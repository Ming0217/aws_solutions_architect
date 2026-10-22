# Local development runbook

Run the SPA + FastAPI web tier **locally** against the **already-deployed**
backend (S3, DynamoDB, SQS, CloudFront, the signing-key secret). This is the
"test and verify locally before deploying" path: nothing here deploys or
destroys AWS resources. Everything binds loopback (`127.0.0.1`) only — never
`0.0.0.0`.

> Local playback uses CloudFront **signed URLs** (a rewritten playlist whose
> segment lines are absolute signed URLs), because a browser on `127.0.0.1`
> cannot carry a cookie scoped to the CloudFront domain. Production uses signed
> **cookies**. The mode is selected by `PLAYBACK_MODE` / `playbackMode`.

## Prerequisites

- Python 3.12.
- AWS credentials for the lab account (`678602035067` / `us-east-1`) in
  `~/.aws` — the local processes call S3/DynamoDB/Secrets Manager directly with
  your own credentials (no local S3/DynamoDB emulator).
- The backend is **already deployed** and the signing key has been loaded
  out of band (see `iac/README.md`, "Deploy order for the signing key").
- The CfnOutputs from `VideoAppStack` (used to fill the env vars below). Fetch
  them with:
  ```bash
  aws cloudformation describe-stacks --stack-name VideoAppStack \
    --query 'Stacks[0].Outputs' --output table
  ```

### Output → env var map

| CfnOutput (VideoAppStack) | Env var | Example value |
|---|---|---|
| `InputBucketName` | `INPUT_BUCKET` | `video-input-678602035067-us-east-1` |
| `OutputBucketName` | `OUTPUT_BUCKET` | `video-output-678602035067-us-east-1` |
| `ArtifactBucketName` | `ARTIFACT_BUCKET` | `video-artifacts-678602035067-us-east-1` |
| `TableName` | `TABLE_NAME` | `VideoCatalog` |
| `CfKeySecretArn` | `CF_KEY_SECRET_ARN` | `arn:aws:secretsmanager:us-east-1:678602035067:secret:video/cf-signing-key` |
| `CloudFrontDomain` | `CF_DOMAIN` | `dXXXX.cloudfront.net` |
| `CfPublicKeyId` | `CF_KEY_PAIR_ID` | `K2XXXXXXXXXXXX` (the **public key** id, not `CfKeyGroupId`) |

## 1. Configure the SPA

```bash
cd projects/video-streaming-app/frontend
cp config.local.json config.json        # gitignored; points the SPA at 127.0.0.1:8000, signed-url mode
```

`frontend/config.local.json` ships:

```json
{
  "apiBaseUrl": "http://127.0.0.1:8000",
  "playbackMode": "signed-url",
  "region": "us-east-1"
}
```

The SPA always `fetch`es `config.json` at startup (it never branches on
hostname), so this copy is what makes it talk to your local API.

## 2. Run the FastAPI web tier

```bash
cd projects/video-streaming-app/api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export INPUT_BUCKET=video-input-678602035067-us-east-1 \
       OUTPUT_BUCKET=video-output-678602035067-us-east-1 \
       ARTIFACT_BUCKET=video-artifacts-678602035067-us-east-1 \
       TABLE_NAME=VideoCatalog \
       CF_KEY_SECRET_ARN=arn:aws:secretsmanager:us-east-1:678602035067:secret:video/cf-signing-key \
       CF_DOMAIN=dXXXX.cloudfront.net \
       CF_KEY_PAIR_ID=K2XXXXXXXXXXXX \
       PLAYBACK_MODE=signed-url \
       AWS_REGION=us-east-1
uvicorn main:app --host 127.0.0.1 --port 8000
```

Confirm it is signing-ready (the signer loads the private PEM from Secrets
Manager at startup; `/health` is 503 until it is loaded):

```bash
curl -f http://127.0.0.1:8000/health
```

> **Offline alternative for the signing key:** set `CF_SIGNING_KEY_FILE` to a
> local private-PEM path to read the key from disk instead of Secrets Manager
> (local dev only — never set it in AWS). See `api/README.md`.

## 3. Serve the SPA

From a second shell, serve `frontend/` over loopback:

```bash
cd projects/video-streaming-app/frontend
python3 -m http.server --bind 127.0.0.1 5500
```

Open <http://127.0.0.1:5500/> in a browser.

## 4. Exercise upload → status → playback

1. **Upload** a video in the SPA (`POST /videos`). The web tier derives one
   `video_id` (`uuid4().hex`), writes the object under
   `input/<video_id>/...`, and creates the `VideoCatalog` row.
2. **Status** polls `GET /videos/{video_id}` until it reaches `Ready` (the
   deployed EC2 worker transcodes to `output/<video_id>/...`).
3. **Playback**: the SPA calls `GET /videos/{video_id}/play-url`. In
   `signed-url` mode this returns the local API's rewritten-playlist URL
   (`GET /videos/{video_id}/playlist.m3u8`) whose segment lines are absolute
   CloudFront **signed URLs**; the player streams the HLS segments from
   CloudFront over those signed URLs.

If segment fetches are blocked by CORS, confirm the `/media/*`
ResponseHeadersPolicy CORS + Output-bucket CORS allow your local origin (set in
`VideoAppStack`).

## Teardown

Nothing to tear down locally — stop `uvicorn` and `http.server` with Ctrl-C and
delete `frontend/config.json` if you like (it is gitignored). AWS teardown is a
separate operator action documented in `iac/README.md`.
