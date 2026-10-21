"""Unit tests for the DLQ-marker Lambda (botocore.stub.Stubber, no network)."""
import json
import os
import sys

import boto3
import pytest
from botocore.stub import Stubber

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import handler

VIDEO_ID = "a" * 32
INPUT_KEY = f"input/{VIDEO_ID}/clip.mp4"
TABLE = "VideoCatalog"


def _s3_event_body(key: str) -> str:
    return json.dumps({"Records": [{"s3": {"object": {"key": key}}}]})


@pytest.fixture
def ddb():
    client = boto3.client(
        "dynamodb", region_name="us-east-1",
        aws_access_key_id="x", aws_secret_access_key="x",
    )
    stub = Stubber(client)
    stub.activate()
    yield client, stub
    stub.deactivate()


def test_parse_video_id_from_prefix():
    assert handler.parse_video_id(INPUT_KEY) == VIDEO_ID
    assert handler.parse_video_id(f"output/{VIDEO_ID}/playlist.m3u8") is None
    assert handler.parse_video_id("input/not-a-hex/clip.mp4") is None
    assert handler.parse_video_id(None) is None


def test_process_record_marks_failed(ddb):
    client, stub = ddb
    stub.add_response(
        "update_item",
        {},
        {
            "TableName": TABLE,
            "Key": {"video_id": {"S": VIDEO_ID}},
            "UpdateExpression": "SET #s = :s",
            "ConditionExpression": "attribute_exists(video_id)",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":s": {"S": "Failed"}},
        },
    )
    handler.process_record(client, TABLE, _s3_event_body(INPUT_KEY))
    stub.assert_no_pending_responses()


def test_conditional_check_failure_is_dropped(ddb):
    client, stub = ddb
    stub.add_client_error(
        "update_item",
        service_error_code="ConditionalCheckFailedException",
        http_status_code=400,
    )
    # No catalog row -> logged and dropped, no crash, no re-raise.
    handler.process_record(client, TABLE, _s3_event_body(INPUT_KEY))
    stub.assert_no_pending_responses()


def test_control_message_dropped_without_update(ddb):
    client, stub = ddb
    # s3:TestEvent and malformed bodies must never trigger an UpdateItem.
    handler.process_record(client, TABLE, json.dumps({"Event": "s3:TestEvent"}))
    handler.process_record(client, TABLE, "not json at all")
    handler.process_record(client, TABLE, _s3_event_body(f"output/{VIDEO_ID}/x.ts"))
    stub.assert_no_pending_responses()  # zero calls expected


def test_handler_iterates_records(ddb, monkeypatch):
    client, stub = ddb
    monkeypatch.setitem(os.environ, "TABLE_NAME", TABLE)
    monkeypatch.setattr(handler, "_DDB", client)
    stub.add_response(
        "update_item",
        {},
        {
            "TableName": TABLE,
            "Key": {"video_id": {"S": VIDEO_ID}},
            "UpdateExpression": "SET #s = :s",
            "ConditionExpression": "attribute_exists(video_id)",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":s": {"S": "Failed"}},
        },
    )
    event = {"Records": [{"body": _s3_event_body(INPUT_KEY)}]}
    assert handler.handler(event, None) == {"batchItemFailures": []}
    stub.assert_no_pending_responses()
