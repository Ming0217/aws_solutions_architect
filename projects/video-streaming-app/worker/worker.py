"""Hardened FFmpeg transcode worker.

Long-polls VideoQueue, downloads the raw upload, transcodes it to a 720p
H.264-baseline/AAC HLS rendition, uploads the playlist + segments to the Output
bucket, and advances the DynamoDB catalog row Processing -> Ready. The message
is deleted ONLY on success (or on a deterministic rejection); transient errors
are left for SQS redelivery.

Design: see projects/video-streaming-app/DESIGN.md sections "SQS + DLQ",
"Worker ASG - queue-depth scaling", "video_id - single correlation id",
"FFmpeg sourcing + downscale", and "Testability".

Resource names are injected by env so local and deployed runs use the identical
code path:
  QUEUE_URL, INPUT_BUCKET, OUTPUT_BUCKET, TABLE_NAME  (required)
  ASG_NAME, LIFECYCLE_HOOK_NAME                        (graceful drain; optional)
  AWS_REGION, FFMPEG_BIN                               (optional, defaulted)
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import tempfile
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger("video-worker")

# video_id is the hex uuid4 embedded in the key PREFIX only: input/<id>/<file>.
# The worker never derives it from the filename.
VIDEO_ID_RE = re.compile(r"^input/(?P<video_id>[0-9a-f]{32})/")

# How long to block in a single ffmpeg wait() before emitting a lifecycle
# heartbeat / checking for a drain request. Well under the 900s hook timeout.
HEARTBEAT_INTERVAL = 30.0

# SQS long-poll wait (seconds).
RECEIVE_WAIT_SECONDS = 20


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested directly)
# --------------------------------------------------------------------------- #
def parse_video_id(key: str | None) -> str | None:
    """Return the video_id from an S3 key prefix, or None if it does not match."""
    if not key:
        return None
    match = VIDEO_ID_RE.match(key)
    return match.group("video_id") if match else None


def extract_object_key(body: str) -> str | None:
    """Pull the S3 object key out of an SQS message body.

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
    # S3 event keys are URL-encoded (e.g. '+' for space).
    return urllib.parse.unquote_plus(key)


def build_ffmpeg_cmd(local_in: str, out_dir: str, ffmpeg_bin: str = "ffmpeg") -> list[str]:
    """Assemble the exact transcode argv: 720p, H.264 baseline level 3.1, AAC, HLS."""
    return [
        ffmpeg_bin,
        "-i", str(local_in),
        "-vf", "scale=-2:720",
        "-c:v", "libx264",
        "-profile:v", "baseline",
        "-level", "3.1",
        "-c:a", "aac",
        "-f", "hls",
        "-hls_time", "6",
        "-hls_playlist_type", "vod",
        str(Path(out_dir) / "playlist.m3u8"),
    ]


def _content_type(name: str) -> str:
    if name.endswith(".m3u8"):
        return "application/vnd.apple.mpegurl"
    if name.endswith(".ts"):
        return "video/mp2t"
    return "application/octet-stream"


# --------------------------------------------------------------------------- #
# Config / clients / drain flag
# --------------------------------------------------------------------------- #
@dataclass
class Config:
    queue_url: str
    input_bucket: str
    output_bucket: str
    table: str
    asg_name: str | None = None
    lifecycle_hook: str | None = None
    instance_id: str | None = None
    region: str = "us-east-1"
    ffmpeg_bin: str = "/usr/local/bin/ffmpeg"


@dataclass
class Clients:
    sqs: object
    s3: object
    ddb: object
    asg: object


class DrainFlag:
    """Thread-safe flag set by the SIGTERM handler to request a graceful drain."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self, *_args: object) -> None:
        self._event.set()

    @property
    def requested(self) -> bool:
        return self._event.is_set()


# --------------------------------------------------------------------------- #
# DynamoDB status helpers (update_item only, never put_item)
# --------------------------------------------------------------------------- #
def get_status(ddb: object, table: str, video_id: str) -> str | None:
    resp = ddb.get_item(TableName=table, Key={"video_id": {"S": video_id}})
    item = resp.get("Item")
    if not item:
        return None
    return item.get("status", {}).get("S")


def set_status(ddb: object, table: str, video_id: str, status: str) -> None:
    # "status" is a DynamoDB reserved word -> alias it.
    ddb.update_item(
        TableName=table,
        Key={"video_id": {"S": video_id}},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": {"S": status}},
    )


# --------------------------------------------------------------------------- #
# S3 transfer (plain get_object/put_object so boto3 stays Stubber-friendly)
# --------------------------------------------------------------------------- #
def download_input(s3: object, bucket: str, key: str, dest: str) -> None:
    resp = s3.get_object(Bucket=bucket, Key=key)
    with open(dest, "wb") as handle:
        handle.write(resp["Body"].read())


def upload_outputs(s3: object, bucket: str, video_id: str, out_dir: str) -> None:
    for name in sorted(os.listdir(out_dir)):
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as handle:
            data = handle.read()
        s3.put_object(
            Bucket=bucket,
            Key=f"output/{video_id}/{name}",
            Body=data,
            ContentType=_content_type(name),
        )


# --------------------------------------------------------------------------- #
# Transcode subprocess (mocked in tests)
# --------------------------------------------------------------------------- #
def run_transcode(
    cmd: list[str],
    on_heartbeat: Callable[[], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> int:
    """Run ffmpeg, emitting a heartbeat each HEARTBEAT_INTERVAL and aborting
    cleanly if a drain is requested. Returns the process exit code."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while True:
        try:
            proc.wait(timeout=HEARTBEAT_INTERVAL)
            break
        except subprocess.TimeoutExpired:
            if on_heartbeat is not None:
                on_heartbeat()
            if should_abort is not None and should_abort():
                LOG.info("drain requested mid-transcode; aborting ffmpeg")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break
    return proc.returncode


# --------------------------------------------------------------------------- #
# Lifecycle-hook (graceful drain) helpers
# --------------------------------------------------------------------------- #
def _lifecycle_ready(cfg: Config) -> bool:
    return bool(cfg.asg_name and cfg.lifecycle_hook and cfg.instance_id)


def send_heartbeat(clients: Clients, cfg: Config) -> None:
    if not _lifecycle_ready(cfg):
        return
    try:
        clients.asg.record_lifecycle_action_heartbeat(
            AutoScalingGroupName=cfg.asg_name,
            LifecycleHookName=cfg.lifecycle_hook,
            InstanceId=cfg.instance_id,
        )
    except ClientError:
        LOG.warning("RecordLifecycleActionHeartbeat failed", exc_info=True)


def complete_drain(clients: Clients, cfg: Config) -> None:
    if not _lifecycle_ready(cfg):
        return
    try:
        clients.asg.complete_lifecycle_action(
            AutoScalingGroupName=cfg.asg_name,
            LifecycleHookName=cfg.lifecycle_hook,
            InstanceId=cfg.instance_id,
            LifecycleActionResult="CONTINUE",
        )
    except ClientError:
        LOG.warning("CompleteLifecycleAction failed", exc_info=True)


# --------------------------------------------------------------------------- #
# Per-message processing
# --------------------------------------------------------------------------- #
def process_message(
    clients: Clients, cfg: Config, body: str, drain: DrainFlag | None = None
) -> None:
    """Process one SQS message body.

    Returns normally when the message should be DELETED (success, idempotent
    skip, control-message drop, or a deterministic FFmpeg rejection). Raises
    when the message must be LEFT for redelivery (transient boto3/OS error).
    """
    key = extract_object_key(body)
    video_id = parse_video_id(key) if key else None
    if video_id is None:
        LOG.info("dropping control / non-conforming message (no input/<id>/ key)")
        return  # delete without processing

    # Idempotency: a message that reappears after the row is already Ready is a
    # no-op. The get_item itself is a boto3 call -> a transient failure here
    # propagates and the message is redelivered.
    status = get_status(clients.ddb, cfg.table, video_id)
    if status == "Ready":
        LOG.info("video %s already Ready; skipping", video_id)
        return  # delete

    with tempfile.TemporaryDirectory(prefix="vid-") as tmp:
        local_in = os.path.join(tmp, "input")
        out_dir = os.path.join(tmp, "out")
        os.makedirs(out_dir, exist_ok=True)

        # Transient path: any boto3/OS error here propagates -> redelivery.
        download_input(clients.s3, cfg.input_bucket, key, local_in)
        set_status(clients.ddb, cfg.table, video_id, "Processing")

        cmd = build_ffmpeg_cmd(local_in, out_dir, cfg.ffmpeg_bin)
        LOG.info("transcoding %s", video_id)
        returncode = run_transcode(
            cmd,
            on_heartbeat=lambda: send_heartbeat(clients, cfg),
            should_abort=(lambda: drain.requested) if drain is not None else None,
        )

        if returncode != 0:
            # Deterministic rejection: the same bytes fail every time, so do not
            # retry. Mark Failed and delete the message.
            LOG.warning("ffmpeg exit %s for %s -> Failed (deterministic)", returncode, video_id)
            set_status(clients.ddb, cfg.table, video_id, "Failed")
            return  # delete, no retry

        # Transient path again: upload / final state write can be retried.
        upload_outputs(clients.s3, cfg.output_bucket, video_id, out_dir)
        set_status(clients.ddb, cfg.table, video_id, "Ready")
        LOG.info("video %s Ready", video_id)
        return  # delete


# --------------------------------------------------------------------------- #
# Consume loop
# --------------------------------------------------------------------------- #
def run_loop(clients: Clients, cfg: Config, drain: DrainFlag) -> None:
    while not drain.requested:
        resp = clients.sqs.receive_message(
            QueueUrl=cfg.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=RECEIVE_WAIT_SECONDS,
        )
        for message in resp.get("Messages", []):
            try:
                process_message(clients, cfg, message["Body"], drain)
            except (ClientError, OSError):
                # Transient failure: leave the message invisible so SQS
                # redelivers it; only maxReceiveCount=3 genuine retries
                # dead-letter it.
                LOG.exception("transient error; leaving message for redelivery")
                continue
            clients.sqs.delete_message(
                QueueUrl=cfg.queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )
    # SIGTERM received: release the ASG termination lifecycle hook.
    LOG.info("drain complete; releasing lifecycle hook")
    complete_drain(clients, cfg)


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
def _fetch_instance_id(timeout: float = 1.0) -> str | None:
    """Best-effort IMDSv2 lookup of this instance's id (None off-EC2)."""
    import urllib.error
    import urllib.request

    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        token = urllib.request.urlopen(token_req, timeout=timeout).read().decode()
        id_req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
        )
        return urllib.request.urlopen(id_req, timeout=timeout).read().decode()
    except (urllib.error.URLError, OSError, ValueError):
        return None


def build_config() -> Config:
    return Config(
        queue_url=os.environ["QUEUE_URL"],
        input_bucket=os.environ["INPUT_BUCKET"],
        output_bucket=os.environ["OUTPUT_BUCKET"],
        table=os.environ["TABLE_NAME"],
        asg_name=os.environ.get("ASG_NAME") or None,
        lifecycle_hook=os.environ.get("LIFECYCLE_HOOK_NAME") or None,
        instance_id=os.environ.get("INSTANCE_ID") or _fetch_instance_id(),
        region=os.environ.get("AWS_REGION", "us-east-1"),
        ffmpeg_bin=os.environ.get("FFMPEG_BIN", "/usr/local/bin/ffmpeg"),
    )


def build_clients(cfg: Config) -> Clients:
    return Clients(
        sqs=boto3.client("sqs", region_name=cfg.region),
        s3=boto3.client("s3", region_name=cfg.region),
        ddb=boto3.client("dynamodb", region_name=cfg.region),
        asg=boto3.client("autoscaling", region_name=cfg.region),
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = build_config()
    clients = build_clients(cfg)
    drain = DrainFlag()
    signal.signal(signal.SIGTERM, drain.request)
    signal.signal(signal.SIGINT, drain.request)
    LOG.info("worker starting; polling %s", cfg.queue_url)
    run_loop(clients, cfg, drain)


if __name__ == "__main__":
    main()
