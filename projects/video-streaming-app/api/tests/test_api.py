"""Unit tests for the FastAPI web tier.

boto3 is exercised through botocore.stub.Stubber (DynamoDB get/query/delete,
S3 list/delete); upload_fileobj + update_item on the happy path are recorded via
monkeypatch so key/metadata/row construction can be asserted without stubbing a
managed-multipart transfer. The signing key is a locally generated test RSA key
loaded from a temp PEM (no AWS).
"""
import io
import os
import re
import sys

import pytest
from botocore.stub import Stubber
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main
import signing

VIDEO_ID = "a" * 32


def _gen_pem() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )


@pytest.fixture
def key_file(tmp_path):
    pem_path = tmp_path / "cf_private.pem"
    pem_path.write_bytes(_gen_pem())
    return str(pem_path)


@pytest.fixture
def client(monkeypatch, key_file):
    """TestClient whose signer is loaded from a local test key (so /health 200)."""
    monkeypatch.setattr(
        main, "signer",
        signing.Signer(main.CF_KEY_SECRET_ARN, main.CF_KEY_PAIR_ID, key_file=key_file),
    )
    with TestClient(main.app) as c:
        yield c


def _set_cookie_headers(response) -> str:
    return ";".join(v for k, v in response.headers.multi_items() if k.lower() == "set-cookie")


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_safe_filename_sanitizes_and_preserves_extension():
    assert main.safe_filename("my movie!.mp4") == "my_movie_.mp4"
    assert main.safe_filename("../../etc/passwd") == "passwd"
    assert main.safe_filename("a/b\\c.mov") == "c.mov"
    assert main.safe_filename("") == "video"
    assert main.safe_filename("///") == "video"


def test_safe_filename_clamps_to_200_bytes_keeping_extension():
    name = "x" * 500 + ".mp4"
    out = main.safe_filename(name)
    assert len(out.encode("utf-8")) <= 200
    assert out.endswith(".mp4")


def test_input_key_embeds_video_id_prefix():
    assert main.input_key(VIDEO_ID, "clip.mp4") == f"input/{VIDEO_ID}/clip.mp4"


def test_limited_reader_aborts_over_cap():
    reader = main._LimitedReader(io.BytesIO(b"0123456789"), limit=4)
    with pytest.raises(main.UploadTooLarge):
        reader.read()


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #
def test_health_200_when_key_loaded(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_503_when_key_absent(monkeypatch, tmp_path):
    missing = str(tmp_path / "does-not-exist.pem")
    monkeypatch.setattr(
        main, "signer",
        signing.Signer(main.CF_KEY_SECRET_ARN, main.CF_KEY_PAIR_ID, key_file=missing),
    )
    with TestClient(main.app) as c:
        r = c.get("/health")
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# POST /videos
# --------------------------------------------------------------------------- #
def test_post_rejects_non_video_content_type(client):
    r = client.post("/videos", files={"file": ("note.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_post_rejects_oversize_declared_length(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 2)
    r = client.post("/videos", files={"file": ("clip.mp4", b"0123456789", "video/mp4")})
    assert r.status_code == 400


def test_post_builds_key_metadata_and_queued_row(client, monkeypatch):
    captured = {}

    def fake_upload(fileobj, bucket, key, ExtraArgs=None):
        fileobj.read()
        captured["bucket"] = bucket
        captured["key"] = key
        captured["extra"] = ExtraArgs

    def fake_update(**kwargs):
        captured["update"] = kwargs
        return {}

    monkeypatch.setattr(main.s3, "upload_fileobj", fake_upload)
    monkeypatch.setattr(main.ddb, "update_item", fake_update)

    r = client.post(
        "/videos",
        files={"file": ("my movie!.mp4", b"rawbytes", "video/mp4")},
        data={"title": "Holiday"},
    )
    assert r.status_code == 200
    body = r.json()
    video_id = body["video_id"]
    assert re.match(r"^[0-9a-f]{32}$", video_id)
    assert body["status"] == "Queued"

    assert captured["bucket"] == main.INPUT_BUCKET
    assert captured["key"] == f"input/{video_id}/my_movie_.mp4"
    assert captured["extra"]["Metadata"] == {"video-id": video_id}
    assert captured["extra"]["ContentType"] == "video/mp4"

    values = captured["update"]["ExpressionAttributeValues"]
    assert values[":s"]["S"] == "Queued"
    assert values[":g"]["S"] == "VIDEO"
    assert values[":t"]["S"] == "Holiday"
    # The unsanitized original filename is stored verbatim for display.
    assert values[":o"]["S"] == "my movie!.mp4"
    assert ":c" in values


def test_post_compensating_delete_on_update_failure(client, monkeypatch):
    from botocore.exceptions import ClientError

    deleted = {}

    def fake_upload(fileobj, bucket, key, ExtraArgs=None):
        fileobj.read()

    def fake_update(**kwargs):
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}},
                          "UpdateItem")

    def fake_delete(Bucket, Key):
        deleted["bucket"] = Bucket
        deleted["key"] = Key
        return {}

    monkeypatch.setattr(main.s3, "upload_fileobj", fake_upload)
    monkeypatch.setattr(main.ddb, "update_item", fake_update)
    monkeypatch.setattr(main.s3, "delete_object", fake_delete)

    r = client.post("/videos", files={"file": ("clip.mp4", b"x", "video/mp4")})
    assert r.status_code == 502
    assert deleted["bucket"] == main.INPUT_BUCKET
    assert deleted["key"].startswith("input/")


# --------------------------------------------------------------------------- #
# GET /videos (GSI query, no scan)
# --------------------------------------------------------------------------- #
def test_list_videos_uses_gsi_query(client):
    stub = Stubber(main.ddb)
    stub.add_response(
        "query",
        {"Items": [{"video_id": {"S": VIDEO_ID}, "status": {"S": "Ready"}}]},
        {
            "TableName": main.TABLE_NAME,
            "IndexName": "by-status-created",
            "KeyConditionExpression": "gsi_pk = :pk",
            "ExpressionAttributeValues": {":pk": {"S": "VIDEO"}},
            "ScanIndexForward": False,
            "Limit": 100,
        },
    )
    stub.activate()
    r = client.get("/videos")
    assert r.status_code == 200
    assert r.json()["videos"][0]["video_id"] == VIDEO_ID
    stub.assert_no_pending_responses()
    stub.deactivate()


# --------------------------------------------------------------------------- #
# GET /videos/{video_id} — exception mapping
# --------------------------------------------------------------------------- #
def test_get_video_absent_item_is_404(client):
    stub = Stubber(main.ddb)
    stub.add_response(
        "get_item", {}, {"TableName": main.TABLE_NAME, "Key": {"video_id": {"S": VIDEO_ID}}}
    )
    stub.activate()
    r = client.get(f"/videos/{VIDEO_ID}")
    assert r.status_code == 404
    stub.deactivate()


def test_get_video_access_denied_is_502_not_404(client):
    stub = Stubber(main.ddb)
    stub.add_client_error("get_item", "AccessDenied")
    stub.activate()
    r = client.get(f"/videos/{VIDEO_ID}")
    # AccessDenied must NOT be masked as 404.
    assert r.status_code == 502
    stub.deactivate()


def test_get_video_resource_not_found_is_500(client):
    stub = Stubber(main.ddb)
    stub.add_client_error("get_item", "ResourceNotFoundException")
    stub.activate()
    r = client.get(f"/videos/{VIDEO_ID}")
    assert r.status_code == 500
    stub.deactivate()


def test_get_video_bad_path_param_is_400(client):
    r = client.get("/videos/not-a-valid-id")
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# GET /videos/{video_id}/play-url
# --------------------------------------------------------------------------- #
def test_play_url_ready_sets_scoped_signed_cookies(client):
    stub = Stubber(main.ddb)
    stub.add_response(
        "get_item",
        {"Item": {"video_id": {"S": VIDEO_ID}, "status": {"S": "Ready"}}},
    )
    stub.activate()
    r = client.get(f"/videos/{VIDEO_ID}/play-url")
    assert r.status_code == 200
    assert r.json()["mode"] == "cookie"
    assert r.json()["play_url"].endswith(f"/media/{VIDEO_ID}/playlist.m3u8")

    set_cookie = _set_cookie_headers(r)
    assert "CloudFront-Policy=" in set_cookie
    assert "CloudFront-Signature=" in set_cookie
    assert f"CloudFront-Key-Pair-Id={main.CF_KEY_PAIR_ID}" in set_cookie
    assert f"Path=/media/{VIDEO_ID}/" in set_cookie
    stub.deactivate()


def test_play_url_not_ready_is_409_with_status(client):
    stub = Stubber(main.ddb)
    stub.add_response(
        "get_item",
        {"Item": {"video_id": {"S": VIDEO_ID}, "status": {"S": "Queued"}}},
    )
    stub.activate()
    r = client.get(f"/videos/{VIDEO_ID}/play-url")
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "Queued"
    stub.deactivate()


def test_play_url_local_mode_returns_rewritten_playlist_endpoint(client, monkeypatch):
    monkeypatch.setattr(main, "PLAYBACK_MODE", "signed-url")
    stub = Stubber(main.ddb)
    stub.add_response(
        "get_item",
        {"Item": {"video_id": {"S": VIDEO_ID}, "status": {"S": "Ready"}}},
    )
    stub.activate()
    r = client.get(f"/videos/{VIDEO_ID}/play-url")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "signed-url"
    # A URL to THIS API's rewritten-playlist endpoint, not a CloudFront URL.
    assert body["play_url"].endswith(f"/videos/{VIDEO_ID}/playlist.m3u8")
    assert _set_cookie_headers(r) == ""  # no cookies in local mode
    stub.deactivate()


# --------------------------------------------------------------------------- #
# DELETE /videos/{video_id}
# --------------------------------------------------------------------------- #
def test_delete_video_clears_both_prefixes(client):
    ddb_stub = Stubber(main.ddb)
    ddb_stub.add_response(
        "delete_item", {},
        {"TableName": main.TABLE_NAME, "Key": {"video_id": {"S": VIDEO_ID}}},
    )
    s3_stub = Stubber(main.s3)
    s3_stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": f"input/{VIDEO_ID}/clip.mp4"}]},
        {"Bucket": main.INPUT_BUCKET, "Prefix": f"input/{VIDEO_ID}/"},
    )
    s3_stub.add_response(
        "delete_objects",
        {"Deleted": [{"Key": f"input/{VIDEO_ID}/clip.mp4"}]},
        {"Bucket": main.INPUT_BUCKET,
         "Delete": {"Objects": [{"Key": f"input/{VIDEO_ID}/clip.mp4"}]}},
    )
    s3_stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": f"output/{VIDEO_ID}/playlist.m3u8"}]},
        {"Bucket": main.OUTPUT_BUCKET, "Prefix": f"output/{VIDEO_ID}/"},
    )
    s3_stub.add_response(
        "delete_objects",
        {"Deleted": [{"Key": f"output/{VIDEO_ID}/playlist.m3u8"}]},
        {"Bucket": main.OUTPUT_BUCKET,
         "Delete": {"Objects": [{"Key": f"output/{VIDEO_ID}/playlist.m3u8"}]}},
    )
    ddb_stub.activate()
    s3_stub.activate()
    r = client.delete(f"/videos/{VIDEO_ID}")
    assert r.status_code == 200
    assert r.json()["deleted"] == VIDEO_ID
    ddb_stub.assert_no_pending_responses()
    s3_stub.assert_no_pending_responses()
    ddb_stub.deactivate()
    s3_stub.deactivate()
