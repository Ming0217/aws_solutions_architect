"""Unit tests for the CloudFront signing module.

A test RSA key is generated locally; Secrets Manager is exercised via
botocore.stub.Stubber. Assertions cover the scoped Resource, the 6h TTL, the
CloudFront-Key-Pair-Id == CF_KEY_PAIR_ID requirement, and a full
signature-verifies-against-the-public-key round trip.
"""
import base64
import json
import os
import sys
import time

import boto3
import pytest
from botocore.stub import Stubber
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import signing

KEY_PAIR_ID = "K2EXAMPLEKEYID"
ARN = "arn:aws:secretsmanager:us-east-1:678602035067:secret:video/cf-signing-key"
VIDEO_ID = "a" * 32
TTL = 6 * 60 * 60


def _gen_pem() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )


def _un_cf_b64(value: str) -> bytes:
    restored = value.replace("-", "+").replace("_", "=").replace("~", "/")
    return base64.b64decode(restored)


@pytest.fixture
def signer(tmp_path):
    pem_path = tmp_path / "cf_private.pem"
    pem_path.write_bytes(_gen_pem())
    s = signing.Signer(ARN, KEY_PAIR_ID, key_file=str(pem_path))
    s.load()
    return s


def test_load_from_secrets_manager():
    pem = _gen_pem()
    client = boto3.client(
        "secretsmanager", region_name="us-east-1",
        aws_access_key_id="x", aws_secret_access_key="x",
    )
    stub = Stubber(client)
    stub.add_response("get_secret_value", {"SecretString": pem.decode()}, {"SecretId": ARN})
    stub.activate()
    s = signing.Signer(ARN, KEY_PAIR_ID, secrets_client=client)
    assert not s.loaded
    s.load()
    assert s.loaded
    stub.assert_no_pending_responses()
    stub.deactivate()


def test_sign_cookies_scope_ttl_and_keypair_id(signer):
    before = int(time.time())
    resource = f"https://d123.cloudfront.net/media/{VIDEO_ID}/*"
    cookies = signer.sign_cookies(resource, TTL)

    assert set(cookies) == {
        "CloudFront-Policy", "CloudFront-Signature", "CloudFront-Key-Pair-Id",
    }
    # MUST use the PUBLIC KEY id for the Key-Pair-Id field.
    assert cookies["CloudFront-Key-Pair-Id"] == KEY_PAIR_ID

    policy = json.loads(_un_cf_b64(cookies["CloudFront-Policy"]))
    statement = policy["Statement"][0]
    # Scoped to this one video's media prefix.
    assert statement["Resource"] == f"https://d123.cloudfront.net/media/{VIDEO_ID}/*"
    expiry = statement["Condition"]["DateLessThan"]["AWS:EpochTime"]
    assert before + TTL <= expiry <= int(time.time()) + TTL + 5


def test_sign_url_custom_policy_params(signer):
    url = f"https://d123.cloudfront.net/media/{VIDEO_ID}/seg0.ts"
    signed = signer.sign_url(url, TTL)
    assert signed.startswith(url + "?")

    query = signed.split("?", 1)[1]
    params = dict(part.split("=", 1) for part in query.split("&"))
    assert params["Key-Pair-Id"] == KEY_PAIR_ID
    assert "Policy" in params and "Signature" in params
    policy = json.loads(_un_cf_b64(params["Policy"]))
    # A signed URL's custom policy pins the exact resource URL.
    assert policy["Statement"][0]["Resource"] == url


def test_rewrite_playlist_signs_only_segment_lines(signer):
    base = f"https://d123.cloudfront.net/media/{VIDEO_ID}"
    playlist = (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n"
        "#EXTINF:6.0,\nseg0.ts\n#EXTINF:6.0,\nseg1.ts\n#EXT-X-ENDLIST\n"
    )
    out = signing.rewrite_playlist(playlist, base, signer, TTL)
    lines = out.splitlines()

    assert lines[0] == "#EXTM3U"  # comment/tag lines pass through
    segment_lines = [ln for ln in lines if ln.startswith(f"{base}/seg")]
    assert len(segment_lines) == 2
    for line in segment_lines:
        assert "Policy=" in line
        assert f"Key-Pair-Id={KEY_PAIR_ID}" in line


def test_signature_verifies_against_public_key(tmp_path):
    pem = _gen_pem()
    pem_path = tmp_path / "cf_private.pem"
    pem_path.write_bytes(pem)
    s = signing.Signer(ARN, KEY_PAIR_ID, key_file=str(pem_path))
    s.load()
    public_key = serialization.load_pem_private_key(pem, password=None).public_key()

    url = f"https://d123.cloudfront.net/media/{VIDEO_ID}/seg0.ts"
    signed = s.sign_url(url, TTL)
    params = dict(part.split("=", 1) for part in signed.split("?", 1)[1].split("&"))
    policy_bytes = _un_cf_b64(params["Policy"])
    signature = _un_cf_b64(params["Signature"])

    # Raises InvalidSignature if the chain (RSA-SHA1/PKCS1v15) is wrong.
    public_key.verify(signature, policy_bytes, padding.PKCS1v15(), hashes.SHA1())


def test_ensure_fresh_reloads_after_ttl(tmp_path):
    pem_path = tmp_path / "cf_private.pem"
    pem_path.write_bytes(_gen_pem())
    s = signing.Signer(ARN, KEY_PAIR_ID, key_file=str(pem_path), refresh_seconds=0)
    s.load()
    first = s._private_key
    # refresh_seconds=0 -> every sign op re-reads the key file.
    pem_path.write_bytes(_gen_pem())
    s.sign_url("https://d123.cloudfront.net/x", TTL)
    assert s._private_key is not first
