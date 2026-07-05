# PhotoShare image-processing Lambda

> **Reverse-engineered / inferred** — this is *not* the original workshop code
> (unavailable). It's reconstructed from the architecture in
> [[projects/photoshare-app|the project doc]]: S3 upload → extract metadata →
> call back through the ALB so the web app writes to RDS.

## What it does

1. Triggered by `s3:ObjectCreated:*` on the image bucket.
2. Reads just the file **header** (first 256 KB via a ranged GET) from S3.
3. Extracts **width, height, format** with a **stdlib-only** parser (PNG/JPEG/GIF)
   — no Pillow, so no Lambda layer to package.
4. POSTs `{s3_key, size_bytes, width, height, image_format}` to the app's
   `POST /internal/metadata` through the ALB (guarded by `INTERNAL_API_KEY`).
5. On any error it raises → Lambda retries → unprocessed events land in the
   **dead-letter queue** (`photoshare-image-dlq`).

## Why call back through the app (not write RDS directly)?

Keeps the Lambda out of the VPC and out of the DB path → its role needs only S3
read + outbound HTTP, no Secrets Manager / RDS access. Least privilege by
architecture (see the project doc's Lambda section).

## Deploy options

**A. Inline in the template (already done, trimmed).** The Phase 2 template ships
a *minimal* inline version (size only) because CloudFormation inline `ZipFile` is
capped at 4096 chars. Good enough to smoke-test the wiring.

**B. This fuller version (recommended).** Package and point the function at it:

```bash
cd lambda
zip function.zip handler.py
# then either update the function directly:
aws lambda update-function-code \
  --function-name photoshare-image-processor \
  --zip-file fileb://function.zip
# (handler = handler.handler)
```

Or upload the zip to S3 and reference it from the template with `Code: { S3Bucket, S3Key }`.

## Env vars (set by the template)

| Var | Purpose |
| --- | --- |
| `ALB_DNS` | ALB public DNS — callback target |
| `INTERNAL_API_KEY` | shared secret; must equal the app's `INTERNAL_API_KEY` |

## Enhancement: thumbnails (needs Pillow)

Dimension parsing is stdlib. **Generating** thumbnails needs Pillow, which has
native deps — package it via a **Lambda layer** or a **container-image Lambda**
built for the Lambda platform. Then upload the thumbnail to `thumbnails/<key>`
and add a `thumb_key` to the callback payload + the `photos` table.
