# Implementation Plan — Video Streaming Platform, hardened (Phase 2) IaC build

Source of truth: `projects/video-streaming-app/DESIGN.md` (approved, 4 review rounds) and
`projects/video-streaming-app.md` (spec). All paths below are **relative to the worktree root**
`/Users/mingxmh/Desktop/Desktop/team_goals/sa_training/aws_solutions_architect/.worktrees/video-streaming-hardening/`.
Work only inside that worktree. **No `cdk deploy`/`cdk destroy` runs in this workflow** — the
deliverable is deploy-ready and locally runnable only.

Account/region are fixed: **678602035067 / us-east-1**. CDK is **Python**, `aws-cdk-lib ^2.170.0`.
Reference CDK (`projects/clear-thinking-app/iac/`) is TypeScript — mirror its *structure* only and
translate every API to the Python binding (`aws_cdk` imports, snake_case props,
`s3deploy.Source.json_data(...)`).

## MUST-FIX carry-forwards (open items from `.agents/tasks/design-review.json`)

These were approved in direction but not yet written into DESIGN.md. They are mandatory and the
reviewer must verify them:

- **[HIGH] CloudFront signer needs the PUBLIC KEY id, not the key-group id.** Add a CfnOutput
  `CfPublicKeyId = public_key.public_key_id` and inject `CF_KEY_PAIR_ID` into the web tier
  (launch-template EnvironmentFile + local env list). The signer uses it for the
  `CloudFront-Key-Pair-Id` field. Keep `CfKeyGroupId` only for the trusted-key-group reference.
- **[MED] Local-dev media CORS.** HLS segments are fetched from CloudFront cross-origin during
  local UI testing. Add a CloudFront `ResponseHeadersPolicy` CORS on the `/media/*` behavior (plus
  S3 CORS on the Output bucket) allowing the localhost dev origins. Production is same-origin and
  needs none.
- **[MED] Web-tier signing-key startup ordering/recovery.** Fetch the private PEM from Secrets
  Manager at boot; either lazy-with-retry (start healthy, fetch on first `play-url`) **or** fail
  the health check until the secret is present, and document the deploy order
  (deploy → `put-secret-value` → ASG replaces initial unhealthy instances). Chosen approach:
  **fail-the-health-check + documented deploy order** (matches DESIGN's lifespan read).
- **[MED] CloudFront VPC-origin → internal ALB SG ingress is an unverified assumption.** At
  implementation time verify against current AWS CloudFront VPC-origins docs how the managed ENIs
  source traffic, confirm `cloudfront.VpcOrigin` exists in `aws-cdk-lib ^2.170.0`, pin the ALB and
  the VPC-origin to the **same explicit private-subnet set**, and wire a concrete SG rule
  (private-subnet-CIDR ingress on TCP 80). Confirm it on `cdk synth`.
- **[MED] Production playback = CloudFront signed COOKIES** — CONFIRMED by orchestrator + user; do
  not re-open. Treat the "signed URLs" wording in the settled decision as satisfied by cookies.
  Local dev uses signed URLs (rewritten playlist).
- **[NIT] gp3 EBS sizing** on both launch templates sized to `MAX_UPLOAD_BYTES` (2 GB) + headroom.
- **[NIT] Local playlist delivery:** local `play-url` returns a URL to the local API's
  rewritten-playlist endpoint whose segment lines are absolute CloudFront signed URLs.
- **[NIT] Env injection:** launch-template user-data writes a systemd `EnvironmentFile` from
  CDK-resolved references so deployed and local paths read identical env var names.

## Build/verify tooling (discovered)

- IaC: Python 3.12 CDK app under `projects/video-streaming-app/iac/`, its own venv +
  `requirements.txt` (`aws-cdk-lib>=2.170.0,<3`, `constructs>=10`). CDK CLI via `npx cdk` (no global
  install needed). `cdk.json` app command `python3 app.py`. **`cdk synth` needs no AWS credentials**
  — define the VPC in-stack (no `from_lookup`), set explicit `env=Environment(account, region)`.
- FFmpeg: `iac/scripts/fetch-ffmpeg.sh` must run **before** `cdk synth` (the ffmpeg
  `BucketDeployment` asset dir must be non-empty or synth fails by design).
- Python checks: `ruff check` (lint/imports), `python -m compileall` (import/syntax), `pytest`
  (unit, boto3 stubbed with `botocore.stub.Stubber`), optional `mypy` best-effort. FastAPI smoke:
  `fastapi.testclient.TestClient` hitting `/health`, plus a real `uvicorn` boot check.

---

# Ordered items

- [ ] 1. **Scaffold the CDK Python app + NetworkStack + DataStack + FFmpeg pin + CF key material + Python tooling.**
      Create `iac/` as a CDK Python app: `app.py` (instantiates NetworkStack, DataStack, AppStack with
      explicit `env=Environment(account="678602035067", region="us-east-1")`), `cdk.json`
      (`"app": "python3 app.py"`), `requirements.txt`, `requirements-dev.txt` (pytest, ruff, mypy),
      `.gitignore` (`cdk.out/`, `assets/ffmpeg/bin/`, `frontend/config.json`). Implement
      `iac/stacks/network_stack.py` (VPC 10.0.0.0/16, 2 AZs, public subnets for a single NAT,
      `PRIVATE_WITH_EGRESS` subnets; S3+DynamoDB gateway endpoints; SQS, Secrets Manager, ssm,
      ssmmessages, ec2messages interface endpoints; `alb-sg`/`web-sg`/`worker-sg` with the DESIGN
      ingress rules and NO port-22 anywhere) and `iac/stacks/data_stack.py` (4 buckets with fixed
      `-678602035067-us-east-1` names, Block Public Access ALL, `removalPolicy=DESTROY`,
      `auto_delete_objects=True`, Input lifecycle IA@30d/Glacier@90d + 7d incomplete-MPU,
      Output 7d incomplete-MPU; `VideoCatalog` table PK `video_id` + GSI `by-status-created`
      (`gsi_pk`/`created_at`, projection ALL), PAY_PER_REQUEST, DESTROY; `VideoQueue` visibility 900s,
      long-poll 20s; `VideoQueue-DLQ` maxReceiveCount=3, 14d retention; ffmpeg `BucketDeployment`
      into the artifacts bucket with `memory_limit=1024`, `ephemeral_storage_size=Size.gibibytes(2)`;
      `video/cf-signing-key` empty Secrets Manager secret DESTROY). Add `iac/scripts/fetch-ffmpeg.sh`
      (curl the pinned `BtbN/FFmpeg-Builds` tag, verify SHA256 against `assets/ffmpeg/FFMPEG.lock`,
      extract `ffmpeg`+`ffprobe` into `assets/ffmpeg/bin/`, fail on empty), `assets/ffmpeg/FFMPEG.lock`,
      and `iac/keys/cf_public.pem` (committed public RSA key; document out-of-band generation).
      Files: `iac/app.py`, `iac/cdk.json`, `iac/requirements.txt`, `iac/requirements-dev.txt`,
      `iac/.gitignore`, `iac/stacks/__init__.py`, `iac/stacks/network_stack.py`,
      `iac/stacks/data_stack.py`, `iac/scripts/fetch-ffmpeg.sh`, `iac/assets/ffmpeg/FFMPEG.lock`,
      `iac/keys/cf_public.pem`, `iac/tests/test_network_data.py`.
      Verify: `cd iac && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt && bash scripts/fetch-ffmpeg.sh && npx cdk synth VideoNetworkStack VideoDataStack` succeeds; `ruff check .` and `pytest tests` pass.

- [ ] 2. **Implement the FFmpeg worker.**
      `worker/worker.py`: SQS long-poll loop (`WaitTimeSeconds=20`); control-message guard (drop +
      delete bodies that are non-JSON, `s3:TestEvent`, or lack a `Records[0].s3.object.key` matching
      `input/<video_id>/…`); parse `video_id` from the key prefix only; idempotency `get_item` skip
      when already `Ready`; download raw → run the exact downscale argv
      (`scale=-2:720`, `-c:v libx264 -profile:v baseline -level 3.1 -c:a aac -f hls -hls_time 6
      -hls_playlist_type vod`) → upload HLS to `output/{video_id}/` → `update_item` Processing→Ready →
      `delete_message`. Non-zero FFmpeg exit = deterministic rejection → `update_item status=Failed` +
      delete (no retry); transient boto3/OS errors (download, ENOSPC, DynamoDB `ClientError`) are
      raised/left for redelivery. SIGTERM handler completes/aborts the job then
      `CompleteLifecycleAction`, with periodic `RecordLifecycleActionHeartbeat`. Add
      `worker/user-data.sh` (pull ffmpeg/ffprobe from the artifacts bucket to `/usr/local/bin`, write a
      systemd `EnvironmentFile` from instance env, install the unit) and `worker/video-worker.service`
      (`User=appuser`, logs to `/video/worker`). Unit tests: key→video_id extraction, idempotency skip,
      argv assembly, Failed-on-nonzero-exit, control-message drop.
      Files: `worker/worker.py`, `worker/requirements.txt`, `worker/user-data.sh`,
      `worker/video-worker.service`, `worker/tests/test_worker.py`.
      Verify: `cd worker && pip install -r requirements.txt pytest ruff && pytest tests && ruff check . && python -m compileall worker.py` all pass.

- [ ] 3. **Implement the FastAPI web tier + local config.**
      `api/main.py`: routes `POST /videos` (uuid4 hex id; sanitize `original_filename`;
      `s3.upload_fileobj` streaming to `input/{video_id}/{safe_filename}` with
      `ExtraArgs Metadata video-id` + ContentType; size cap enforced on Content-Length and mid-stream;
      `update_item` Queued + `gsi_pk="VIDEO"` + `created_at`; compensating `delete_object` if the
      catalog write fails → 502), `GET /videos` (GSI Query, newest-first, no scan),
      `GET /videos/{video_id}` (`get_item`; absent `"Item"` → 404; `ResourceNotFoundException` → 500),
      `GET /videos/{video_id}/play-url` (if Ready: production returns playlist URL + sets 3 CloudFront
      signed cookies scoped to `/media/{video_id}/*`, 6h; local mode returns a URL to the local
      rewritten-playlist endpoint whose segment lines are absolute CloudFront signed URLs; else 409 +
      status), `DELETE /videos/{video_id}`, `GET /health`. `api/signing.py`: load the private PEM from
      Secrets Manager **once at startup** (lifespan), parse to `RSAPrivateKey`, 12h TTL refresh;
      startup-read failure fails `/health`; use `CF_KEY_PAIR_ID` for the key-pair id; per-resource
      policy + TTL identical for cookie and URL signing. Per-operation exception handling (the DESIGN
      table); no bare except; CORS allowing the CloudFront origin + the two localhost dev origins with
      `allow_credentials=True`. Reads env `INPUT_BUCKET`, `OUTPUT_BUCKET`, `TABLE_NAME`,
      `ARTIFACT_BUCKET`, `CF_KEY_SECRET_ARN`, `CF_DOMAIN`, `CF_KEY_PAIR_ID`, `MAX_UPLOAD_BYTES`. Ship
      `api/user-data.sh` + `api/video-web.service` (gunicorn+uvicorn workers, port 8000, `User=appuser`,
      EnvironmentFile, logs to `/video/web`). Unit tests with `Stubber`: id/key/metadata, GSI Query
      builder, signed cookie/URL (TTL + scoped path), exception mapping per ClientError code, input
      validation.
      Files: `api/main.py`, `api/signing.py`, `api/requirements.txt`, `api/user-data.sh`,
      `api/video-web.service`, `api/tests/test_api.py`, `api/tests/test_signing.py`.
      Verify: `cd api && pip install -r requirements.txt pytest ruff && pytest tests && ruff check . && python -c "import main"` pass; uvicorn boot smoke: start `uvicorn main:app --host 127.0.0.1 --port 8000` with stub env, `curl -f 127.0.0.1:8000/health`, stop.

- [ ] 4. **Build the vanilla SPA frontend.**
      `frontend/index.html`, `frontend/app.js` (ES modules; **always fetch `config.json`** at startup
      for `{apiBaseUrl, region, playbackMode}`; upload form → `POST /videos`; poll `GET /videos`;
      status badges incl. Failed; player view calls `play-url`), `frontend/player.js` (hls.js from CDN;
      on a segment 403 re-call `play-url` to refresh cookies; media is same-origin in production so no
      `withCredentials`), `frontend/styles.css`, and checked-in `frontend/config.local.json`
      (`apiBaseUrl: "http://127.0.0.1:8000"`, `playbackMode: "signed-url"`). `frontend/config.json` is
      gitignored (produced by `BucketDeployment` in AWS, or `cp config.local.json config.json` locally).
      Files: `frontend/index.html`, `frontend/app.js`, `frontend/player.js`, `frontend/styles.css`,
      `frontend/config.local.json`.
      Verify: serve with `python -m http.server --bind 127.0.0.1 5500` from `frontend/` after
      `cp config.local.json config.json`, load the page, confirm it fetches config.json and renders
      (manual, recorded in findings); `node --check app.js player.js` (syntax) passes.

- [ ] 5. **Implement the DLQ-marker Lambda + the full AppStack (integration glue).**
      `iac/lambda/dlq_marker/handler.py`: parse `video_id` from a DLQ body's S3 key; `update_item
      status=Failed` with `ConditionExpression="attribute_exists(video_id)"` (catch
      `ConditionalCheckFailedException` → log/drop); same control-message guard; then delete the DLQ
      message. `iac/stacks/app_stack.py`: two IAM instance roles (`video-web-role`, `video-worker-role`)
      with the DESIGN least-privilege policies (literal `input/*`/`output/*` prefixes; web gets
      `secretsmanager:GetSecretValue` on the key secret + `CF_KEY_PAIR_ID`; worker gets the two
      autoscaling lifecycle actions); web ASG (`t3.small`, min1/max2/desired1, CPU target-tracking 60%)
      + worker ASG (`c7i.large`, min0/max0→0 desired, step-scaling: `video-queue-backlog` 0→N band +
      `video-queue-idle` visible+not-visible=0 for 15×60s → 0) with launch templates that write a
      systemd EnvironmentFile from CDK-resolved refs and set **gp3 block devices** sized to 2 GB +
      headroom; worker ASG termination **LifecycleHook**; internal ALB + target groups + `/health`
      check; S3→SQS `add_event_notification(OBJECT_CREATED, SqsDestination, prefix="input/")`;
      CloudFront `PublicKey` (from `keys/cf_public.pem`) + `KeyGroup`; single distribution with
      `/media/*` (Output OAC, trusted key group, **ResponseHeadersPolicy CORS for localhost origins**),
      `/api/*` (**VPC origin** to the internal ALB, CACHING_DISABLED, forward all), default (site OAC);
      S3 CORS on Output for localhost; verify the VPC-origin↔ALB SG mechanism against current AWS docs
      and pin ALB + VPC-origin to the same private-subnet set; `BucketDeployment` of `frontend/` +
      generated `config.json` (`apiBaseUrl:"/api"`, `playbackMode:"cookie"`); explicit log groups
      `/video/web`, `/video/worker`, `/video/dlq-marker` (TWO_WEEKS, DESTROY); all CfnOutputs including
      **`CfPublicKeyId`** and `CfKeyGroupId`.
      Files: `iac/lambda/dlq_marker/handler.py`, `iac/lambda/dlq_marker/__init__.py`,
      `iac/stacks/app_stack.py`, `iac/tests/test_app_stack.py`,
      `iac/lambda/dlq_marker/tests/test_handler.py`.
      Verify: `cd iac && bash scripts/fetch-ffmpeg.sh && npx cdk synth` (all three stacks) succeeds;
      `ruff check .` and `pytest tests lambda/dlq_marker/tests` pass.

- [ ] 6. **Write the local-dev runbook + DEPLOY runbook + iac README.**
      `projects/video-streaming-app/LOCAL_DEV.md` (prereqs; `cp frontend/config.local.json
      frontend/config.json`; export the env vars pointing at deployed resources; run
      `uvicorn main:app --host 127.0.0.1 --port 8000`; serve the SPA on loopback :5500; exercise
      upload→status→playback locally via signed-URL mode), and `iac/README.md` DEPLOY runbook:
      out-of-band RSA keypair generation; `npx cdk bootstrap`; `bash scripts/fetch-ffmpeg.sh`;
      `npx cdk deploy` (deploy order → `aws secretsmanager put-secret-value` for the private PEM →
      ASG replaces initial unhealthy web instances); local test; validate; `npx cdk destroy` (reverse
      order); and a **verify-nothing-lingers** checklist (buckets, table, queues+DLQ, secret, log
      groups, distribution, ASGs). State clearly that no deploy/destroy is run in this workflow.
      Files: `projects/video-streaming-app/LOCAL_DEV.md`, `iac/README.md`.
      Verify: `npx cdk synth` still green; the runbook commands match the actual file/script/output
      names used in items 1–5 (cross-check by reading).

- [ ] 7. **Phase 2 VERIFY (cross-feature integration).**
      From a clean venv in `iac/`: `bash scripts/fetch-ffmpeg.sh && npx cdk synth` passes for all three
      stacks; `ruff check` + `python -m compileall` + `pytest` pass across `iac/`, `worker/`, `api/`,
      `iac/lambda/dlq_marker/`; FastAPI boots under `uvicorn` (health 200). Fix any seams between the
      components (env var names, bucket/table/queue references, asset paths, config.json shape).
      Verify: all the above commands pass with zero errors.

- [ ] 8. **Phase 3 docs.** Write `projects/video-streaming-app/walkthrough.md` (the hardened build
      narrative + how each hardening flag is closed), update `projects/video-streaming-app.md`
      (status, hardened section, cleanup checkbox context, confirmed signed-cookie decision), and the
      `projects/projects.md` index entry as needed.
      Files: `projects/video-streaming-app/walkthrough.md`, `projects/video-streaming-app.md`,
      `projects/projects.md`.
      Verify: links resolve; the project doc reflects the as-built hardened design; no `cdk deploy`
      claimed.

- [ ] 9. **Finalize.** Commit each package's changes on the `video-streaming-hardening` branch
      (separate logical commits, never push), rebase/clean up as the existing finalize step does, and
      leave the tree green (final `cdk synth` + all unit suites pass).
      Verify: `git status` clean; `npx cdk synth` and all `pytest` suites pass.

## Assumptions / gaps

- No AGENTS.md/CONTRIBUTING/.kiro steering exist in the repo; conventions are taken from the two
  reference apps (clear-thinking-app CDK teardown discipline, photoshare FastAPI/boto3 + local test
  patterns) and the DESIGN.
- Lint = `ruff`, tests = `pytest` with `botocore.stub.Stubber`, type = `mypy` best-effort — chosen
  because the repo pins none; they are the idiomatic Python-3.12 defaults and need no AWS account.
- `fetch-ffmpeg.sh` needs network to the pinned GitHub release at verify time; it is pinned +
  SHA256-checked. If the sandbox has no egress, record it as a retryable blocker rather than
  committing a vendored binary.
- Directory name `frontend/` (per the task) corresponds to the DESIGN's `spa/`.
