# Video Streaming — web tier (FastAPI)

The JSON API that the SPA calls. It owns upload (`POST /videos`), listing
(`GET /videos`), status (`GET /videos/{video_id}`), playback credentials
(`GET /videos/{video_id}/play-url`), and delete (`DELETE /videos/{video_id}`),
plus `GET /health` for the ALB target group. It never serves HTML — the SPA is
a separate static bundle (FEAT-004) fronted by the same CloudFront domain.

See `../DESIGN.md` sections **FastAPI web tier**, **CloudFront + signed-cookie
playback**, and **Local-dev approach** for the authoritative behavior.

## Environment

All resource names come from env so the local and deployed runs use the same
code path. In AWS the launch template (FEAT-005) writes these to
`/etc/video-web.env`; locally export them in your shell.

| Var | Meaning |
|---|---|
| `INPUT_BUCKET` | raw-upload bucket (`video-input-678602035067-us-east-1`) |
| `OUTPUT_BUCKET` | HLS output bucket (`video-output-678602035067-us-east-1`) |
| `TABLE_NAME` | DynamoDB catalog (`VideoCatalog`) |
| `ARTIFACT_BUCKET` | FFmpeg artifact bucket (optional for the web tier) |
| `CF_KEY_SECRET_ARN` | Secrets Manager ARN of the CloudFront **private** signing key |
| `CF_DOMAIN` | the single CloudFront distribution domain |
| `CF_KEY_PAIR_ID` | the CloudFront **public key** id — used verbatim for the `CloudFront-Key-Pair-Id` field (NOT the key-group id) |
| `MAX_UPLOAD_BYTES` | upload cap, default `2147483648` (2 GiB) |
| `PLAYBACK_MODE` | `cookie` (prod, default) or `signed-url` (local dev) |
| `AWS_REGION` | default `us-east-1` |
| `CF_SIGNING_KEY_FILE` | **local dev only** — read the private PEM from this path instead of Secrets Manager. Never set in AWS. |

## Local development

The app runs against the **deployed** backend resources using your own AWS
credentials (`~/.aws`) — no MinIO/DynamoDB-local. Bind loopback only (never
`0.0.0.0`) for local dev:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export INPUT_BUCKET=video-input-678602035067-us-east-1 \
       OUTPUT_BUCKET=video-output-678602035067-us-east-1 \
       TABLE_NAME=VideoCatalog \
       CF_KEY_SECRET_ARN=arn:aws:secretsmanager:us-east-1:678602035067:secret:video/cf-signing-key \
       CF_DOMAIN=dXXXX.cloudfront.net \
       CF_KEY_PAIR_ID=K2XXXXXXXXXXXX \
       PLAYBACK_MODE=signed-url
uvicorn main:app --host 127.0.0.1 --port 8000
```

In local mode (`PLAYBACK_MODE=signed-url`), `play-url` returns a URL to this
API's own rewritten-playlist endpoint (`GET /videos/{video_id}/playlist.m3u8`),
whose segment lines are absolute CloudFront **signed URLs** — a browser on
`127.0.0.1` cannot attach a CloudFront-domain cookie, so cookies are not used
locally. Production (`PLAYBACK_MODE=cookie`) sets the three CloudFront signed
cookies scoped to `/media/{video_id}/*` and returns the playlist URL directly.

## Deploy-time behavior (signing key)

The web process reads the private PEM from Secrets Manager **once at startup**
and caches the parsed RSA key (12h TTL refresh). `GET /health` returns **503**
until the key is loaded, so the ALB never routes a playback request the tier
cannot sign. Deploy order therefore is:

1. `cdk deploy` (the `video/cf-signing-key` secret is created empty).
2. `aws secretsmanager put-secret-value --secret-id video/cf-signing-key \
   --secret-string file://cf_private.pem` (one-time, out of band).
3. The web ASG's initially-unhealthy instances turn healthy once the secret is
   present (or are replaced), then serve playback.

## Tests

```bash
pip install -r requirements.txt pytest ruff
pytest tests && ruff check .
```
