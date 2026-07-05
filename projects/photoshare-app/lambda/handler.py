"""
PhotoShare image-processing Lambda  (INFERRED / reverse-engineered).

NOTE: This is NOT the original workshop code (unavailable). It's reconstructed
from the architecture in the project doc:
  S3 ObjectCreated  ->  this Lambda  ->  extract metadata  ->  POST back through
  the ALB to the web app, which writes to RDS (Lambda stays out of the DB path).

Deliberately dependency-free: image dimensions are parsed from the file header
using only the standard library (no Pillow / no Lambda layer needed). If you
later want thumbnails, add Pillow via a layer or a container image — see README.

Env vars:
  ALB_DNS           - the ALB's public DNS name (callback target)
  INTERNAL_API_KEY  - shared secret; must match the app's INTERNAL_API_KEY
"""
import json
import os
import struct
import urllib.parse
import urllib.request

import boto3
from botocore.config import Config

ALB_DNS = os.environ["ALB_DNS"]
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "change-me")
# S3_ENDPOINT_URL is set only for local testing (MinIO); unset in real Lambda.
_S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")

if _S3_ENDPOINT_URL:
    s3 = boto3.client("s3", endpoint_url=_S3_ENDPOINT_URL,
                      config=Config(s3={"addressing_style": "path"}))
else:
    s3 = boto3.client("s3")

# Read only the first chunk of the object - image dimensions live in the header,
# so we never need to pull the whole file just to measure it.
HEADER_BYTES = 262144  # 256 KB


def get_image_size(data: bytes):
    """Return (width, height, format) from raw image header bytes, stdlib only."""
    # PNG: 8-byte signature, then IHDR with width/height at offset 16.
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return w, h, "png"
    # GIF: 'GIF87a'/'GIF89a', then little-endian width/height.
    if len(data) >= 10 and data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return w, h, "gif"
    # JPEG: scan segments for a Start-Of-Frame (SOFn) marker.
    if len(data) >= 2 and data[:2] == b"\xff\xd8":
        i, n = 2, len(data)
        sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                       0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in sof_markers:
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h, "jpeg"
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg_len
        return None, None, "jpeg"
    return None, None, None


def _callback(payload: dict):
    req = urllib.request.Request(
        f"http://{ALB_DNS}/internal/metadata",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 "X-Internal-Key": INTERNAL_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        print("callback status:", r.status, "payload:", payload)


def handler(event, context):
    processed = []
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        # S3 event keys are URL-encoded (spaces become '+').
        key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
        size = rec["s3"]["object"].get("size")

        obj = s3.get_object(Bucket=bucket, Key=key,
                            Range=f"bytes=0-{HEADER_BYTES - 1}")
        data = obj["Body"].read()
        width, height, fmt = get_image_size(data)

        payload = {
            "s3_key": key,
            "size_bytes": size,
            "width": width,
            "height": height,
            "image_format": fmt,
        }
        _callback(payload)
        processed.append(payload)

    # If _callback raises, the exception propagates -> Lambda retries -> DLQ.
    return {"processed": processed}
