"""Unit tests for the FFmpeg transcode worker.

boto3 is exercised through botocore.stub.Stubber (no network, no moto); the
ffmpeg subprocess is replaced by monkeypatching worker.run_transcode.
"""
import io
import json
import os
import sys

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import worker

VIDEO_ID = "a" * 32
INPUT_KEY = f"input/{VIDEO_ID}/clip.mp4"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def cfg():
    return worker.Config(
        queue_url="https://sqs.us-east-1.amazonaws.com/123/VideoQueue",
        input_bucket="video-input-678602035067-us-east-1",
        output_bucket="video-output-678602035067-us-east-1",
        table="VideoCatalog",
        ffmpeg_bin="ffmpeg",
    )


def _client(service):
    return boto3.client(service, region_name="us-east-1",
                        aws_access_key_id="x", aws_secret_access_key="x")


@pytest.fixture
def clients():
    c = worker.Clients(
        sqs=_client("sqs"),
        s3=_client("s3"),
        ddb=_client("dynamodb"),
        asg=_client("autoscaling"),
    )
    stubs = {
        "sqs": Stubber(c.sqs),
        "s3": Stubber(c.s3),
        "ddb": Stubber(c.ddb),
        "asg": Stubber(c.asg),
    }
    for s in stubs.values():
        s.activate()
    yield c, stubs
    for s in stubs.values():
        s.assert_no_pending_responses()
        s.deactivate()


def _s3_event_body(key=INPUT_KEY):
    return json.dumps({"Records": [{"s3": {"object": {"key": key}}}]})


def _streaming_body(data: bytes) -> StreamingBody:
    return StreamingBody(io.BytesIO(data), len(data))


def _get_item_status(status):
    if status is None:
        return {}
    return {"Item": {"video_id": {"S": VIDEO_ID}, "status": {"S": status}}}


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_parse_video_id_from_key_prefix():
    assert worker.parse_video_id(INPUT_KEY) == VIDEO_ID


def test_parse_video_id_ignores_filename_and_bad_prefix():
    # id-looking token in the filename must NOT be picked up.
    assert worker.parse_video_id(f"input/notanid/{VIDEO_ID}.mp4") is None
    assert worker.parse_video_id(f"output/{VIDEO_ID}/playlist.m3u8") is None
    assert worker.parse_video_id(None) is None


def test_extract_object_key_from_s3_event():
    assert worker.extract_object_key(_s3_event_body()) == INPUT_KEY


def test_extract_object_key_url_decodes():
    body = _s3_event_body(key=f"input/{VIDEO_ID}/a+b.mp4")
    assert worker.extract_object_key(body) == f"input/{VIDEO_ID}/a b.mp4"


def test_extract_object_key_drops_control_shapes():
    assert worker.extract_object_key("not json") is None
    assert worker.extract_object_key(
        json.dumps({"Service": "Amazon S3", "Event": "s3:TestEvent"})) is None
    assert worker.extract_object_key(json.dumps({"Records": []})) is None
    assert worker.extract_object_key(json.dumps({"foo": "bar"})) is None


def test_build_ffmpeg_cmd_assembly():
    cmd = worker.build_ffmpeg_cmd("/tmp/in", "/tmp/out", "ffmpeg")
    assert cmd[0] == "ffmpeg"
    assert cmd[1:3] == ["-i", "/tmp/in"]
    # The mandated downscale + HLS-safe codec pins.
    assert "-vf" in cmd and cmd[cmd.index("-vf") + 1] == "scale=-2:720"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-profile:v") + 1] == "baseline"
    assert cmd[cmd.index("-level") + 1] == "3.1"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-f") + 1] == "hls"
    assert cmd[-1].endswith("playlist.m3u8")


# --------------------------------------------------------------------------- #
# process_message behaviour
# --------------------------------------------------------------------------- #
def test_control_message_dropped_without_processing(clients, cfg):
    c, _stubs = clients
    body = json.dumps({"Service": "Amazon S3", "Event": "s3:TestEvent"})
    # No stubbed responses => any AWS call would raise. Returning cleanly proves
    # the body was dropped before touching DynamoDB/S3.
    worker.process_message(c, cfg, body)


def test_idempotency_skip_when_already_ready(clients, cfg):
    c, stubs = clients
    stubs["ddb"].add_response(
        "get_item", _get_item_status("Ready"),
        {"TableName": "VideoCatalog", "Key": {"video_id": {"S": VIDEO_ID}}},
    )
    # No s3/ddb-write responses stubbed: a Ready row must short-circuit.
    worker.process_message(c, cfg, _s3_event_body())


def test_failed_on_nonzero_exit_writes_failed_and_returns(clients, cfg, monkeypatch):
    c, stubs = clients
    stubs["ddb"].add_response("get_item", _get_item_status("Queued"))
    stubs["s3"].add_response(
        "get_object", {"Body": _streaming_body(b"rawbytes")},
        {"Bucket": cfg.input_bucket, "Key": INPUT_KEY},
    )
    stubs["ddb"].add_response("update_item", {})  # Processing
    stubs["ddb"].add_response(
        "update_item", {},
        {
            "TableName": "VideoCatalog",
            "Key": {"video_id": {"S": VIDEO_ID}},
            "UpdateExpression": "SET #s = :s",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":s": {"S": "Failed"}},
        },
    )
    monkeypatch.setattr(worker, "run_transcode", lambda *a, **k: 1)
    # Returns normally (=> caller deletes the message); no upload happens.
    worker.process_message(c, cfg, _s3_event_body())


def test_transient_get_object_error_is_reraised(clients, cfg):
    c, stubs = clients
    stubs["ddb"].add_response("get_item", _get_item_status("Queued"))
    stubs["s3"].add_client_error("get_object", "InternalError")
    with pytest.raises(ClientError):
        worker.process_message(c, cfg, _s3_event_body())


def test_success_path_uploads_and_marks_ready(clients, cfg, monkeypatch):
    c, stubs = clients
    stubs["ddb"].add_response("get_item", _get_item_status("Queued"))
    stubs["s3"].add_response(
        "get_object", {"Body": _streaming_body(b"rawbytes")},
        {"Bucket": cfg.input_bucket, "Key": INPUT_KEY},
    )
    stubs["ddb"].add_response("update_item", {})  # Processing
    stubs["s3"].add_response(
        "put_object", {},
        {
            "Bucket": cfg.output_bucket,
            "Key": f"output/{VIDEO_ID}/playlist.m3u8",
            "Body": b"#EXTM3U\n",
            "ContentType": "application/vnd.apple.mpegurl",
        },
    )
    stubs["ddb"].add_response(
        "update_item", {},
        {
            "TableName": "VideoCatalog",
            "Key": {"video_id": {"S": VIDEO_ID}},
            "UpdateExpression": "SET #s = :s",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":s": {"S": "Ready"}},
        },
    )

    def fake_transcode(cmd, **kwargs):
        with open(cmd[-1], "wb") as handle:  # cmd[-1] == <out_dir>/playlist.m3u8
            handle.write(b"#EXTM3U\n")
        return 0

    monkeypatch.setattr(worker, "run_transcode", fake_transcode)
    worker.process_message(c, cfg, _s3_event_body())


# --------------------------------------------------------------------------- #
# Consume loop: delete-on-success vs leave-on-transient
# --------------------------------------------------------------------------- #
def test_loop_deletes_on_success(cfg, monkeypatch):
    sqs = _client("sqs")
    stub = Stubber(sqs)
    stub.add_response(
        "receive_message",
        {"Messages": [{"Body": _s3_event_body(), "ReceiptHandle": "rh-1"}]},
    )
    stub.add_response(
        "delete_message", {},
        {"QueueUrl": cfg.queue_url, "ReceiptHandle": "rh-1"},
    )
    stub.add_response("receive_message", {"Messages": []})
    stub.activate()

    drain = worker.DrainFlag()
    calls = {"n": 0}

    def fake_process(*a, **k):
        calls["n"] += 1

    def fake_receive(**kwargs):
        if calls["n"] >= 1:
            drain.request()
        return sqs.receive_message(**kwargs)

    monkeypatch.setattr(worker, "process_message", fake_process)
    c = worker.Clients(sqs=_WrappedSqs(sqs, fake_receive), s3=None, ddb=None, asg=None)
    worker.run_loop(c, cfg, drain)
    stub.assert_no_pending_responses()
    stub.deactivate()


def test_loop_leaves_message_on_transient_error(cfg, monkeypatch):
    sqs = _client("sqs")
    stub = Stubber(sqs)
    stub.add_response(
        "receive_message",
        {"Messages": [{"Body": _s3_event_body(), "ReceiptHandle": "rh-1"}]},
    )
    # No delete_message stubbed: a transient error must NOT delete.
    stub.activate()

    drain = worker.DrainFlag()

    def fake_process(*a, **k):
        drain.request()
        raise OSError("disk full")

    monkeypatch.setattr(worker, "process_message", fake_process)
    c = worker.Clients(sqs=sqs, s3=None, ddb=None, asg=None)
    worker.run_loop(c, cfg, drain)
    stub.assert_no_pending_responses()
    stub.deactivate()


class _WrappedSqs:
    """Lets the loop's receive_message trip the drain flag after one message."""

    def __init__(self, real, receive_fn):
        self._real = real
        self._receive_fn = receive_fn

    def receive_message(self, **kwargs):
        return self._receive_fn(**kwargs)

    def delete_message(self, **kwargs):
        return self._real.delete_message(**kwargs)
