"""FastAPI JSON web tier for the video-streaming platform.

A self-built JSON API (no inline HTML -- the SPA is separate), run unprivileged
by gunicorn/uvicorn on port 8000 behind the internal ALB. All AWS access uses
the instance's ``video-web-role`` (no credentials in code). Resource names come
from env so the local and deployed runs use the identical code path.

Env (all required unless noted):
  INPUT_BUCKET OUTPUT_BUCKET TABLE_NAME ARTIFACT_BUCKET
  CF_KEY_SECRET_ARN CF_DOMAIN CF_KEY_PAIR_ID
  MAX_UPLOAD_BYTES   (optional, default 2147483648 = 2 GiB)
  PLAYBACK_MODE      (optional: "cookie" prod [default] | "signed-url" local)
  AWS_REGION         (optional, default us-east-1)
  CF_SIGNING_KEY_FILE(optional, LOCAL DEV ONLY: read the private PEM from this
                      path instead of Secrets Manager -- never set in AWS)

Correlation: one ``video_id = uuid4().hex`` derived ONCE here at upload and
threaded through the S3 key prefix (input/<video_id>/...), the x-amz-meta-video-id
object metadata, and the DynamoDB row. See DESIGN.md "FastAPI web tier",
"video_id - single correlation id", and "Local-dev approach".
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

import signing

LOG = logging.getLogger("video-web")

# --------------------------------------------------------------------------- #
# Config (env-driven; same names local and deployed)
# --------------------------------------------------------------------------- #
INPUT_BUCKET = os.environ["INPUT_BUCKET"]
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
TABLE_NAME = os.environ["TABLE_NAME"]
ARTIFACT_BUCKET = os.environ.get("ARTIFACT_BUCKET", "")
CF_KEY_SECRET_ARN = os.environ["CF_KEY_SECRET_ARN"]
CF_DOMAIN = os.environ["CF_DOMAIN"]
CF_KEY_PAIR_ID = os.environ["CF_KEY_PAIR_ID"]
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
PLAYBACK_MODE = os.environ.get("PLAYBACK_MODE", "cookie")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
CF_SIGNING_KEY_FILE = os.environ.get("CF_SIGNING_KEY_FILE") or None

GSI_NAME = "by-status-created"
GSI_PK = "VIDEO"
# Signed-cookie / signed-URL lifetime: 6h, longer than any expected lab clip.
PLAYBACK_TTL_SECONDS = 6 * 60 * 60

VIDEO_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_UNSAFE_RUN = re.compile(r"[^A-Za-z0-9._-]+")

_deserializer = TypeDeserializer()

# boto3 clients (module-level so tests can wrap them with botocore.stub.Stubber).
s3 = boto3.client("s3", region_name=AWS_REGION)
ddb = boto3.client("dynamodb", region_name=AWS_REGION)

# The signing key cache. Loaded once in the lifespan hook below.
signer = signing.Signer(
    CF_KEY_SECRET_ARN,
    CF_KEY_PAIR_ID,
    region=AWS_REGION,
    key_file=CF_SIGNING_KEY_FILE,
)


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested directly)
# --------------------------------------------------------------------------- #
def safe_filename(name: str | None) -> str:
    """Sanitize an untrusted client filename for use in an S3 key (Finding 7).

    Unicode-normalized, path separators + control chars stripped, reduced to
    ``[A-Za-z0-9._-]`` (other runs collapsed to ``_``), clamped to 200 bytes
    keeping the extension; empty-after-sanitize falls back to ``video``.
    """
    if not name:
        return "video"
    name = unicodedata.normalize("NFKD", name)
    name = name.replace("\\", "/").rsplit("/", 1)[-1]  # drop any path
    name = "".join(ch for ch in name if ch >= " " and ch != "\x7f")  # control chars
    name = _UNSAFE_RUN.sub("_", name).strip("_")
    if not name:
        return "video"
    if len(name.encode("utf-8")) <= 200:
        return name
    root, dot, ext = name.rpartition(".")
    if dot and 0 < len(ext) < 190:
        keep = 200 - len(ext) - 1
        return f"{root[:keep]}.{ext}"
    return name[:200]


def input_key(video_id: str, safe_name: str) -> str:
    return f"input/{video_id}/{safe_name}"


def deserialize_item(item: dict) -> dict:
    return {k: _deserializer.deserialize(v) for k, v in item.items()}


def _client_error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


# --------------------------------------------------------------------------- #
# Size-capped stream wrapper for upload_fileobj
# --------------------------------------------------------------------------- #
class UploadTooLarge(Exception):
    """Raised when the uploaded body exceeds MAX_UPLOAD_BYTES mid-stream."""


class _LimitedReader:
    """Wrap a file object so reading past ``limit`` bytes aborts the transfer."""

    def __init__(self, fileobj: object, limit: int) -> None:
        self._f = fileobj
        self._limit = limit
        self._count = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._f.read(size)
        self._count += len(chunk)
        if self._count > self._limit:
            raise UploadTooLarge()
        return chunk


# --------------------------------------------------------------------------- #
# App + lifespan (load the signing key ONCE)
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        signer.load()
        LOG.info("signing key loaded")
    except (ClientError, OSError, ValueError):
        # Fail the health check (ALB pulls the target) rather than serve
        # unsignable play-urls. Never log the key material.
        LOG.exception("failed to load signing key at startup; /health will report 503")
    yield


app = FastAPI(title="Video Streaming API", version="0.1.0", lifespan=lifespan)

# CORS: the CloudFront origin + the two localhost dev origins explicitly (not
# "*"), with credentials so the signed-cookie Set-Cookie/XHR flow works.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"https://{CF_DOMAIN}",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    video_id = request.path_params.get("video_id")
    LOG.exception("unexpected error (video_id=%s): %s", video_id, exc)
    return JSONResponse(status_code=500, content={"detail": "internal error"})


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> Response:
    # Shallow check -- but report 503 until the signing key is loaded so the ALB
    # never routes playback requests we cannot sign.
    if not signer.loaded:
        return JSONResponse(status_code=503, content={"status": "no-signing-key"})
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.post("/videos")
def create_video(
    request: Request,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()] = "",
) -> dict:
    # --- validate at the trust boundary ---
    content_type = file.content_type or ""
    if not content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="file must be a video/* upload")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="upload exceeds size limit")

    video_id = uuid.uuid4().hex
    original_filename = file.filename or "video"
    key = input_key(video_id, safe_filename(original_filename))

    # --- stream to S3 Input (managed multipart; cap enforced mid-stream) ---
    try:
        s3.upload_fileobj(
            _LimitedReader(file.file, MAX_UPLOAD_BYTES),
            INPUT_BUCKET,
            key,
            ExtraArgs={
                "Metadata": {"video-id": video_id},
                "ContentType": content_type,
            },
        )
    except UploadTooLarge:
        LOG.info("upload aborted over size cap (video_id=%s)", video_id)
        raise HTTPException(status_code=400, detail="upload exceeds size limit") from None
    except ClientError as exc:
        LOG.error("S3 upload failed (video_id=%s, code=%s)", video_id,
                  _client_error_code(exc))
        raise HTTPException(status_code=502, detail="upload failed") from exc

    # --- write the Queued catalog row (update_item, never put_item) ---
    created_at = datetime.now(UTC).isoformat()
    try:
        ddb.update_item(
            TableName=TABLE_NAME,
            Key={"video_id": {"S": video_id}},
            UpdateExpression=(
                "SET #s = :s, gsi_pk = :g, created_at = :c, "
                "title = :t, original_filename = :o"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": {"S": "Queued"},
                ":g": {"S": GSI_PK},
                ":c": {"S": created_at},
                ":t": {"S": title},
                ":o": {"S": original_filename},
            },
        )
    except ClientError as exc:
        # Compensating cleanup: delete the just-uploaded orphan, best effort.
        LOG.error("update_item failed (video_id=%s, key=%s, code=%s); compensating",
                  video_id, key, _client_error_code(exc))
        try:
            s3.delete_object(Bucket=INPUT_BUCKET, Key=key)
        except ClientError:
            LOG.exception("compensating delete failed (video_id=%s, key=%s)", video_id, key)
        raise HTTPException(status_code=502, detail="failed to record video") from exc

    return {"video_id": video_id, "status": "Queued"}


@app.get("/videos")
def list_videos() -> dict:
    try:
        resp = ddb.query(
            TableName=TABLE_NAME,
            IndexName=GSI_NAME,
            KeyConditionExpression="gsi_pk = :pk",
            ExpressionAttributeValues={":pk": {"S": GSI_PK}},
            ScanIndexForward=False,
            Limit=100,
        )
    except ClientError as exc:
        code = _client_error_code(exc)
        if code == "ResourceNotFoundException":
            LOG.error("table/index missing on list: %s", code)
            raise HTTPException(status_code=500, detail="catalog unavailable") from exc
        LOG.error("list query failed (code=%s)", code)
        raise HTTPException(status_code=502, detail="list failed") from exc
    return {"videos": [deserialize_item(i) for i in resp.get("Items", [])]}


def _get_video_item(video_id: str) -> dict:
    """Fetch a catalog row; map absent -> 404, missing table -> 500, else 502."""
    try:
        resp = ddb.get_item(
            TableName=TABLE_NAME, Key={"video_id": {"S": video_id}}
        )
    except ClientError as exc:
        code = _client_error_code(exc)
        if code == "ResourceNotFoundException":
            LOG.error("table missing on get (video_id=%s)", video_id)
            raise HTTPException(status_code=500, detail="catalog unavailable") from exc
        LOG.error("get_item failed (video_id=%s, code=%s)", video_id, code)
        raise HTTPException(status_code=502, detail="lookup failed") from exc
    if "Item" not in resp:
        LOG.info("video not found (video_id=%s)", video_id)
        raise HTTPException(status_code=404, detail="video not found")
    return deserialize_item(resp["Item"])


def _validate_video_id(video_id: str) -> None:
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(status_code=400, detail="invalid video_id")


@app.get("/videos/{video_id}")
def get_video(video_id: str) -> dict:
    _validate_video_id(video_id)
    return _get_video_item(video_id)


@app.get("/videos/{video_id}/play-url")
def play_url(video_id: str, request: Request, response: Response) -> dict:
    _validate_video_id(video_id)
    item = _get_video_item(video_id)
    status = item.get("status")
    if status != "Ready":
        raise HTTPException(status_code=409, detail={"status": status})
    if not signer.loaded:
        raise HTTPException(status_code=503, detail="signing key unavailable")

    playlist_url = f"https://{CF_DOMAIN}/media/{video_id}/playlist.m3u8"
    if PLAYBACK_MODE == "signed-url":
        # Local dev: the browser can't attach a CloudFront-domain cookie, so
        # point at THIS API's rewritten-playlist endpoint (its segment lines are
        # absolute CloudFront signed URLs). Return a URL to that endpoint.
        local_url = str(request.url_for("local_playlist", video_id=video_id))
        return {"play_url": local_url, "mode": "signed-url"}

    # Production: set the three signed cookies scoped to /media/{video_id}/*.
    resource = f"https://{CF_DOMAIN}/media/{video_id}/*"
    cookies = signer.sign_cookies(resource, PLAYBACK_TTL_SECONDS)
    cookie_path = f"/media/{video_id}/"
    for name, value in cookies.items():
        response.set_cookie(
            key=name,
            value=value,
            max_age=PLAYBACK_TTL_SECONDS,
            path=cookie_path,
            secure=True,
            httponly=True,
            samesite="none",
        )
    return {"play_url": playlist_url, "mode": "cookie"}


@app.get("/videos/{video_id}/playlist.m3u8")
def local_playlist(video_id: str) -> Response:
    """Local-dev-only: fetch the HLS playlist and rewrite segments to signed URLs."""
    _validate_video_id(video_id)
    if PLAYBACK_MODE != "signed-url":
        raise HTTPException(status_code=404, detail="not found")
    if not signer.loaded:
        raise HTTPException(status_code=503, detail="signing key unavailable")

    media_base = f"https://{CF_DOMAIN}/media/{video_id}"
    playlist_url = f"{media_base}/playlist.m3u8"
    signed_playlist_url = signer.sign_url(playlist_url, PLAYBACK_TTL_SECONDS)
    try:
        import urllib.request

        with urllib.request.urlopen(signed_playlist_url, timeout=10) as handle:
            playlist_text = handle.read().decode("utf-8")
    except OSError as exc:
        LOG.error("failed to fetch playlist (video_id=%s)", video_id)
        raise HTTPException(status_code=502, detail="playlist fetch failed") from exc

    rewritten = signing.rewrite_playlist(
        playlist_text, media_base, signer, PLAYBACK_TTL_SECONDS
    )
    return PlainTextResponse(rewritten, media_type="application/vnd.apple.mpegurl")


@app.delete("/videos/{video_id}")
def delete_video(video_id: str) -> dict:
    _validate_video_id(video_id)
    try:
        ddb.delete_item(TableName=TABLE_NAME, Key={"video_id": {"S": video_id}})
    except ClientError as exc:
        LOG.error("delete_item failed (video_id=%s, code=%s)", video_id,
                  _client_error_code(exc))
        raise HTTPException(status_code=502, detail="delete failed") from exc

    _delete_prefix(INPUT_BUCKET, f"input/{video_id}/")
    _delete_prefix(OUTPUT_BUCKET, f"output/{video_id}/")
    return {"deleted": video_id}


def _delete_prefix(bucket: str, prefix: str) -> None:
    """ListObjectsV2 + DeleteObjects over a per-video prefix (best effort)."""
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objects:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
    except ClientError:
        LOG.exception("prefix cleanup failed (bucket=%s, prefix=%s)", bucket, prefix)
