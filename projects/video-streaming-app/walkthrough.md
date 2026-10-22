---
title: "Video Streaming Platform — Architecture Walkthrough (hardened)"
type: walkthrough
domain: architecting
date: 2026-10-20
status: iac-complete-local-runnable-not-deployed
okr: H2 2026 — KR4 (architecture walkthrough)
tags:
  - aws
  - walkthrough
  - architecting
---

# Video Streaming Platform — Architecture Walkthrough (hardened)

> Companion to the build doc [[projects/video-streaming-app|video-streaming-app]],
> the hardened design [`DESIGN.md`](./DESIGN.md), and the IaC in
> [`iac/`](./iac/README.md). One of the walkthroughs for **KR4**: explain design
> choices, tradeoffs, assumptions, and failure modes.
>
> **Status: hardened Phase 2 rebuilt as AWS CDK (Python) and runnable locally;
> NOT deployed in this workflow.** No `cdk deploy` or `cdk destroy` was run here —
> the stacks synthesize and the web tier + SPA run locally against env-injected
> resource names (see [`LOCAL_DEV.md`](./LOCAL_DEV.md)). Every claim below is read
> off the as-built code, not a live stack. The tutorial v1 (console build, verified
> live earlier) is the baseline; this walkthrough records how each v1 hardening
> flag is closed by the Phase 2 code.

## 1. Summary

The platform is an **event-driven media pipeline** whose whole reason for existing
is **decoupling**: transcoding is CPU- and memory-heavy, so running it inline on
the web server would freeze the UI for everyone. The three stages run
independently — a **FastAPI web tier** accepts an upload and returns instantly, an
**S3 event** fans a job into **SQS**, and a separate **EC2/FFmpeg worker** pulls
the job, transcodes to **HLS**, writes the Output bucket, and flips the
**DynamoDB** row to `Ready`. The browser polls status and then streams the HLS
through **CloudFront**.

The hardened build keeps that architecture faithful but rebuilds it as
reproducible **AWS CDK (Python)**, three stacks (`NetworkStack`, `DataStack`,
`AppStack`), and closes the eleven hardening flags the tutorial left open. The web
tier is a self-built JSON API (no inline HTML blob) run unprivileged by
gunicorn/uvicorn behind an **internal ALB**; the SPA is vanilla HTML/JS on
**S3 + CloudFront**; playback is CloudFront **signed cookies** against a private
Output bucket. This mirrors the v1→Phase-2 arc of
[[projects/photoshare-app|PhotoShare]] and reuses the CDK discipline
(removal policies, explicit log groups, `BucketDeployment` + generated
`config.json`, `CfnOutput`s) from [[projects/clear-thinking-app|Clear Thinking]].

## 2. Design choices (why each service)

| Component | Choice | Why |
| --- | --- | --- |
| IaC | **AWS CDK (Python)**, 3 stacks | One language infra+app; one-command teardown; split along lifecycle/teardown boundaries (`DESIGN.md` "CDK stack decomposition") |
| Network | VPC, public + private subnets across 2 AZs, single NAT | Public subnets hold only the NAT; ALB, web ASG, worker ASG are all private |
| Public surface | **One CloudFront distribution**, three origins | Single HTTPS domain for SPA (`/*`), API (`/api/*` → API Gateway HTTP API over HTTPS → VPC Link → internal ALB), media (`/media/*` → Output bucket OAC) |
| Web tier | EC2 ASG running **FastAPI** (gunicorn/uvicorn), unprivileged, port 8000 | Self-built contract; no root, no Flask dev server; behind the internal ALB |
| Worker | EC2 ASG, **c7i.large**, FFmpeg, private subnet, min0/max4/desired0 | Compute-optimized for real transcode; scale-to-zero on queue depth; no inbound |
| Ingest buffer | **SQS** + **DLQ** (`maxReceiveCount=3`, 900s visibility) | Decouples upload from transcode; quarantines poison pills; timeout exceeds worst-case transcode |
| Data | **DynamoDB** `VideoCatalog`, PK `video_id`, GSI for listing | Single-item lookups by id; newest-first `Query`, never a table scan |
| Storage | 4 private S3 buckets (input, output, site, artifacts), Block Public Access | Durable object storage; Output served only via CloudFront signed cookies |
| Playback auth | CloudFront **signed cookies** (signed URLs in local dev) | One signing op for the whole HLS fan-out; Output bucket stays private |
| FFmpeg | **Pinned static build** staged to an artifact bucket | Reproducible; no boot-time pull from a flaky third-party host |
| Failed-state writer | Worker (graceful) **+ DLQ-marker Lambda** (crash) | Two writers so the crash path also surfaces `Failed` in the UI |
| Admin access | **Session Manager** only (SSM endpoints) | No security group opens port 22 anywhere |
| Observability | Explicit CloudWatch log groups (`DESTROY`, 2-week retention) | Nothing lingers after teardown |

Fuller rationale for each lives in [`DESIGN.md`](./DESIGN.md) and the
[[projects/video-streaming-app|build doc]].

## 3. Assumptions (branch-point decisions, confirmed)

Agreed with the user at the hardening branch point:

| Requirement | Decision | Why it matters |
| --- | --- | --- |
| **IaC** | **AWS CDK in Python** (not TypeScript) | User doesn't know TypeScript; CDK gives one-command teardown + CDK/CFN breadth |
| **Transcode compute** | **Stay faithful** — a hardened EC2/FFmpeg worker (not Fargate/MediaConvert) | Keeps the tutorial's compute story; hardening is about the gaps, not a rewrite |
| **Local verification** | Run and verify the **web tier + SPA locally** before deploying | "Test locally first" — drove the env-injected config and the signed-URL local playback path |
| **Frontend** | **Vanilla HTML/JS static SPA** (no framework/build step) on S3 + CloudFront | Replaces the tutorial's inline `HTML_TEMPLATE`; composes with CloudFront playback |
| **Playback vehicle** | **CloudFront signed COOKIES** in production (signed URLs in local dev) | Confirmed with the user — HLS fans out to many segments, so cookies authorize the whole prefix with one signing op (see §4) |
| **Auth** | **None this pass** — public, like the tutorial | No Cognito; keeps scope on the hardening flags |
| **Account / region** | `678602035067` / `us-east-1` | Where the lab + Bedrock-free managed services live |

### Explicitly out of scope for this pass

- **Authentication** — public like the tutorial; Cognito is a later pass.
- **Multi-region DR** — single region; durability is regional-managed-service + S3.
- **A live deploy in this workflow** — the IaC is complete and locally runnable;
  deploy/teardown is a deliberate, separate operator action (see §7).

## 4. How each hardening flag is closed by the as-built code

The tutorial v1 took the simpler path in eleven places (several **verified live**
as real failures). Each row names the v1 gap and the concrete construct/code that
closes it in Phase 2.

| v1 hardening flag | Closed by (as-built) |
| --- | --- |
| **One shared `*FullAccess` role** across both servers | **Two asymmetric least-privilege roles** in `app_stack.py`: `video-web-role` (S3 `PutObject` to `input/*`, `GetObject` on `output/*`, scoped `ListBucket`, DynamoDB read/write + Query, `GetSecretValue` on the one signing secret — **no SQS**) and `video-worker-role` (SQS receive/delete on `VideoQueue`, S3 `GetObject` on input + artifacts, `PutObject` to `output/*`, DynamoDB `UpdateItem`/`GetItem` — **no PutObject to Input, no SendMessage**). Each statement is pinned to this project's literal ARNs. |
| **Worker in a public subnet with SSH open to the world** | Worker ASG lives in **private subnets** (`network_stack.py`), `worker-sg` has **no inbound rules at all**, and **no SG anywhere opens port 22**. Admin is **Session Manager** via the three SSM interface endpoints (`ssm`, `ssmmessages`, `ec2messages`) plus `AmazonSSMManagedInstanceCore` on both roles. |
| **No DLQ → poison-pill OOM loop (verified live)** | `data_stack.py` attaches **`VideoQueue-DLQ`** with `max_receive_count=3` and 14-day retention; the main queue uses **900s visibility** (exceeds worst-case transcode, so no mid-work redelivery) and 20s long polling. |
| **Non-idempotent worker + 30s default visibility → double-processing** | `worker.py` checks `get_status` before processing and **skips when the row is already `Ready`** (idempotent); combined with the 900s visibility, redeliveries are both rare and harmless. |
| **No `Failed` status on error (verified live, UI gave no signal)** | **Two writers.** The graceful path: on a non-zero FFmpeg exit the worker writes `status=Failed` and deletes the message (deterministic rejection — same bytes fail every time, so no retry). The crash path: a worker killed mid-job (the 4K OOM case) can't write anything, so after `maxReceiveCount` redeliveries the message lands in the DLQ and the **`video-dlq-failed-marker` Lambda** writes `Failed` (guarded by `attribute_exists(video_id)` so an orphan row isn't upserted). |
| **`video_id` derived differently by web vs worker (stuck-on-Queued bug)** | Derived **once** in `main.py` as `uuid4().hex` at upload and threaded through the S3 key **prefix** (`input/<video_id>/...`), the `x-amz-meta-video-id` object metadata, and the DynamoDB row. The worker and the DLQ Lambda both parse it from the key prefix with the identical `^input/(?P<video_id>[0-9a-f]{32})/` regex — **never from the filename**. |
| **`put_item` on completion overwrote the row** | Every state write uses **`update_item`** (merge), in both `main.py` and `worker.py`'s `set_status`. No `put_item` anywhere. |
| **t3.micro worker OOM-killed on 4K (verified live); no downscale** | Worker is **c7i.large** (compute-optimized). `build_ffmpeg_cmd` pins **`scale=-2:720`, H.264 baseline, `-level 3.1`, AAC, HLS `-hls_time 6 -hls_playlist_type vod`** — large inputs are downscaled to fit and the codecs are HLS-safe. gp3 root volumes sized for the 2 GB upload cap + scratch. |
| **Single fixed worker; no scale-to-zero** | Worker ASG is **min0/max4/desired0** with two disjoint one-sided step policies on queue depth: scale-out on `ApproximateNumberOfMessagesVisible` (1→19 ⇒ 1, 20→49 ⇒ 2, ≥50 ⇒ 4), scale-in to 0 when `visible + not-visible == 0` for 15 sustained minutes. A 900s **termination lifecycle hook** lets an in-flight transcode drain on SIGTERM (the worker records heartbeats and completes the hook). |
| **No S3 lifecycle (cost/sustainability)** | Input bucket tiers `input/` to **Standard-IA at 30d** and **Glacier at 90d**, with incomplete-multipart cleanup at 7d; Output bucket keeps HLS hot (MPU cleanup only). |
| **`/api/videos` did a full DynamoDB `scan` every 3s** | `list_videos` runs a **GSI `Query`** (`by-status-created`, `gsi_pk="VIDEO"`, `ScanIndexForward=False`, `Limit=100`) — newest-first with no table scan. |
| **Bare `except: 404` masked all errors in `/stream`** | Every route maps **specific `ClientError` codes** to distinct HTTP statuses (`ResourceNotFoundException`→500, absent item→404, other→502), plus a catch-all handler that logs with the `video_id` and returns a 500 — no error is silently turned into a 404. |
| **"Browser streams directly from a public bucket" / Flask proxy** | Output bucket is **private (Block Public Access ON)**; CloudFront reaches it via **OAC** and `/media/*` **requires a trusted key group** (signed cookies). The browser never touches S3 and the web tier no longer relays bytes. |
| **Console-built, not reproducible; FFmpeg from a flaky host** | Whole stack is **CDK**; FFmpeg is a **pinned static build** staged into the artifact bucket by `scripts/fetch-ffmpeg.sh` before synth (synth fails if the asset dir is empty, by design), downloaded to the worker from S3 at boot. |

## 5. The CloudFront signed-cookie playback decision

The settled spec wording said "CloudFront + **signed URLs**." The as-built code
meets that requirement's substance — private Output bucket, CloudFront-gated
playback, no public S3, per-video-scoped credentials — but uses **signed cookies
for production playback**, confirmed with the user. The reason is the HLS fan-out:
one `.m3u8` plus many `.ts` segments. Per-object signed URLs would force a
playlist rewrite on every play; a single set of **signed cookies scoped to
`/media/{video_id}/*`** authorizes the whole prefix with one signing operation and
no rewrite.

- `GET /videos/{video_id}/play-url` (when status is `Ready`) sets the three
  CloudFront cookies (`CloudFront-Policy`, `CloudFront-Signature`,
  `CloudFront-Key-Pair-Id`) with a **custom policy scoped to the one video**,
  `Path=/media/{video_id}/`, `Secure`, `HttpOnly`, `SameSite=None`, 6-hour TTL.
- Because the SPA, the API, and `/media/*` all live under the **one CloudFront
  domain**, the cookies are same-origin and attach to `hls.js`'s segment XHRs
  automatically — no `withCredentials`/`xhrSetup`. On a segment `403` (expired
  cookies) the player's `onRefresh` re-calls `play-url` and resumes.
- **Signed URLs are still exercised in local dev**: a browser on `127.0.0.1`
  can't carry a CloudFront-domain cookie, so `PLAYBACK_MODE=signed-url` returns a
  rewritten playlist whose segment lines are absolute signed URLs. The signing
  mechanism the spec names is therefore still used; only the production delivery
  vehicle differs.
- The signing key is loaded **once at startup** from Secrets Manager into an
  in-memory RSA key (never per request), with a 12-hour TTL refresh; `/health`
  reports `503` until it is loaded so the ALB never routes unsignable playback.
  The `CF_KEY_PAIR_ID` env is the CloudFront **public-key** id (output
  `CfPublicKeyId`), not the key-group id.

## 6. Tradeoffs (what was chosen NOT to do, and why)

- **EC2/FFmpeg worker over Fargate/MediaConvert.** Stays faithful to the
  tutorial's compute story and keeps the SQS-driven ASG visible. *Tradeoff:* we
  manage the AMI/launch template and the FFmpeg artifact rather than handing
  transcoding to a managed service.
- **Signed cookies over per-object signed URLs in production** (see §5). *Tradeoff:*
  diverges from the literal spec wording; accepted and confirmed because it avoids
  a per-play playlist rewrite.
- **Single NAT gateway** (one, not one-per-AZ). *Tradeoff:* the private tier's
  *outbound* egress is a single-AZ risk; acceptable for a lab whose scale-to-zero
  worker leaves NAT mostly idle, and gateway endpoints keep S3/DynamoDB off NAT.
- **Internal ALB fronted by an API Gateway HTTP API + VPC Link, over an
  internet-facing ALB + ACM or a CloudFront VPC origin.** Keeps the ALB private
  (hardening preserved), encrypts the CloudFront→origin hop on the `execute-api`
  cert, and stays on the single CloudFront domain. This replaced a CloudFront VPC
  origin that did not pass edge→ALB traffic in the live deploy (§9a, Finding 3).
  *Tradeoff:* one extra managed hop (API Gateway) and its `/api`-prefix path
  mapping, versus a direct origin — accepted because the VPC origin didn't work
  and the internet-facing-ALB alternative loses the private-ALB hardening.
- **Fixed-name resources** (buckets with an account+region suffix, `VideoCatalog`,
  `VideoQueue`, the worker ASG name). *Tradeoff:* less CDK auto-naming, but the
  IAM policies stay literal ARNs and user-data can embed the ASG name with no
  dependency cycle.
- **Out-of-band private-key load** (operator runs `put-secret-value` after
  deploy) over an in-stack custom resource. Keeps the private key off the
  CloudFormation surface entirely. *Tradeoff:* one documented manual step.
- **No auth this pass.** Simpler and on-scope for a hardening pass about the
  pipeline gaps. *Tradeoff:* the surface is public; Cognito is a later pass.

## 7. Failure modes (intended mitigations — as-built, not deploy-verified here)

For each component: what happens if it fails, the blast radius, and the mitigation
in code. These are **designed and coded**, not verified against a live stack in
this workflow (the tutorial v1 OOM crash loop, by contrast, was verified live —
see the build doc).

| Component | If it fails… | Blast radius | Mitigation (as-built) |
| --- | --- | --- | --- |
| Web EC2 (one instance) | that node gone | Contained | **ASG across 2 AZs** (min1/max2); ALB `/health` check routes around it |
| Worker killed mid-transcode (the 4K OOM case) | that job unfinished | Contained — upload never lost | SQS redelivers to `maxReceiveCount=3` → **DLQ** → **DLQ-marker Lambda writes `Failed`**; no infinite loop |
| FFmpeg rejects the input (bad bytes) | that job fails | Per-job | Worker writes `Failed` and **deletes** the message (deterministic — no retry) |
| Duplicate SQS delivery (at-least-once) | re-processing risk | Per-job | **Idempotency** (skip if already `Ready`) + **900s visibility** (no mid-work redelivery) |
| Queue backlog spike | transcode lag | Throughput | Worker ASG **scales out** on visible-message bands (up to 4) |
| Sustained idle | wasted spend | Cost | Worker ASG **scales to zero** after 15 idle minutes; graceful drain on SIGTERM |
| Signing key unreadable at startup | can't sign playback | Playback only | `/health` returns **503** so the ALB pulls the target; cached key reused on refresh failure |
| Expired playback cookie mid-watch | segment `403` | Per-session | Player `onRefresh` re-calls `play-url` and resumes |
| DynamoDB read/write fails | status/listing errors | Core data | Specific `ClientError` → correct HTTP status; On-Demand absorbs spikes |
| S3 unavailable | ingest/playback degraded | High | 11-nines durability; regional service; Output served only via CloudFront |
| Upload exceeds the cap | that upload rejected | Per-request | `_LimitedReader` aborts mid-stream at `MAX_UPLOAD_BYTES`; orphan object compensating-deleted |

## 8. Well-Architected mapping (feeds KR3)

| Pillar | State (Phase 2, as-built) | Notes / further improvements |
| --- | --- | --- |
| Operational Excellence | Console → **IaC (CDK Python)**, repeatable + versioned; FFmpeg **pinned**; explicit `DESTROY` log groups; `Failed` surfaced on both graceful and crash paths | Add a deploy pipeline + change-set previews; a dashboard/alarms suite |
| Security | **Two least-privilege roles**, **private worker + no port 22** (Session Manager), private Output bucket via OAC + **signed-cookie** `/media/*`, signing key in Secrets Manager (loaded once, never in code/AMI/SPA), S3 Block Public Access on all buckets, IMDSv2 required | Add auth (Cognito); customer-managed KMS; WAF on CloudFront |
| Reliability | **DLQ** + **idempotency** + **900s visibility**; two-writer `Failed`; web ASG across 2 AZs; graceful worker drain | Deploy + run the two live failure tests (graceful reject + worker-kill poison pill) |
| Performance Efficiency | **c7i.large** worker; `scale=-2:720` downscale + HLS-safe codecs; GSI listing (no scan); signed cookies = one signing op per play | Load-test to tune the scale-out bands and instance size |
| Cost Optimization | Worker **scales to zero**; On-Demand DynamoDB; S3 **lifecycle** (IA@30d, Glacier@90d); single NAT; gateway endpoints keep S3/DynamoDB off NAT | Right-size after load testing; per-AZ NAT if the egress SPOF matters |
| Sustainability | Managed services + scale-to-zero worker + lifecycle-tiered storage avoid provisioning for peak | — |

## 9. Build & validation status

- **Built as AWS CDK (Python)** — three stacks (`NetworkStack`, `DataStack`,
  `AppStack`) that synthesize; the VPC is defined in-stack (no `from_lookup`) and
  the two AZs are pinned so synth stays credential-free.
- **Locally runnable** — the FastAPI web tier + the vanilla SPA run over loopback
  against env-injected resource names, with signed-URL local playback (see
  [`LOCAL_DEV.md`](./LOCAL_DEV.md)). Resource names come from env so the local and
  deployed runs use the **identical code path**.
- **Unit tests** cover the pure logic: web-tier `video_id`/key construction, the
  GSI query, signing (TTL + scoped path), `ClientError`→HTTP mapping, input
  validation; worker `video_id` extraction, idempotency skip, FFmpeg argv, and the
  `Failed`-on-nonzero-exit path; and the DLQ-marker parse → `UpdateItem`.
## 9a. Live deployment record (2026-10-22)

Deployed to account `678602035067` / `us-east-1` via `cdk deploy`, tested, and
torn down the same day. The live run validated the architecture **and surfaced
three real defects that `synth` + mocked unit tests could not** — the whole point
of a live pass (same spirit as PhotoShare's MySQL-8 crash).

**Verified working live:** all three stacks deploy clean (~18 min, CloudFront the
long pole); S3+OAC serves the SPA and `config.json`; the Output bucket stays
private; SSM Session Manager reaches the private instances (no port 22); the web
ASG target is healthy; the signing-key-at-boot gate works (`/health` 503 until the
secret is loaded, then 200); DynamoDB/SQS/DLQ/secret all present; `cdk destroy`
removes everything cleanly.

**Finding 1 — Python runtime mismatch (fixed live).** The web gunicorn worker
crashed: `ImportError: cannot import name 'UTC' from 'datetime'`. Amazon Linux
2023's default `python3` is **3.9**, but the app uses `datetime.UTC` (3.11+). The
worker had the same latent gap plus **no venv and no boto3 install** (it had never
run — scale-to-zero). Fix: both user-data scripts now install **python3.11**,
build the venv with it, and the worker ships + installs its `requirements.txt`;
`video-worker.service` runs the venv interpreter. *Lesson: `synth` and mocked
pytest run on the build host's Python, never the AMI's — exercise the real runtime.*

**Finding 2 — CloudFront bare-root 403 (fixed live).** `/index.html` served 200
but `/` returned 403: a prior fix removed the distribution-wide `403→index.html`
(needed so `/media` signed-cookie 403s reach the player) and nothing covered the
root. Fix: set `default_root_object=index.html`.

**Finding 3 — CloudFront VPC-origin → internal ALB will not pass traffic (diagnosed first pass; remediation confirmed live in the second pass — see below).**
Every `/api/*` request returns a **30-second CloudFront 504**, while the app
answers instantly on the instance itself (`localhost:8000/health`→200,
`/api/videos`→404). Exhaustively ruled out as causes, all verified correct live:
the VPC origin is `http-only` port **80**, the ALB listener is HTTP **80**
(internal, active), the target group is **healthy** on 8000, the VPC-origin ENIs
sit at **10.0.2.9 / 10.0.3.76** inside the `alb-sg`-allowed `10.0.2.0/24` +
`10.0.3.0/24` (and broadening ingress to the whole `10.0.0.0/16` changed nothing),
and the subnet NACLs are default allow-all. So a textbook-correct configuration
of the **newer CloudFront VPC-origin feature** still would not carry traffic from
the edge to the private ALB. A secondary `/api`-prefix mismatch waits behind it
(CloudFront forwards `/api/videos` but the app serves `/videos`).
**Remediation — APPLIED IN CODE, `synth`-verified, and later live-redeployed and confirmed (see "Second live pass" below).**
The VPC-origin hop is removed and replaced with a well-trodden path: CloudFront
`/api/*` → an **API Gateway HTTP API** (its AWS-managed `execute-api` HTTPS
endpoint, used as an `HttpOrigin` with `protocol_policy=HTTPS_ONLY`) → a **VPC
Link** (ENIs in the private subnets, `vpclink-sg`) → the **still-internal ALB** →
the web ASG (FastAPI on `:8000`). The secondary `/api`-prefix mismatch is fixed in
the same hop: the HTTP API route is `ANY /api/{proxy+}` with an integration
parameter mapping `overwrite:path = /${request.path.proxy}`, so the ALB (and the
app) receive `/videos`, `/health`, … unprefixed — the FastAPI app is unchanged
and local dev keeps working. Verified by `cdk synth` + `ruff` + `pytest`:

- the `VideoAppStack` template has an `AWS::ApiGatewayV2::Api` (`video-api`,
  HTTP), an `AWS::ApiGatewayV2::VpcLink`, and a `VPC_LINK` integration to the ALB
  HTTP listener with `overwrite:path = /${request.path.proxy}`;
- the ALB is still `Scheme: internal` (no public IP) and its SG admits TCP 80
  from `vpclink-sg` only — no `0.0.0.0/0`;
- the CloudFront `/api/*` behaviour points at the `execute-api` origin with
  `OriginProtocolPolicy: https-only` and the `AllViewerExceptHostHeader`
  origin-request policy (so API Gateway sees its own Host); and
- the `AWS::CloudFront::VpcOrigin` resource is gone.

This keeps the ALB private (hardening preserved), encrypts the CloudFront→origin
hop carrying the signed-cookie `Set-Cookie`, and stays on the single CloudFront
domain (no CORS/cross-domain-cookie issues). Re-proving it live is a future
one-command redeploy.

### Second live pass (2026-10-22) — remediation confirmed + end-to-end validated

The remediated code was redeployed and run end-to-end. Results:

- **Finding 3 confirmed fixed.** `GET /api/videos` returned `200 {"videos":[]}`
  in ~0.13 s through the new CloudFront → API Gateway HTTP API → VPC Link →
  internal ALB → FastAPI path. The VPC-origin 504 is gone; the ALB stayed
  `internal`.
- **Finding 4 — `/media/*` → `output/` prefix mismatch (found and fixed this
  pass).** A video reached `Ready`, but playback stalled at 0:00. The signed
  cookies, key group, and public-key↔private-key pair all verified **correct** —
  CloudFront accepted the cookies and forwarded to S3 (`server: AmazonS3`), and
  **S3** returned the 403. Root cause: the worker writes HLS to the Output bucket
  under `output/<id>/…`, but the `/media/*` behaviour had an empty origin path, so
  CloudFront asked S3 for `media/<id>/playlist.m3u8` — a key that never exists.
  Nothing mapped the public `/media/` prefix to the stored `output/` prefix. Fix:
  a CloudFront **viewer-request Function** on `/media/*` rewrites `/media/` →
  `/output/` (origin path cannot do this — it prepends and cannot strip the
  matched `/media` segment). `cdk synth` confirms the `AWS::CloudFront::Function`;
  verified live by serving the real keys and re-fetching through the edge with the
  signed cookies (manifest `200 application/vnd.apple.mpegurl`, segment
  `200 video/mp2t`). *Lesson: a correct signing path still fails if the public URL
  prefix and the stored S3 key prefix were never reconciled — and a post-cookie
  403 is the origin's, not the signer's.*
- **Two UI fixes.** The upload modal now auto-closes on a successful upload
  (`app.js` `closeUploadModal()` on the success path), and `[hidden]` is forced
  with `display:none` so the player/upload modals stay closed until opened.
- **End-to-end validated.** Browser upload → `Queued` → EC2/FFmpeg worker
  cold-start (ASG 0→1) → `Ready` → **signed-cookie HLS playback in the browser**.
  See [`docs/screenshots/01-landing-hero.png`](./docs/screenshots/01-landing-hero.png)
  (landing page) and [`docs/screenshots/02-playback.png`](./docs/screenshots/02-playback.png)
  (the clip playing in the player modal).
- **Thumbnails deferred (future enhancement).** Gallery cards show a placeholder,
  not a poster frame — the pipeline generates no thumbnail and all media sits
  behind signed cookies, so a proper preview needs a frame extracted at transcode
  time and stored on a public (site-bucket) path. Scoped as a future enhancement,
  not a hardening objective (see DESIGN.md).
- **Teardown re-verified** — `cdk destroy --all` removed every stack with no
  lingering buckets/table/queues/secret/log groups/distribution/ASGs.

## 10. Takeaways

- **The hardening analysis drove a concrete design.** Every v1 flag maps to a
  specific construct or code path (§4), not a vague "to improve later" — the
  whole point of the v1→Phase-2 exercise.
- **Decoupling is the backbone, and failure handling is now complete.** SQS still
  absorbs a dying worker, and the DLQ + the DLQ-marker Lambda mean even the
  crash path ends in a visible `Failed` instead of an infinite loop.
- **`video_id` as a single correlation id** threads S3 ↔ SQS ↔ DynamoDB ↔ the
  player; deriving it once (and parsing it identically everywhere) removes the
  stuck-on-Queued class of bug.
- **One CloudFront domain** solves mixed-content, cross-domain cookies, and the
  private-bucket requirement at once — the signed-cookie choice follows directly
  from the HLS fan-out.
- **Private-by-default, verified in code** — no port 22, private worker, private
  buckets, a signing key that never touches source. The design is coded; the live
  proof is the next, operator-run step.
