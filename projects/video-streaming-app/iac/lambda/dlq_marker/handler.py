"""DLQ-marker Lambda -- marks worker-crashed jobs ``Failed``.

Event source: ``VideoQueue-DLQ``. A message lands here only after SQS has
redelivered it ``maxReceiveCount`` times, i.e. the worker process was killed
mid-job (the verified-live 4K OOM case) and could never write ``Failed`` itself.
This Lambda is the only path that closes the ``Failed`` flag for the crash case.

See DESIGN.md "SQS + DLQ" (two-writer Failed status) and "Testability". The
control-message guard and the ``video_id``-from-key-prefix parse mirror the
worker exactly, so a shapeless or non-conforming body is logged and dropped
instead of attempting an ``UpdateItem`` for a nonexistent row.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger("video-dlq-marker")
LOG.setLevel(logging.INFO)

# video_id is the hex uuid4 embedded in the key PREFIX only: input/<id>/<file>.
VIDEO_ID_RE = re.compile(r"^input/(?P<video_id>[0-9a-f]{32})/")

_DDB = None


def _ddb():
    """Lazily create (and cache) the DynamoDB client so tests can inject a stub."""
    global _DDB
    if _DDB is None:
        _DDB = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _DDB


def parse_video_id(key: str | None) -> str | None:
    """Return the video_id from an S3 key prefix, or None if it does not match."""
    if not key:
        return None
    match = VIDEO_ID_RE.match(key)
    return match.group("video_id") if match else None


def extract_object_key(body: str) -> str | None:
    """Pull the S3 object key out of a (DLQ) SQS message body.

    Returns None for the control-message shapes that must be dropped without
    processing: non-JSON bodies, the s3:TestEvent control message, and any body
    lacking Records[0].s3.object.key.
    """
    try:
        message = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(message, dict):
        return None
    if message.get("Event") == "s3:TestEvent":
        return None
    records = message.get("Records")
    if not isinstance(records, list) or not records:
        return None
    try:
        key = records[0]["s3"]["object"]["key"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(key, str):
        return None
    return urllib.parse.unquote_plus(key)


def process_record(ddb: object, table: str, body: str) -> None:
    """Mark one DLQ body's video_id Failed.

    Returns normally when the message should be DELETED (control-message drop,
    no-such-row, or a successful Failed write). Raises on a transient DynamoDB
    error so the event source mapping leaves the message for another attempt.
    """
    key = extract_object_key(body)
    video_id = parse_video_id(key) if key else None
    if video_id is None:
        LOG.info("dropping control / non-conforming DLQ message (no input/<id>/ key)")
        return

    try:
        ddb.update_item(
            TableName=table,
            Key={"video_id": {"S": video_id}},
            UpdateExpression="SET #s = :s",
            ConditionExpression="attribute_exists(video_id)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": {"S": "Failed"}},
        )
        LOG.info("video %s marked Failed (worker-crash path)", video_id)
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Orphan with no catalog row (compensating-delete case): nothing to
            # mark. Drop it rather than upserting a spurious row.
            LOG.info("no catalog row for %s; dropping", video_id)
            return
        raise


def handler(event: dict, context: object) -> dict:
    table = os.environ["TABLE_NAME"]
    ddb = _ddb()
    for record in event.get("Records", []):
        process_record(ddb, table, record.get("body", ""))
    return {"batchItemFailures": []}
