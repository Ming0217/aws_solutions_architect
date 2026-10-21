# video-streaming-app — IaC (CDK, Python)

AWS CDK app for the hardened video-streaming platform. Three stacks deploy to
account `678602035067` / `us-east-1`:

| Stack | Contents |
|---|---|
| `VideoNetworkStack` | VPC, subnets, NAT, VPC endpoints, security groups |
| `VideoDataStack` | S3 buckets, DynamoDB (`VideoCatalog`), SQS (`VideoQueue` + `VideoQueue-DLQ`), empty `video/cf-signing-key` secret |
| `VideoAppStack` | ALB, web + worker ASGs, CloudFront distribution, DLQ-marker Lambda, CfnOutputs |

Account/region are pinned in `app.py` so `cdk synth` is credential-free and
resource names/CIDRs are deterministic.

> **No `cdk deploy` or `cdk destroy` is run in this workflow.** The deploy and
> teardown commands below are the operator runbook; this workflow's deliverable
> is a deploy-ready, locally-runnable app verified only by `cdk synth`.

## Setup & synth (clean venv)

```bash
cd projects/video-streaming-app/iac
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
bash scripts/fetch-ffmpeg.sh            # REQUIRED before synth (see below)
npx cdk synth                           # all three stacks
```

### Why `fetch-ffmpeg.sh` must run first

`VideoDataStack` deploys a pinned static FFmpeg build to the artifact bucket via
a `BucketDeployment` whose asset is `assets/ffmpeg/bin/`. That directory is
**gitignored** — the binaries are regenerated deterministically from
`assets/ffmpeg/FFMPEG.lock` (pinned release tag, asset name, and SHA256), not
vendored. `scripts/fetch-ffmpeg.sh` downloads the pinned tarball, verifies its
SHA256 (fails hard on mismatch), and extracts `ffmpeg` + `ffprobe` into `bin/`.
Synth fails by design if `bin/` is empty, so a missing prebuild can't ship a
worker with no FFmpeg. The fetch needs network egress to the pinned GitHub
release.

To re-pin, update `TAG`/`ASSET`/`SHA256` in `FFMPEG.lock` together and re-run
the script.

## Lint & test

```bash
ruff check .
pytest tests
```

---

# DEPLOY runbook (operator)

Follow the steps in order. Prerequisites: AWS credentials for
`678602035067` / `us-east-1`, Python 3.12, Node (for `npx cdk`), and `openssl`.

## 1. Generate the CloudFront signing key pair (once, out of band)

Playback is gated by CloudFront signed credentials. The RSA-2048 key pair is
generated **once, out of band** — never by CDK, and the private key is never
committed:

```bash
openssl genrsa -out cf_private.pem 2048
openssl rsa -pubout -in cf_private.pem -out cf_public.pem
```

- **Public** PEM: committed as [`keys/cf_public.pem`](keys/cf_public.pem) and
  passed to `cloudfront.PublicKey(encoded_key=...)` in `VideoAppStack`. A public
  key is not sensitive. (Replace `keys/cf_public.pem` only if you regenerate the
  pair.)
- **Private** PEM: loaded into Secrets Manager out of band in step 4. Keep
  `cf_private.pem` out of the repo.

## 2. Bootstrap the environment (once per account/region)

```bash
npx cdk bootstrap aws://678602035067/us-east-1
```

## 3. Fetch FFmpeg, then deploy

```bash
bash scripts/fetch-ffmpeg.sh            # populate assets/ffmpeg/bin/ first
npx cdk deploy --all                    # deploys Network -> Data -> App in dependency order
```

Record the `VideoAppStack` outputs (used by `LOCAL_DEV.md` and step 4):

```bash
aws cloudformation describe-stacks --stack-name VideoAppStack \
  --query 'Stacks[0].Outputs' --output table
```

Key outputs: `InputBucketName`, `OutputBucketName`, `SiteBucketName`,
`ArtifactBucketName`, `TableName`, `QueueUrl`, `DlqUrl`, `AlbDnsName`,
`CloudFrontDomain`, `CfKeyGroupId`, `CfPublicKeyId`, `CfKeySecretArn`.

## 4. Load the signing key out of band — DEPLOY ORDER MATTERS

The web tier reads the private PEM from the `video/cf-signing-key` secret
**once at startup** and fails `GET /health` with **503** until it is present,
so the ALB never routes a playback request the tier cannot sign. The secret is
created **empty** by `VideoDataStack`, so immediately after `cdk deploy` the web
ASG instances are initially unhealthy. Load the key:

```bash
aws secretsmanager put-secret-value \
  --secret-id video/cf-signing-key \
  --secret-string file://cf_private.pem
```

Deploy order, therefore:

1. `cdk deploy --all` (the secret exists but is empty; web instances report
   unhealthy).
2. `aws secretsmanager put-secret-value ...` (one-time, out of band).
3. The web ASG's initially-unhealthy instances turn healthy once the secret is
   present (or the ASG replaces them), then serve playback.

## 5. Test

Use `../LOCAL_DEV.md` to run the SPA + FastAPI locally against the now-deployed
backend (signed-URL playback mode). For an end-to-end AWS check, browse to the
`CloudFrontDomain` output and exercise upload → status → playback.

## 6. Validate

- `GET https://<CloudFrontDomain>/health` (via the ALB behind CloudFront)
  returns 200 once the signing key is loaded.
- Upload a clip; confirm an `input/<video_id>/...` object, a `VideoCatalog` row
  that advances to `Ready`, and an `output/<video_id>/...` HLS set.
- Playback streams the HLS segments from CloudFront.

---

# Teardown + verify-nothing-lingers

```bash
npx cdk destroy VideoAppStack VideoDataStack VideoNetworkStack   # reverse stack order
```

Every stateful resource sets `removal_policy=DESTROY` and every bucket sets
`auto_delete_objects=True`, so `cdk destroy` removes data stores too. The
`video/cf-signing-key` secret is deleted with the stack (no recovery window).

After `destroy` completes, confirm nothing lingers:

- [ ] CloudFormation: `VideoAppStack`, `VideoDataStack`, `VideoNetworkStack` all
      gone — `aws cloudformation list-stacks --query "StackSummaries[?starts_with(StackName,'Video')]"` shows only `DELETE_COMPLETE`.
- [ ] No leftover `video-*` S3 buckets — `aws s3 ls | grep video-` returns
      nothing (expect `video-input-`, `video-output-`, `video-site-`,
      `video-artifacts-…678602035067-us-east-1` all gone).
- [ ] DynamoDB `VideoCatalog` table gone — `aws dynamodb list-tables`.
- [ ] SQS `VideoQueue` and `VideoQueue-DLQ` gone — `aws sqs list-queues`.
- [ ] Secrets Manager `video/cf-signing-key` gone —
      `aws secretsmanager list-secrets`.
- [ ] CloudWatch log groups `/video/web`, `/video/worker`, `/video/dlq-marker`
      gone — `aws logs describe-log-groups --log-group-name-prefix /video/`.
- [ ] CloudFront distribution removed — `aws cloudfront list-distributions`.
- [ ] Both ASGs (web + worker) at 0 / removed, no lingering EC2 instances —
      `aws autoscaling describe-auto-scaling-groups`.

Delete the local `cf_private.pem` once teardown is confirmed (it never belonged
in the repo).
