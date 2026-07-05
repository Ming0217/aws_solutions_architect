"""
PhotoShare API — a minimal, self-built replacement for kodekloud/photosharing-app.

Contract it must honor (so it drops into the existing infra unchanged):
  - listens on port 8000
  - GET /health returns 200 (Docker healthcheck + ALB target group)
  - reads env: S3_BUCKET, AWS_SECRET_NAME, AWS_REGION, INTERNAL_API_KEY
  - stores images in S3, metadata in RDS MySQL (creds from Secrets Manager)
  - POST /internal/metadata is called back by the image-processing Lambda

Deliberately small and readable — tweak freely.
"""
import io
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

from db import get_conn, init_schema

S3_BUCKET = os.environ["S3_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "change-me")
# S3_ENDPOINT_URL is set only for local testing (points at MinIO). In AWS it's
# unset and boto3 talks to real S3.
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")


def _s3_client():
    kwargs = {"region_name": AWS_REGION}
    if S3_ENDPOINT_URL:
        # MinIO/local: custom endpoint + path-style addressing.
        kwargs["endpoint_url"] = S3_ENDPOINT_URL
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    return boto3.client("s3", **kwargs)


s3 = _s3_client()
app = FastAPI(title="PhotoShare API", version="0.1.0")


def _retry(fn, label, attempts=20, delay=3):
    for i in range(attempts):
        try:
            fn()
            return
        except Exception as e:  # noqa: BLE001
            print(f"[startup] {label} not ready ({i + 1}/{attempts}): {e}")
            time.sleep(delay)
    raise RuntimeError(f"[startup] {label} never became ready")


def _ensure_local_bucket():
    # Local testing only: auto-create the MinIO bucket. Never runs in AWS
    # (guarded by S3_ENDPOINT_URL), where the bucket is created by IaC.
    try:
        s3.create_bucket(Bucket=S3_BUCKET)
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    except Exception as e:  # noqa: BLE001
        if "BucketAlreadyOwnedByYou" not in str(e) and "BucketAlreadyExists" not in str(e):
            raise


@app.on_event("startup")
def _startup():
    if S3_ENDPOINT_URL:
        _retry(_ensure_local_bucket, "local bucket")
    # Create the photos table if it doesn't exist yet (idempotent).
    _retry(init_schema, "db schema")


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the single-page frontend."""
    with open(os.path.join(_STATIC_DIR, "index.html")) as f:
        return f.read()


@app.get("/health")
def health():
    # Shallow check — kept cheap so a brief DB blip doesn't flap the ALB target.
    return {"status": "ok"}


@app.get("/health/deep")
def health_deep():
    # Deeper check for manual debugging: confirms DB connectivity too.
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": "reachable"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}")


@app.post("/photos")
async def upload_photo(file: UploadFile = File(...), title: str = Form("")):
    """Upload an image: store bytes in S3, write a metadata row in MySQL."""
    ext = os.path.splitext(file.filename or "")[1].lower() or ".bin"
    key = f"uploads/{uuid.uuid4().hex}{ext}"
    body = await file.read()

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=body,
        ContentType=file.content_type or "application/octet-stream",
    )

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO photos (title, s3_key, content_type, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (title, key, file.content_type, "uploaded",
                 datetime.now(timezone.utc)),
            )
            photo_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # S3 ObjectCreated event now fires -> Lambda -> POST /internal/metadata.
    return {"id": photo_id, "s3_key": key, "title": title, "status": "uploaded"}


@app.get("/photos")
def list_photos():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, s3_key, content_type, size_bytes, width, "
                "height, image_format, status, created_at "
                "FROM photos ORDER BY id DESC LIMIT 100"
            )
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return {"photos": rows}
    finally:
        conn.close()


@app.get("/photos/{photo_id}/image")
def get_image(photo_id: int):
    """Stream the image THROUGH the app (bucket blocks public access by design)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT s3_key, content_type FROM photos WHERE id=%s",
                        (photo_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="photo not found")
    key, content_type = row
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
    return StreamingResponse(
        io.BytesIO(obj["Body"].read()),
        media_type=content_type or "application/octet-stream",
    )


@app.post("/internal/metadata")
def internal_metadata(payload: dict, x_internal_key: str = Header(default="")):
    """Called by the image-processing Lambda after an upload. Not public."""
    if x_internal_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="forbidden")

    key = payload.get("s3_key")
    if not key:
        raise HTTPException(status_code=400, detail="s3_key required")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE photos SET "
                "size_bytes   = COALESCE(%s, size_bytes), "
                "content_type = COALESCE(%s, content_type), "
                "width        = COALESCE(%s, width), "
                "height       = COALESCE(%s, height), "
                "image_format = COALESCE(%s, image_format), "
                "status       = 'processed' "
                "WHERE s3_key = %s",
                (payload.get("size_bytes"), payload.get("content_type"),
                 payload.get("width"), payload.get("height"),
                 payload.get("image_format"), key),
            )
        conn.commit()
    finally:
        conn.close()
    return {"status": "processed", "s3_key": key}
