"""
Local end-to-end test (no AWS). Assumes the local harness is up:
  cd app && docker compose -f docker-compose.local.yml up --build -d

Flow exercised:
  1. GET /health                          (app + ALB target contract)
  2. POST /photos  -> uploads a PNG        (app -> MinIO + MySQL row)
  3. GET /photos   -> row present, status 'uploaded'
  4. run the Lambda handler on a synthetic S3 event
     (handler reads MinIO header -> parses dims -> POSTs /internal/metadata)
  5. GET /photos   -> status 'processed', width/height populated
  6. GET /photos/{id}/image -> streams the bytes back

Run inside the test venv (requests + boto3). MinIO + app are reached via
published host ports (9000 / 8080), so the handler runs on the host.
"""
import io
import os
import struct
import sys
import time

import requests

BASE = "http://localhost:8080"
EXPECT_W, EXPECT_H = 120, 80

# --- env for the Lambda handler (must be set BEFORE importing it) ---
os.environ["ALB_DNS"] = "localhost:8080"
os.environ["S3_ENDPOINT_URL"] = "http://localhost:9000"
os.environ["INTERNAL_API_KEY"] = "local-test-key"
os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadmin")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))
import handler  # noqa: E402


def make_png(width, height):
    """Minimal PNG: signature + IHDR (handler reads width/height at offset 16)."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)
    ihdr += b"\x08\x02\x00\x00\x00" + b"\x00\x00\x00\x00"  # bit depth/color + fake CRC
    return sig + ihdr


def wait_for_health(timeout=90):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{BASE}/health", timeout=3)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    if not wait_for_health():
        check("app health reachable", False, "app never became healthy on :8080")
        return finish()
    check("GET /health == 200", True)

    png = make_png(EXPECT_W, EXPECT_H)
    r = requests.post(
        f"{BASE}/photos",
        files={"file": ("test.png", png, "image/png")},
        data={"title": "local test"},
        timeout=10,
    )
    check("POST /photos == 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return finish()
    doc = r.json()
    photo_id, s3_key = doc["id"], doc["s3_key"]
    check("upload returned id + s3_key", bool(photo_id) and bool(s3_key), f"id={photo_id} key={s3_key}")

    r = requests.get(f"{BASE}/photos", timeout=10)
    row = next((p for p in r.json()["photos"] if p["id"] == photo_id), None)
    check("photo listed as 'uploaded'", row is not None and row["status"] == "uploaded",
          f"row={row}")

    # Synthetic S3 event -> run the Lambda handler (reads MinIO, posts callback)
    event = {"Records": [{"s3": {
        "bucket": {"name": "photoshare-local"},
        "object": {"key": s3_key, "size": len(png)},
    }}]}
    try:
        out = handler.handler(event, None)
        check("Lambda handler ran", True, str(out))
    except Exception as e:  # noqa: BLE001
        check("Lambda handler ran", False, repr(e))
        return finish()

    r = requests.get(f"{BASE}/photos", timeout=10)
    row = next((p for p in r.json()["photos"] if p["id"] == photo_id), None)
    check("photo now 'processed'", row is not None and row["status"] == "processed", f"row={row}")
    check("dimensions extracted (120x80)",
          row is not None and row["width"] == EXPECT_W and row["height"] == EXPECT_H,
          f"w={row and row.get('width')} h={row and row.get('height')}")

    r = requests.get(f"{BASE}/photos/{photo_id}/image", timeout=10)
    check("GET /photos/{id}/image == 200", r.status_code == 200,
          f"status={r.status_code} ctype={r.headers.get('content-type')}")

    return finish()


def finish():
    passed = sum(1 for _, c, _ in results if c)
    total = len(results)
    print(f"\n=== {passed}/{total} checks passed ===")
    sys.exit(0 if passed == total and total > 0 else 1)


if __name__ == "__main__":
    main()
