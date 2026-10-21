# video-streaming-app — IaC (CDK, Python)

AWS CDK app for the hardened video-streaming platform. Three stacks
(`VideoNetworkStack`, `VideoDataStack`, `VideoAppStack`) deploy to account
`678602035067` / `us-east-1`. Account/region are pinned in `app.py` so `cdk
synth` is credential-free and resource names/CIDRs are deterministic.

> `VideoAppStack` lands in FEAT-005; `app.py` guards its import so the two
> implemented stacks synth today.

## Setup & synth (clean venv)

```bash
cd projects/video-streaming-app/iac
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
bash scripts/fetch-ffmpeg.sh            # REQUIRED before synth (see below)
npx cdk synth VideoNetworkStack VideoDataStack
```

### Why `fetch-ffmpeg.sh` must run first

The `DataStack` deploys a pinned static FFmpeg build to the artifact bucket via a
`BucketDeployment` whose asset is `assets/ffmpeg/bin/`. That directory is
**gitignored** — the binaries are regenerated deterministically from
`assets/ffmpeg/FFMPEG.lock` (pinned release tag, asset name, and SHA256), not
vendored. `scripts/fetch-ffmpeg.sh` downloads the pinned tarball, verifies its
SHA256 (fails hard on mismatch), and extracts `ffmpeg` + `ffprobe` into `bin/`.
Synth fails by design if `bin/` is empty, so a missing prebuild can't ship a
worker with no FFmpeg. The fetch needs network egress to the pinned GitHub
release.

To re-pin, update `TAG`/`ASSET`/`SHA256` in `FFMPEG.lock` together and re-run the
script.

## Lint & test

```bash
ruff check .
pytest tests
```

## CloudFront signing-key pair

Playback is gated by CloudFront signed credentials. The RSA-2048 key pair is
generated **once, out of band** — never by CDK, and the private key is never
committed:

```bash
openssl genrsa -out cf_private.pem 2048
openssl rsa -pubout -in cf_private.pem -out cf_public.pem
```

- **Public** PEM: committed as [`keys/cf_public.pem`](keys/cf_public.pem) and
  passed to `cloudfront.PublicKey(encoded_key=...)` in `VideoAppStack`
  (FEAT-005). A public key is not sensitive.
- **Private** PEM: loaded into the `video/cf-signing-key` Secrets Manager secret
  (created empty by `DataStack`) **out of band** after deploy:
  ```bash
  aws secretsmanager put-secret-value \
    --secret-id video/cf-signing-key \
    --secret-string file://cf_private.pem
  ```
  It never lives in source, the AMI, or the SPA. The web tier reads it once at
  startup. Keep `cf_private.pem` out of the repo.

## Teardown

Every stateful resource sets `removal_policy=DESTROY` (buckets also
`auto_delete_objects=True`); `cdk destroy` in reverse stack order removes
everything. No `cdk deploy`/`cdk destroy` is run in this workflow.
