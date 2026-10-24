---
title: "Design: Video Streaming Platform — hardened (Phase 2) IaC build"
type: design
domain: architecting
date: 2026-10-20
tags:
  - aws
  - design
  - cdk
  - ec2
  - sqs
  - s3
  - dynamodb
  - cloudfront
---

# Design: Video Streaming Platform — hardened (Phase 2) IaC build

> Requirements source: [[projects/video-streaming-app|the video-streaming-app project doc]]
> (architecture, Hardening flags, Well-Architected review, Gotchas). This design
> turns every hardening flag into a concrete, implementable decision.
> Reference patterns (structure/discipline, not copied):
> [[projects/clear-thinking-app|clear-thinking-app]] (its `iac/` CDK app — removal policies,
> explicit log groups, `BucketDeployment` + generated `config.json`, `CfnOutput`s)
> and [[projects/photoshare-app|photoshare-app]] (FastAPI + boto3 patterns,
> v1→Phase-2 hardening style).
>
> **Language note:** the clear-thinking-app reference CDK is **TypeScript**
> (`aws-cdk-lib` via npm, `clear-thinking-stack.ts`); this build is **Python**.
> Mirror its *structure* only — translate every API name to the Python binding
> (`aws_cdk` imports, snake_case props, `s3deploy.Source.json_data('config.json',
> {...})` not TypeScript's `Source.jsonData(...)`). Do not copy TS signatures.

## Overview

The hardened build recreates the same event-driven pipeline (upload → S3 Input →
S3 event → SQS → EC2/FFmpeg worker → S3 Output → DynamoDB `Ready` → playback) as
reproducible Infrastructure-as-Code, and closes the eleven hardening flags from
the project doc. The stack is **AWS CDK in Python** (`aws-cdk-lib` v2,
`cdk init app --language python`), deploying to **account 678602035067 /
us-east-1**. Compute stays faithful to the tutorial: an **EC2 + FFmpeg worker**,
hardened (compute-optimized, private subnet, Auto Scaling Group driven by SQS
queue depth) rather than Fargate or MediaConvert. The web tier is a **FastAPI
(Python) JSON API** run by `gunicorn`/`uvicorn` workers, unprivileged, behind an
**Application Load Balancer**. The frontend is a **vanilla HTML/JS static SPA**
(no build step) on **S3 + CloudFront**. Playback is **CloudFront + signed URLs**
against a **private** Output bucket. No auth this pass — public, like the
tutorial (no Cognito).

The technology stack is locked once this design is approved: Python 3.12, CDK v2
pinned to **`aws-cdk-lib >=2.170.0`** (matches the clear-thinking-app reference
app; the `aws_apigatewayv2`/`aws_apigatewayv2_integrations` L2 constructs the
`/api` hop relies on — `HttpApi`, `VpcLink`, `HttpAlbIntegration` — are stable in
this range), FastAPI + `uvicorn`/`gunicorn` + `boto3` for the
web tier, a Python `worker.py` long-poll loop + static FFmpeg for the worker,
Amazon Linux 2023 AMIs, and vanilla ES-module JS (`hls.js` for playback) for the
SPA.

## Named resources (correlation targets for IAM scoping)

To keep the two IAM roles scoped to this project's exact ARNs, the stack names
its stateful resources deterministically (region/account are fixed):

| Logical | Physical name | ARN shape |
| --- | --- | --- |
| Input bucket | `video-input-678602035067-us-east-1` | `arn:aws:s3:::video-input-678602035067-us-east-1` |
| Output bucket | `video-output-678602035067-us-east-1` | `arn:aws:s3:::video-output-678602035067-us-east-1` |
| Frontend bucket | `video-site-678602035067-us-east-1` | `arn:aws:s3:::video-site-678602035067-us-east-1` |
| FFmpeg artifact bucket | `video-artifacts-678602035067-us-east-1` | `arn:aws:s3:::video-artifacts-678602035067-us-east-1` |
| Jobs table | `VideoCatalog` | `arn:aws:dynamodb:us-east-1:678602035067:table/VideoCatalog` |
| Transcode queue | `VideoQueue` | `arn:aws:sqs:us-east-1:678602035067:VideoQueue` |
| Dead-letter queue | `VideoQueue-DLQ` | `arn:aws:sqs:us-east-1:678602035067:VideoQueue-DLQ` |

Buckets carry a fixed account+region suffix (globally unique without a random
id, so the ARNs are known at synth time and the IAM policies stay literal).

## CDK stack decomposition

One CDK app, three stacks, split along lifecycle and teardown boundaries:

1. **`NetworkStack`** — the VPC, subnets, NAT gateway, and VPC endpoints. Changes
   rarely; separated so the app stacks can reference it without re-synthesizing
   networking.
2. **`DataStack`** — the four S3 buckets, the `VideoCatalog` table, and
   `VideoQueue` + `VideoQueue-DLQ`. These hold state and own the removal
   policies; isolating them makes the "what gets destroyed" surface obvious.
3. **`AppStack`** — the ALB + web-tier ASG (FastAPI), the worker ASG + launch
   template, both IAM instance roles, the S3→SQS event notification, the
   **DLQ-consumer Lambda** (`video-dlq-failed-marker`) that marks exhausted jobs
   `Failed`, the single CloudFront distribution (SPA + `/api/*` → ALB origin +
   `/media/*` → Output bucket) and its key group for signed cookies, the
   `BucketDeployment` of the SPA, CloudWatch log groups, and all `CfnOutput`s.

Cross-stack wiring is by object reference (CDK generates the exports/imports).
Alternative considered: a single monolithic stack (simpler, as in
clear-thinking-app). Rejected because the worker AMI/launch-template churns far
more than the VPC or the data resources, and a three-stack split lets the data
resources be destroyed last and deliberately. The split is cheap in CDK and
keeps blast radius small.

## VPC / subnet / NAT / VPC-endpoint layout

A single VPC (`10.0.0.0/16`) across two AZs:

- **Public subnets** (one per AZ) host only the **NAT gateway**. There is no
  internet-facing load balancer: the **ALB is internal** (no public IP, placed in
  the private subnets) and is reached only through an **API Gateway HTTP API +
  VPC Link** (below), so the single public surface is the CloudFront distribution
  itself.
- **Private subnets** (`PRIVATE_WITH_EGRESS`, one per AZ) host the **internal
  ALB**, the web ASG instances, the worker ASG instances, and the **API Gateway
  VPC Link ENIs**. Nothing here gets a public IP. The web tier is reachable only
  through the ALB (itself reachable only from the VPC Link's ENIs); the worker is
  reachable by nothing inbound.
- **NAT gateway** (single, in one public subnet — cost choice for a lab; the
  doc's scale-to-zero worker means NAT is mostly idle) gives private instances
  outbound for OS/package updates and SSM.
- **VPC endpoints**, so S3/SQS/DynamoDB traffic never leaves the AWS network and
  doesn't bill through NAT:
  - **Gateway endpoints**: S3 and DynamoDB (free; route-table entries on the
    private subnets).
  - **Interface endpoints**: SQS, **Secrets Manager** (so the web tier's
    signing-key reads stay on the AWS network and don't exit via NAT — closes the
    "credential call leaves via NAT" gap), plus the three SSM endpoints
    (`ssm`, `ssmmessages`, `ec2messages`) so **Session Manager** works with no
    inbound path.

**Admin access is Session Manager only.** No security group anywhere opens
inbound SSH (port 22) — this directly closes the "SSH `0.0.0.0/0`" flag and the
"worker needs no inbound at all" flag. The SSM interface endpoints let the agent
reach Systems Manager over the private network; operators use
`aws ssm start-session`. (Per the builder-security policy: datastores and compute
are private by default; the only public ingress is the CloudFront distribution on
443. The ALB is internal and reached only through the API Gateway VPC Link.)

**Security groups** (private-by-default, least ingress):

- `alb-sg` (internal ALB): inbound **TCP 80 only, from the API Gateway VPC Link's
  security group** (`vpclink-sg`) — not `0.0.0.0/0`, and not a private-subnet
  CIDR range. The `/api` hop is CloudFront → an **API Gateway HTTP API** (over
  HTTPS) → a **VPC Link** → this internal ALB (see **CloudFront + signed-cookie
  playback** and the Finding-3 remediation note below). The VPC Link places its
  ENIs in the private subnets carrying `vpclink-sg`, so referencing that SG is an
  exact, synth-resolvable ingress source — nothing else can reach the internal
  ALB (it has no public IP and no public-subnet exposure). This is the Finding-3
  remediation: the CloudFront→origin hop now terminates on the API Gateway
  endpoint's AWS-managed TLS cert (so the signed-cookie `Set-Cookie` and uploaded
  bytes are encrypted over the internet), and the API-Gateway→ALB hop stays on
  AWS's private network via the VPC Link. No ACM cert is needed on the ALB's
  unresolvable `*.elb.amazonaws.com` name. Egress to `web-sg` on the app port
  only.
  ```python
  # network_stack.py
  alb_sg.add_ingress_rule(
      peer=vpclink_sg,
      connection=ec2.Port.tcp(80),
      description="From API Gateway VPC Link only")
  vpclink_sg.add_egress_rule(
      peer=alb_sg,
      connection=ec2.Port.tcp(80),
      description="To internal ALB (HTTP listener)")
  ```
  - **Why API Gateway + VPC Link and not a CloudFront VPC origin (Finding 3).**
    An earlier revision used a `cloudfront.VpcOrigin` straight to the internal
    ALB. In a live deploy that path returned a 30 s CloudFront 504 on every
    `/api/*` request despite a textbook-correct SG/port/target-health/NACL
    configuration (see `walkthrough.md` §9a). The API Gateway HTTP API + VPC Link
    is the well-trodden replacement: the HTTP API's default
    `https://{id}.execute-api.{region}.amazonaws.com` endpoint carries a valid
    AWS-managed cert (so CloudFront uses it as an HTTPS custom origin with
    `protocol_policy=HTTPS_ONLY`, no custom domain), and the VPC Link reaches the
    still-internal ALB privately. The `/api` prefix is stripped at the HTTP API
    (route `ANY /api/{proxy+}`, integration parameter mapping
    `overwrite:path = /${request.path.proxy}`) so the FastAPI app keeps its
    existing unprefixed routes (`/videos`, `/health`, …) and local dev — which
    calls those routes unprefixed — is unaffected.
  - *Alternative considered:* an internet-facing ALB restricted to the
    `com.amazonaws.global.cloudfront.origin-facing` managed prefix list with an
    ACM cert. Rejected because it makes the ALB internet-facing (loses the
    hardening) and needs a custom domain + cert; the API Gateway path keeps the
    ALB private with zero cert management and stays on the single CloudFront
    domain (no CORS / cross-domain-cookie issues).
- `vpclink-sg` (API Gateway VPC Link ENIs): no inbound; egress **TCP 80 to
  `alb-sg`** only. The VPC Link is created in the private subnets with this SG.
- `web-sg`: inbound only from `alb-sg` on the gunicorn port (**8000**). No other
  inbound. Egress: HTTPS to the VPC endpoints + NAT.
- `worker-sg`: **no inbound rules at all**. Egress: HTTPS to endpoints + NAT.

**Web-tier ASG sizing.** The web ASG (FastAPI behind the ALB) uses **`t3.small`**
(2 GB RAM — enough for `gunicorn` + a few `uvicorn` workers; the web tier does no
transcoding, only I/O-bound S3/DynamoDB calls and signing), launch template with
`video-web-role`, `web-sg`, private subnets, no public IP. Capacity
**`minCapacity=1, maxCapacity=2, desiredCapacity=1`** across the two AZs. Scaling
is a single **CPU target-tracking policy at 60%** (`maxCapacity=2` is the ceiling)
— simple and sufficient for a public, no-auth lab with light traffic; it never
scales to zero (unlike the worker) because the ALB needs a live target to serve
the SPA's API calls. For a truly idle lab, `min=desired=1` alone carries it.

## IAM — two least-privilege per-server roles

Replaces the single shared `*FullAccess` `iam_role_video_lab`. Each role is an
EC2 instance profile with `AmazonSSMManagedInstanceCore` attached (for Session
Manager) plus a tight inline policy scoped to this project's exact ARNs. The two
roles are deliberately asymmetric: the web tier has an upload path but no queue
access; the worker has queue + output-write but no upload path.

**Web-tier role** (`video-web-role`):

| Action | Resource | Why |
| --- | --- | --- |
| `s3:PutObject` | `arn:aws:s3:::video-input-678602035067-us-east-1/*` | store the raw upload |
| `s3:GetObject` | `arn:aws:s3:::video-output-678602035067-us-east-1/*` | (fallback/debug read of HLS; primary playback is via CloudFront signed URLs) |
| `s3:ListBucket` | `arn:aws:s3:::video-input-…` with `Condition StringLike s3:prefix ["input/*"]`; `…video-output-…` with `Condition StringLike s3:prefix ["output/*"]` | enumerate the per-video prefixes to delete on `DELETE /videos/{video_id}` |
| `s3:DeleteObject` | `…video-input-…/input/*` **and** `…video-output-…/output/*` | delete the raw + HLS objects on `DELETE /videos/{video_id}` |
| `dynamodb:PutItem`, `UpdateItem`, `GetItem`, `Query`, `DeleteItem` | `table/VideoCatalog` **and** `table/VideoCatalog/index/*` | write `Queued`, read status, list via GSI, delete |
| `cloudfront:` — none | — | signing uses a private key from Secrets Manager, not an API call |
| `secretsmanager:GetSecretValue` | the CloudFront signing-key secret ARN | sign playback URLs/cookies |
| **SQS — none** | — | S3 fires the event, not the web server |

The `s3:ListBucket` condition uses a literal `StringLike` over the whole
owner-controlled prefix space (`input/*`, `output/*`), **not** a per-request
`${video_id}`. IAM has no `${video_id}` policy variable — only `${aws:…}`/`${s3:…}`
keys resolve at request time — so templating the id would either deny every
`ListObjectsV2` (the literal key never matches) or be underspecified. Scoping to
the prefix space keeps the grant tight to this project's two prefixes while
letting `DELETE /videos/{video_id}` list whichever per-video prefix it was handed.

The web tier is granted `s3:DeleteObject` on the **Output** bucket (for cleanup)
even though the worker is the *sole writer* of `output/` objects. Deletion is not
writing: the processing-time invariant ("only the worker produces HLS") is
preserved because the web tier never calls `PutObject` on Output — it only
removes a whole `output/{video_id}/` prefix when the user deletes the video. The
two roles still never overlap on *creation* of any object, which is what keeps
the split meaningful.

**Worker role** (`video-worker-role`):

| Action | Resource | Why |
| --- | --- | --- |
| `sqs:ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes`, `ChangeMessageVisibility` | `VideoQueue` | consume → process → delete lifecycle |
| `s3:GetObject` | `arn:aws:s3:::video-input-678602035067-us-east-1/*` | download the raw video |
| `s3:PutObject` | `arn:aws:s3:::video-output-678602035067-us-east-1/*` | write HLS output |
| `s3:GetObject` | `arn:aws:s3:::video-artifacts-678602035067-us-east-1/*` | pull the pinned FFmpeg build |
| `dynamodb:UpdateItem`, `GetItem` | `table/VideoCatalog` | idempotency check + `Processing`/`Ready` |
| `autoscaling:RecordLifecycleActionHeartbeat`, `autoscaling:CompleteLifecycleAction` | the worker ASG ARN | graceful drain via the ASG termination lifecycle hook (below) |
| **No `s3:PutObject` to Input; no upload path; no DLQ send** | — | worker never ingests |

The worker role no longer carries the `Failed`-write responsibility for the
poison-pill/OOM path (see **SQS + DLQ** — a DLQ-consumer Lambda owns that). The
DLQ redrive is a queue attribute, not an IAM grant, so neither EC2 role needs
`sqs:SendMessage` — the only sender is S3 (via the queue resource policy,
below). CloudFront signing uses a key pair whose private key lives in Secrets
Manager; only the web role can read it.

## SQS + DLQ

- **`VideoQueue`** (Standard): **visibility timeout 900 s (15 min)**, chosen to
  exceed the worst-case transcode. With the mandatory `scale=-2:720` downscale a
  single job is well under a minute, but 15 minutes leaves headroom for a large
  input on a busy worker and prevents the "message reappears mid-transcode →
  double-process" flag. Receive wait time 20 s (long polling).
- **`VideoQueue-DLQ`** (Standard): redrive policy on `VideoQueue` with
  **`maxReceiveCount = 3`**. A poison pill (the 4K OOM case) is retried three
  times, then quarantined in the DLQ instead of OOM-looping forever. DLQ message
  retention 14 days so a human can inspect failures.
- **S3 → SQS** stays native (the web server does not enqueue). The Input bucket's
  `ObjectCreated:*` notification targets `VideoQueue`. The queue's resource
  policy allows `s3.amazonaws.com` to `sqs:SendMessage` **only** when
  `aws:SourceArn` equals the Input bucket ARN (confused-deputy guard, carried
  over from the tutorial). CDK wires this in Python via:

  ```python
  input_bucket.add_event_notification(
      s3.EventType.OBJECT_CREATED,
      s3n.SqsDestination(video_queue),              # aws_cdk.aws_s3_notifications
      s3.NotificationKeyFilter(prefix="input/"),
  )
  ```

  which injects the `SourceArn`-scoped queue policy automatically.

**`Failed` status — two writers, covering both failure shapes (closes the "no
`Failed` status" flag completely):**

1. **FFmpeg exits non-zero but the worker survives** (bad codec, corrupt but
   parseable file): the worker treats a non-zero FFmpeg exit as a **deterministic
   rejection** — the same bytes will fail every time, so retrying is pointless and
   only burns `maxReceiveCount`. It `update_item`s `status=Failed` for that
   `video_id`, **deletes the SQS message** (no retry), and moves on. The worker
   owns this path because it is still alive to write it. **Transient
   infrastructure errors are explicitly *not* treated this way:** an
   `s3.download_file`/`get_object` failure, a local disk-full (`ENOSPC`), or a
   `ClientError` on the DynamoDB write is re-raised (or simply not
   `delete_message`'d), so the message stays invisible for the visibility timeout
   and is **redelivered** for another attempt rather than being written off as
   `Failed`. Only after `maxReceiveCount=3` genuine redeliveries does such a
   message dead-letter (path 2). `worker.py` distinguishes the two by *which*
   operation raised: a non-zero return from the FFmpeg subprocess → `Failed` +
   delete; any boto3/OS exception around download, disk, or state write → log and
   leave for redelivery.
2. **The worker process is killed mid-job** (the verified-live 4K OOM case) — it
   cannot write anything. The message is redelivered up to `maxReceiveCount=3`,
   then SQS moves it to `VideoQueue-DLQ`. A small **DLQ-consumer Lambda**
   (`video-dlq-failed-marker`, event source = `VideoQueue-DLQ`) parses
   `video_id` from the message body's S3 key (`input/<video_id>/…`) and
   `update_item`s `status=Failed` **with `ConditionExpression="attribute_exists(video_id)"`**
   so it only flips an existing catalog row to `Failed` and never upserts a
   spurious row for an orphan whose catalog write failed (the compensating-delete
   case above); a `ConditionalCheckFailedException` is caught, logged at info,
   and the message deleted (nothing to mark). Then it deletes the DLQ message.
   This is the **only** path that survives a worker OOM, so it is what actually
   closes the flag for the dominant failure mode. Its IAM role grants exactly
   `dynamodb:UpdateItem` on `table/VideoCatalog` (no index, no other table) and
   `sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes` on the DLQ only. It
   is added to `AppStack`, to the teardown list, and gets its own log group
   (`/video/dlq-marker`).

## Worker ASG — queue-depth scaling with scale-to-zero

- **Instance type**: `c7i.large` (compute-optimized, ~4 GB RAM) — replaces the
  OOM-prone `t3.micro`. Compute-optimized fits the CPU/memory profile of FFmpeg;
  combined with the `720p` downscale this removes the memory blowup.
- **ASG**: `minCapacity = 0`, `maxCapacity = 4`, `desiredCapacity = 0` at
  deploy. Launch template uses `video-worker-role`, `worker-sg`, private
  subnets, no public IP.
- **Scaling signal — one scheme (step scaling), two disjoint alarms.** Target
  tracking is *not* used: it maintains capacity for a target and will not take an
  ASG to 0, which conflicts with the scale-to-zero requirement. Instead a single
  **step-scaling** scheme owns all capacity changes, driven by two CloudWatch
  alarms with non-overlapping responsibilities:
  - **Scale-out (owns 0→N):** alarm `video-queue-backlog` on
    `ApproximateNumberOfMessagesVisible` for `VideoQueue`, statistic `Sum`,
    period **60 s**, `evaluationPeriods = 1`, `GreaterThanOrEqualToThreshold`
    `1`. Its step-scaling policy sets desired capacity by backlog band:
    `≥1 msg → 1`, `≥20 → 2`, `≥50 → 4` instances (capped at `maxCapacity=4`).
    This is the one policy that lifts the ASG off zero.
  - **Scale-in to zero (owns N→0):** alarm `video-queue-idle` on a metric-math
    expression `m_visible + m_not_visible` (both from `VideoQueue`), statistic
    `Sum`, period **60 s**, `evaluationPeriods = 15` (15 min sustained),
    `LessThanOrEqualToThreshold` `0`. Its step-scaling policy sets desired
    capacity to **0**. The `not_visible` term ensures we never scale in while a
    message is in flight (being transcoded).

  Because both alarms adjust the *same* ASG through step policies (not a mix of
  target-tracking + step), they cannot fight: a non-empty queue keeps desired ≥1,
  and only a fully-drained queue for a sustained window returns it to 0.
  Scale-to-zero when empty is the Cost/Sustainability target from the
  Well-Architected table.
- **Graceful drain — ASG termination lifecycle hook (not instance-protection
  toggling).** A `autoscaling.LifecycleHook` on the worker ASG's
  `autoscaling:EC2_INSTANCE_TERMINATING` transition (heartbeat 900 s, default
  result `CONTINUE`) holds an instance in `Terminating:Wait` while it finishes
  the in-flight job. The worker's SIGTERM handler finishes (or cleanly aborts)
  the current transcode, then calls `CompleteLifecycleAction` to release the
  hook; while working it periodically calls `RecordLifecycleActionHeartbeat` so
  the hook doesn't time out. This is why `video-worker-role` grants exactly
  `autoscaling:RecordLifecycleActionHeartbeat` + `CompleteLifecycleAction` on the
  ASG ARN (and no `SetInstanceProtection`). The 15-min visibility timeout is the
  backstop: if drain somehow fails, the message simply reappears for another
  worker rather than being lost.

## `video_id` — single correlation id, derived once

Closes the "web vs worker derive `video_id` differently → stuck on `Queued`"
flag. The id is derived **exactly once, in the web tier at upload**, and
**passed through** every downstream hop so nothing recomputes it:

1. Web tier generates `video_id = uuid4().hex` at `POST /videos` (a UUID, not a
   filename-derived slug — eliminates the space/`+` divergence entirely).
2. The raw object is stored under a key that **embeds the id**:
   `input/{video_id}/{safe_filename}`, and the id is **also** written to S3
   object metadata (`x-amz-meta-video-id`). `safe_filename` is the
   client-supplied `original_filename` after **sanitization** (Finding 7):
   stripped of path separators and control characters, Unicode-normalized,
   reduced to a safe charset (`[A-Za-z0-9._-]`, other runs collapsed to `_`), and
   clamped to 200 bytes while preserving the extension; an empty result falls
   back to `video`. The unsanitized `original_filename` is still stored verbatim
   as a DynamoDB attribute for display. **Correlation never depends on the
   filename** — the worker parses the hex `video_id` from the key *prefix*
   (`input/<video_id>/`), so a hostile or odd filename cannot affect routing; the
   sanitization only keeps control characters and traversal-ish sequences out of
   S3 keys and logs.
3. The web tier writes the `Queued` DynamoDB row keyed by that same `video_id`.
4. S3's event notification carries the object key; the worker parses `video_id`
   from the **key prefix** (`input/<video_id>/...`) — it never re-derives from
   the filename. The metadata copy is the cross-check.
5. The worker writes HLS to `output/{video_id}/playlist.m3u8` (+ `.ts` segments)
   and updates the DynamoDB row under the identical `video_id`.

**Control-message guard (Finding 3).** When the S3→SQS notification is first
configured, S3 posts a control message
`{"Service":"Amazon S3","Event":"s3:TestEvent"}` that has **no**
`Records[].s3.object.key`; redeliveries and future notification types can produce
similarly shapeless bodies. Before parsing `video_id`, the worker loop **inspects
the body**: if it is not valid JSON, or has `"Event": "s3:TestEvent"`, or lacks a
`Records[0].s3.object.key` matching `input/<video_id>/…`, the worker **logs it at
info and calls `delete_message` without processing** — it never lets such a body
fail-parse and burn its way to `maxReceiveCount`. The DLQ-marker Lambda applies
the **same** guard symmetrically: a DLQ body with no parseable
`input/<video_id>/…` key is logged and dropped (deleted) rather than attempting
an `UpdateItem` for a nonexistent `video_id` (see **SQS + DLQ** and
**Testability**).

One id threads S3 Input ↔ SQS message ↔ DynamoDB item ↔ S3 Output ↔ the signed
playback URL. Both sides are guaranteed to agree.

## FFmpeg sourcing + downscale

- **Sourcing**: do **not** pull from the flaky third-party host at boot. The CDK
  `DataStack` provisions the `video-artifacts` bucket; a static FFmpeg build is
  uploaded to it via `BucketDeployment` at deploy time, so the artifact is
  version-pinned and served from our own S3 over the gateway endpoint. The
  worker's user-data downloads `ffmpeg`/`ffprobe` from
  `s3://video-artifacts-.../ffmpeg/` to `/usr/local/bin` on first boot.
- **Exact pin + how the binary reaches the asset dir (Finding 5).**
  `BucketDeployment` needs the binary present in a local asset directory at
  `cdk synth` time; it does not fetch anything itself. Mechanism:
  - **Pinned release:** `BtbN/FFmpeg-Builds`, release tag
    **`autobuild-2024-11-01-14-16`**, asset
    **`ffmpeg-n7.1-latest-linux64-gpl-7.1.tar.xz`** (`linux64-gpl` for x86_64 —
    the `libx264` + HLS build verified in the Gotchas). The tag + the asset's
    **`SHA256`** are committed to the repo in `iac/assets/ffmpeg/FFMPEG.lock`.
  - **Prebuild script** (`iac/scripts/fetch-ffmpeg.sh`, run before `cdk synth`,
    also invoked by CI): `curl -L` the pinned tarball, verify it against the
    committed `SHA256` (fail hard on mismatch), extract only `ffmpeg` and
    `ffprobe` into `iac/assets/ffmpeg/bin/`. That `bin/` dir is **gitignored**
    (binaries are regenerated deterministically from the lock file, not
    vendored), and `BucketDeployment(sources=[Source.asset('assets/ffmpeg/bin')])`
    points at it. Synth fails loudly if the dir is empty, so a missing prebuild
    can't silently ship a worker with no FFmpeg.
    - *Alternative considered:* vendoring the extracted binaries directly via
      **Git LFS** at a pinned path (no prebuild step, but ~80 MB in LFS and a
      binary in source control). Rejected in favor of the lock-file + fetch
      script, which keeps source control text-only and makes the pin auditable
      as a diff. Either satisfies the "no flaky third-party host at boot" goal;
      the fetch happens once at build time against the pinned, checksummed URL,
      never at instance launch.
  - **`BucketDeployment` sizing:** the `ffmpeg`+`ffprobe` payload (~80–100 MB
    extracted) exceeds the default Lambda-backed deployer limits, so set
    `memory_limit=1024` (MiB) and `ephemeral_storage_size=Size.gibibytes(2)` on
    the `BucketDeployment` so the asset-copy handler has room to stage and unzip.
  - Chosen over baking a custom AMI (EC2 Image Builder) because the S3-artifact
    approach needs no AMI pipeline, keeps the build reproducible, and the pin
    lives in one place (`FFMPEG.lock`). If cold-start download time matters
    later, the same pinned artifact can be baked into an AMI without changing the
    worker code.
- **Downscale command** (the OOM fix — caps output resolution and uses
  HLS-safe codecs):

  ```python
  cmd = ['ffmpeg', '-i', local_in,
         '-vf', 'scale=-2:720',                       # 720p, aspect preserved
         '-c:v', 'libx264', '-profile:v', 'baseline', '-level', '3.1',
         '-c:a', 'aac',                               # HLS-compatible audio
         '-f', 'hls',
         '-hls_time', '6', '-hls_playlist_type', 'vod',
         f'{out_dir}/playlist.m3u8']
  ```

  **H.264 level** is **`3.1`**, not `3.0`: 1280×720 exceeds the macroblock/frame
  limits of baseline level 3.0 (capped near 720×576), so declaring `3.0` on a
  720p encode produces a non-conformant stream and defeats the device-compat
  reason for pinning baseline in the first place. Level 3.1 covers 1280×720 up to
  30 fps, which matches the `scale=-2:720` output. (If strict level-3.0 device
  support were ever required, the scale would drop to `-2:480` instead; the spec
  mandates 720p, so 3.1 is the correct pairing.)

## CloudFront + signed-cookie playback (private Output bucket)

> **Why one CloudFront domain (SPA + `/api/*` + `/media/*`):** the browser runs the
> S3-served `app.js`, which calls `/api/*` and loads `/media/*` on the *same origin* so
> the signed cookies attach automatically (no CORS, no cross-domain cookie problem). See
> [[learning-plan/10-architecting/serverless-spa-api-wiring|SPA ↔ API wiring]] for the
> general pattern (this app is its single-domain / signed-cookie example).

Closes the playback flag the clean way and follows the builder-security policy
(storage never internet-exposed; private-bucket playback via signed credentials).

> **On "signed URLs" vs signed cookies (Finding 4).** The settled decision and
> the spec flag both say "CloudFront + signed URLs." This design meets the
> underlying requirement in full — private Output bucket (Block Public Access
> ON), CloudFront-gated playback, no public S3, per-video-scoped signed
> credentials — but uses CloudFront **signed cookies** for *production* playback
> rather than per-object signed URLs, because HLS fans out to one `.m3u8` plus
> many `.ts` segments and signing each URL would force a playlist rewrite on
> every play. Signed cookies authorize the whole `/media/{video_id}/*` prefix
> with one signing operation and no rewrite. **Signed URLs are still used in
> local dev** (see Local-dev), so the signing mechanism the decision names is
> exercised; only the production delivery vehicle differs. This is a deliberate,
> documented choice — flagged here for the user to confirm the cookie vehicle is
> acceptable given the literal wording.

**One distribution, one domain, three origins.** A single CloudFront
distribution is the only public HTTPS surface and resolves both the mixed-content
problem and the cross-domain-cookie problem at once:

| Path pattern | Origin | Behavior |
| --- | --- | --- |
| `/media/*` | Output bucket via **OAC** | **requires signed cookies** (trusted key group); redirect-to-HTTPS |
| `/api/*` | an **API Gateway HTTP API over HTTPS** (`HttpOrigin`, `protocol_policy=HTTPS_ONLY`), which forwards via a **VPC Link** to the **internal ALB** | no CloudFront caching (`CachePolicy.CACHING_DISABLED`), `ALL_VIEWER_EXCEPT_HOST_HEADER` origin-request policy (an API Gateway custom origin needs its own `execute-api` Host); this is where the API lives |
| default (`/*`) | Frontend (site) bucket via **OAC** | the SPA static assets; no signing |

Because the SPA, the API, and the media all share the **one CloudFront domain**,
a `Set-Cookie` returned by the API response (proxied through CloudFront from the
API Gateway → VPC Link → ALB path) is scoped to that same host, so the browser
**does** attach the CloudFront signed cookies to the subsequent `/media/*`
segment requests. (This is the specific thing that failed when the API was on the
raw ALB domain and media on a separate CloudFront domain.) The whole
CloudFront→origin hop is HTTPS: CloudFront terminates on the API Gateway
endpoint's AWS-managed cert, so the `Set-Cookie` never crosses the internet in
plaintext.

- The **Output bucket stays private** — S3 **Block Public Access ON** (all four
  settings), no bucket ACLs, no public policy. CloudFront reaches it through an
  **Origin Access Control (OAC)**; the bucket policy grants `s3:GetObject` only
  to the distribution's service principal, conditioned on `aws:SourceArn =` the
  distribution ARN. The site bucket is fronted the same way (OAC, private).

**Signed cookies, not per-URL signing, for the HLS fan-out.** HLS pulls one
`.m3u8` plus many `.ts` segments; signing each would mean rewriting the playlist.
Instead `GET /videos/{video_id}/play-url`, when status is `Ready`, returns the
playlist URL (`https://<cf-domain>/media/{video_id}/playlist.m3u8`) **and sets
three CloudFront signed cookies** (`CloudFront-Policy`, `CloudFront-Signature`,
`CloudFront-Key-Pair-Id`) via `Set-Cookie` on the API response. The cookie
policy is a **custom policy scoped to `Resource: https://<cf-domain>/media/{video_id}/*`**
so a viewer is authorized only for the one video, and `Path=/media/{video_id}/`,
`Secure`, `HttpOnly`, `SameSite=None` (cross-path XHR from the SPA, same site).
`hls.js` then fetches the playlist and every segment under `/media/{video_id}/…`
and the browser attaches the cookies automatically — no m3u8 rewrite, one signing
operation per play. These media requests are **same-origin** (the SPA, the API,
and `/media/*` all live under the one CloudFront domain), so the scoped-`Path`
cookies attach to `hls.js`'s XHRs with no extra configuration — **no
`withCredentials`/`xhrSetup` is needed**. (If media were ever served from a
different origin, `hls.js` would require `xhrSetup` setting `xhr.withCredentials =
true`; that is explicitly not our case.)

**Signing-key pair lifecycle (explicit, reproducible):**
1. Generate an RSA-2048 key pair **once, out of band** (documented in the repo
   README): `openssl genrsa -out cf_private.pem 2048` and
   `openssl rsa -pubout -in cf_private.pem -out cf_public.pem`.
2. The **public** PEM (`cf_public.pem`) is committed to the repo and passed to
   `cloudfront.PublicKey(..., encoded_key=<pem text>)` at synth; that public key
   is added to a `cloudfront.KeyGroup`, which the `/media/*` behavior trusts. No
   secret material is in the repo — a public key is not sensitive.
3. The **private** PEM is loaded into a Secrets Manager secret
   (`video/cf-signing-key`) by a **one-time, out-of-band**
   `aws secretsmanager put-secret-value` run by the operator after deploy (the
   README gives the exact command). It is never in source, in the AMI, or in the
   SPA. The CDK creates the (empty-at-synth) secret with
   `removalPolicy=DESTROY` so teardown removes it; the web role's
   `secretsmanager:GetSecretValue` is scoped to this secret's ARN.
   (Rationale for out-of-band vs an in-stack custom resource: it keeps the
   private key off the CloudFormation event/template surface entirely; the
   trade-off is one documented manual step, acceptable for a lab.)

**Signing-key caching (Finding 6).** The web process reads
`secretsmanager:GetSecretValue` for the private PEM **once at startup** (in a
FastAPI lifespan/startup hook), parses it into an in-memory
`rsa.RSAPrivateKey`, and reuses that object for every `play-url` signing
operation — it is **not** read per request. A simple TTL-refresh (re-fetch if the
cached key is older than, say, 12 h) covers an operator rotating the secret
without a redeploy; on a `GetSecretValue` failure at startup the process fails
its health check (so the ALB pulls it out of service) rather than serving
unsignable `play-url`s. This keeps Secrets Manager off the per-playback latency
and cost path while the interface endpoint keeps the one startup read on the AWS
network.

**TTL vs long sessions:** the cookie policy's expiry is set to
**6 hours** — comfortably longer than any expected lab clip, so a VOD session
never expires mid-watch. Combined with `hls_playlist_type=vod` (the playlist is
fetched once), the common case needs no re-auth. If a session ever outlives the
cookie, segment fetches return `403`; the SPA treats a `403` on a segment as
"re-call `play-url`" to refresh the cookies and resume. This behavior is stated
so the implementer doesn't guess.

- The SPA never holds AWS credentials and never talks to S3 directly; it calls
  the FastAPI JSON API (through CloudFront) and loads media only through
  CloudFront signed cookies.

## S3 lifecycle

Closes the Cost/Sustainability flag:

- **Input bucket**: lifecycle rule transitions raw objects under `input/` to
  **S3 Standard-IA after 30 days** and **Glacier Flexible Retrieval after 90
  days** — raw source is cold once transcoded. (A shorter window risks
  re-transcode needs; 30/90 is the conservative default.) An expiry of
  incomplete multipart uploads after 7 days keeps stray parts from accruing.
- **Output bucket**: no aggressive tiering (HLS is the hot, served artifact), but
  incomplete-multipart cleanup after 7 days.

## DynamoDB — key-based listing, no scan

Closes the "full `scan` every 3 s" anti-pattern.

- Table **`VideoCatalog`**, PK `video_id` (String), On-Demand (PAY_PER_REQUEST) —
  unchanged primary key, since single-item lookups by id remain the dominant
  access.
- Add a **GSI `by-status-created`**: partition key `gsi_pk` (a constant bucket
  value, e.g. the literal `"VIDEO"`), sort key `created_at` (ISO-8601 string).
  The listing endpoint runs a **`Query`** on this GSI (`gsi_pk = "VIDEO"`,
  `ScanIndexForward = false`, `Limit = 100`) to return newest-first without ever
  scanning the table. Projection: `ALL` (the grid needs status + title +
  timestamps). Every item the web tier writes sets `gsi_pk = "VIDEO"` and
  `created_at`.
  - A single-partition GSI is acceptable at this scale (one small catalog); if it
    ever grew hot, the partition key would shard by date (`VIDEO#yyyy-mm-dd`).
    Noted, not built.

## FastAPI web tier

A self-built FastAPI JSON API (no inline HTML — the SPA is separate), run by
`gunicorn` with `uvicorn` workers on **port 8000**, bound to the instance's
private interface and fronted by the ALB. It runs as an **unprivileged**
systemd service (`User=appuser`), never root, never binding port 80 directly —
closing the "runs as root" and "Flask dev server" flags together. All AWS calls
use `video-web-role` (no credentials in code).

Routes:

- `POST /videos` — accept the multipart upload. Generate `video_id = uuid4().hex`,
  then **stream** the body to Input under `input/{video_id}/{safe_filename}` via
  **`s3.upload_fileobj(file.file, INPUT_BUCKET, key, ExtraArgs={"Metadata": {"video-id": video_id}, "ContentType": file.content_type})`**
  — not `put_object` (Finding 2). `upload_fileobj` is boto3's managed-transfer
  API: it reads from FastAPI's `UploadFile.file` (a `SpooledTemporaryFile` that
  spills to a temp file past its in-memory threshold) and performs an automatic
  **multipart** upload in bounded-size chunks, so a multi-hundred-MB-to-2-GB body
  never has to be read whole into RAM and the transfer is resumable chunk-by-chunk
  — the point the tutorial's `upload_fileobj` got right and a single-PUT
  `put_object` would regress on a 2 GB-RAM `t3.small`. After the upload, call
  **`update_item`** (not `put_item`) writing status `Queued`, `gsi_pk="VIDEO"`,
  `created_at`, `title`, `original_filename`. Returns
  `{video_id, status: "Queued"}` immediately. (Consistent `update_item` closes
  the "`put_item` overwrites the row" flag.) The `x-amz-meta-video-id` metadata
  rides along via `ExtraArgs["Metadata"]`.
- `GET /videos` — list via the GSI `Query` (above). No scan.
- `GET /videos/{video_id}` — `get_item` by id for status polling. A missing item
  is signalled by **`"Item"` not in the response** (DynamoDB returns an empty
  result, *not* `ResourceNotFoundException`), which maps to **`404`**;
  `ResourceNotFoundException` is reserved for a missing table/index (a
  misconfiguration → `500`).
- `GET /videos/{video_id}/play-url` — if status is `Ready`, return the playlist
  URL and set the three CloudFront signed cookies (custom policy scoped to
  `/media/{video_id}/*`, 6 h expiry) on the response; else return the current
  status (`409 {status}`) so the SPA shows `Queued`/`Processing`/`Failed`
  instead of a broken player. This route `get_item`s the row first and applies
  the same absent-item → `404` branch as `GET /videos/{video_id}`.
- `DELETE /videos/{video_id}` — `delete_item`, then `ListObjectsV2` +
  `DeleteObjects` to clear the `input/{video_id}/` and `output/{video_id}/` S3
  prefixes (needs the web role's `s3:ListBucket`/`s3:DeleteObject` grants added
  for Finding 2).
- `GET /health` — shallow 200 for the ALB target group.

**Exception handling (concrete, per operation — closes the bare-`except` flag):**

| Operation | Failure | Recoverable? | Caller sees | Logged |
| --- | --- | --- | --- | --- |
| Upload — bad content-type / too large | validation | fatal to request | `400` + reason | info |
| `s3.upload_fileobj` (managed multipart) | `S3UploadFailedError` / `ClientError` (`AccessDenied`, throttling) | throttling→boto3 retries internally; else fatal | `502` | error w/ `video_id` |
| `dynamodb.update_item` after a successful S3 upload | `ClientError` | fatal; **compensating cleanup** (see below) | `502` | error w/ `video_id`, key |
| `get_item` — item absent (`"Item"` not in response) | unknown `video_id` | fatal to request | `404` | info |
| `get_item` / `Query` — `ResourceNotFoundException` (table/index missing) | infra misconfig | fatal | `500` | error |
| `get_item` / `Query` — other `ClientError` (throttle, access) | throttle→retry; else fatal | `502` | error |
| `play-url` when not `Ready` | not an error | — | `409` + `{status}` | debug |
| Secrets Manager read for signing key | `ClientError` | fatal | `500` | error (never log the key) |

No bare `except`. `botocore.exceptions.ClientError` is matched on
`error.response["Error"]["Code"]` so `AccessDenied` is never masked as `404`
(the exact bug from the Gotchas). A FastAPI exception handler maps unexpected
errors to `500` and logs a stack trace with the `video_id` correlation id.

**Orphan handling — compensating cleanup, not lifecycle (Finding 3).** If the S3
upload succeeds but the subsequent `update_item` fails, the object is an orphan:
raw bytes in Input with no catalog row and (because the S3→SQS notification has
already fired on the object-create) possibly a queued job whose `video_id` the
worker will find has no DynamoDB item. The Input lifecycle rule only **tiers**
`input/` objects to IA/Glacier — it has **no expiration**, so an orphan is *not*
auto-deleted; it would persist forever in colder storage. The route therefore
performs an explicit **compensating delete**: in the `except` branch it issues a
best-effort `s3.delete_object(INPUT_BUCKET, key)` for the just-uploaded key
(using the web role's `s3:DeleteObject` on `input/*`) before returning `502`. If
that compensating delete also fails, it is logged at `error` with the key for
manual cleanup — the request still returns `502`, and the worker's
control/absent-item guards (below) keep the stray queued message harmless (a
`get_item` miss → no `Ready` written; the message dead-letters and the
DLQ-marker's "no row to update" path logs-and-drops it). There is no claim that
lifecycle sweeps orphans, because it does not.

**Input validation at the trust boundary:** `POST /videos` requires a file part;
content-type must start with `video/` (reject otherwise, `400`); size capped at
a configurable `MAX_UPLOAD_BYTES` (default 2 GB) — enforced via the
`Content-Length` header up front and again by aborting the stream if the running
byte count exceeds the cap during `upload_fileobj`, so a lying header can't slip
a larger body through. `original_filename` is **sanitized** before it is
interpolated into the S3 key (Finding 7): required, treated as untrusted,
Unicode-normalized, control characters and path separators stripped, reduced to
`[A-Za-z0-9._-]` (other runs → `_`), and clamped to 200 bytes keeping the
extension; empty-after-sanitize → `video`. `title` optional, length-clamped and
stored as-is (never interpolated into a query — DynamoDB is parameterized by the
SDK). `video_id` in path params is validated against `^[0-9a-f]{32}$` before any
S3/DynamoDB call.

**Invariant ownership:** the web tier is the sole writer of `video_id` and the
`Queued`/initial row (upload-time invariant); the worker is the sole writer of
`Processing`/`Ready`/`Failed` and of `output/` objects (processing-time
invariant). Neither crosses into the other's writes, which is why the IAM roles
can be split cleanly. Idempotency is owned by the worker: before transcoding it
`get_item`s and **skips if already `Ready`** (the at-least-once backstop),
making redelivered messages harmless even with the long visibility timeout.

## Local-dev approach

The SPA and FastAPI must run locally against the **deployed backend resources**
(the message-3 "test locally before deploying" requirement), using the
developer's own AWS credentials:

- **Runtime `config.json`**: the SPA **always fetches `config.json`** at startup
  (fetched, not compiled in) holding `{ apiBaseUrl, region, playbackMode }`. In
  AWS, CDK's `BucketDeployment` writes `config.json` with `apiBaseUrl: "/api"` —
  a **same-origin relative path**, since the API is reached through the same
  CloudFront domain as the SPA, which is also what makes the signed cookies work
  — and `playbackMode: "cookie"`.
- **Local config convention (Finding 8):** the SPA never branches on hostname.
  Instead the repo ships a checked-in `config.local.json`
  (`apiBaseUrl: "http://127.0.0.1:8000"`, `playbackMode: "signed-url"`), and the
  documented local-dev step is **`cp spa/config.local.json spa/config.json`**
  before serving the SPA. `spa/config.json` is **gitignored** so the deployed
  value is only ever produced by `BucketDeployment` and a developer's local copy
  never gets committed. One loader path, two config files, an explicit copy — no
  runtime hostname sniffing.
- **Local FastAPI**: run `uvicorn main:app --host 127.0.0.1 --port 8000`
  (loopback bind — never `0.0.0.0` for local dev, per builder-security). It reads
  resource names from env (`INPUT_BUCKET`, `OUTPUT_BUCKET`, `TABLE_NAME`,
  `ARTIFACT_BUCKET`, `CF_KEY_SECRET_ARN`, `CF_DOMAIN`) and uses the developer's
  ambient AWS credentials (`~/.aws`) via `boto3` — the **same deployed** S3
  buckets, DynamoDB table, and CloudFront distribution. No MinIO/DynamoDB-local
  needed; the backend is real, only the process is local.
- **Local SPA**: served by any static server bound to loopback
  (`python -m http.server --bind 127.0.0.1 5500`); it calls the local FastAPI,
  which signs CloudFront URLs the same way as in production, so playback is
  exercised end-to-end locally.
- CORS on the FastAPI app allows the CloudFront origin and the two localhost dev
  origins explicitly (not `*`), with `allow_credentials=True` so the signed-cookie
  `Set-Cookie`/XHR flow works in the deployed environment. In production the SPA
  and API are same-origin (both under the CloudFront domain), so CORS matters
  only for local dev.
- **Local playback uses signed URLs, not cookies (Finding 7).** Signed *cookies*
  are set for the CloudFront domain; a browser pointed at `http://127.0.0.1:5500`
  will not attach a CloudFront-domain cookie to anything — and "just follow the
  playlist URL" fails identically, because that request also reaches CloudFront
  with no cookie and returns `403`. So in local mode (`playbackMode:
  "signed-url"` in `config.local.json`) the local API's `play-url` returns a
  **CloudFront signed URL** for the playlist against the deployed distribution,
  and — because HLS fans out to many segments — the local playlist is served
  through a tiny **signed-URL rewrite**: the API fetches the `.m3u8`, rewrites
  each segment line to its own signed URL, and returns the rewritten playlist so
  `hls.js` plays it with no cookie. This is a **local-dev-only** code path gated
  by `playbackMode`; production stays on signed cookies (no rewrite). The
  signing *logic* (same `rsa` key, same per-resource policy, same TTL) is
  therefore exercised locally end-to-end; only the delivery vehicle
  (URL vs cookie) differs, and that difference is one documented branch.

## Clean teardown + outputs

Single `cdk destroy` (reverse stack order) removes everything — the message-1
requirement, mirroring clear-thinking-app:

- All four S3 buckets: `removalPolicy=DESTROY` + `autoDeleteObjects=True`.
- `VideoCatalog`: `removalPolicy=DESTROY`.
- `VideoQueue` + DLQ: removed with the stack (no retention).
- **Explicit CloudWatch log groups** for the web service, the worker, and the
  DLQ-consumer Lambda (`/video/web`, `/video/worker`, `/video/dlq-marker`), each
  `retention=TWO_WEEKS`, `removalPolicy=DESTROY`, so no log groups linger after
  destroy. The SSM agent and ASG lifecycle logs route here.
- `video/cf-signing-key` Secrets Manager secret: `removalPolicy=DESTROY`.
- ASGs set `desiredCapacity=0`/scale-in so no instances block deletion.

`CfnOutput`s: `InputBucketName`, `OutputBucketName`, `SiteBucketName`,
`ArtifactBucketName`, `TableName`, `QueueUrl`, `DlqUrl`, `AlbDnsName`,
`CloudFrontDomain` (the single public domain; the SPA, `/api/*`, and `/media/*`
all live here — there is no separate `ApiBaseUrl`, it is `CloudFrontDomain/api`),
`CfKeyGroupId`, `CfKeySecretArn`.

## Testability

- **Unit (web tier)**: `video_id` generation + key/metadata construction; the GSI
  `Query` builder; signed-URL/cookie generation (assert TTL + scoped path);
  exception mapping (each `ClientError` code → the right HTTP status); input
  validation (content-type, size, path-param regex). boto3 is stubbed with
  `botocore.stub.Stubber`.
- **Unit (worker)**: `video_id` extraction from an S3-event key; idempotency
  skip when status is already `Ready`; FFmpeg argv assembly (`scale=-2:720`,
  baseline/AAC); `Failed`-on-nonzero-exit path (worker-survives case). FFmpeg
  itself is shelled out, so the argv is asserted and the subprocess mocked.
- **Unit (DLQ-marker Lambda)**: `video_id` parse from a DLQ message body →
  `UpdateItem status=Failed` (boto3 stubbed); malformed message → logged and
  dropped, no crash.
- **Integration**: deploy to the lab account and run the pipeline end-to-end
  (upload → `Queued` → worker → `Ready` → signed-cookie playback through
  CloudFront). Two failure tests: (a) a FFmpeg-rejectable input → worker writes
  `Failed` itself and deletes the message; (b) a **worker-kill** poison pill
  (e.g. an input that OOMs, or a worker that `sys.exit`s before delete) → the
  message is redelivered to `maxReceiveCount=3`, lands in `VideoQueue-DLQ`, and
  the **DLQ-consumer Lambda** writes `status=Failed` — asserting the flag is
  closed for the crash path, not just the graceful one. The scale-to-zero
  behavior is observed via the ASG desired-capacity dropping to 0 after the
  queue drains for the idle window.
- Design choices that aid testing: pure functions for id/key/argv/signing;
  resource names injected by env (no hardcoding) so local and deployed runs use
  the identical code path.

## Responses to design-review findings — round 1

Revision against the first `.agents/tasks/design-review.md` (verdict
CHANGES_REQUESTED: 1 HIGH, 6 MEDIUM, 3 NIT). All ten findings are **addressed** —
none backlogged.

1. **HIGH — `Failed` on the OOM/retry-exhaustion path had no implementer.**
   Addressed. Added a **DLQ-consumer Lambda** (`video-dlq-failed-marker`,
   triggered by `VideoQueue-DLQ`) that parses `video_id` and `UpdateItem`s
   `status=Failed`, with `dynamodb:UpdateItem` on `table/VideoCatalog` only. It
   is in `AppStack`, the teardown list, and has its own log group. The worker
   still writes `Failed` on the survive-but-nonzero-exit case; the Lambda owns
   the crash/OOM case (the only path that survives a killed worker). The
   integration test now has a distinct worker-kill case asserting
   DLQ→Lambda→`Failed`. (See **SQS + DLQ**, **IAM**, **CDK stack decomposition**,
   **Testability**.)
2. **MEDIUM — web role couldn't perform its own `DELETE /videos` cleanup.**
   Addressed. Granted `video-web-role` prefix-scoped `s3:ListBucket` and
   `s3:DeleteObject` on both Input and Output buckets, and called out that the
   web tier deleting `output/` objects does not violate the "worker is sole
   *writer* of `output/`" invariant (deletion ≠ creation). (See **IAM**,
   **FastAPI DELETE route**.)
3. **MEDIUM — ALB HTTPS cert/domain unspecified → mixed content.** Addressed by
   the **single-CloudFront** option: the API is a second origin (`/api/*` → ALB)
   on the one CloudFront distribution, so the browser only ever speaks HTTPS to
   the CloudFront domain and no ACM cert on the `*.elb.amazonaws.com` name is
   needed. `alb-sg` inbound is restricted to the CloudFront→ALB path only
   (refined in round 2 to a VPC origin and in round 3 to the concrete
   private-subnet-CIDR rule — see round-3 response 1). `ApiBaseUrl` is dropped in
   favor of the same-origin `/api`. (See **VPC security groups**, **CloudFront**,
   **Local-dev**, **outputs**.)
4. **MEDIUM — graceful drain needed an ungranted action.** Addressed by choosing
   an **ASG termination lifecycle hook** over instance-protection toggling;
   granted the worker role exactly `autoscaling:RecordLifecycleActionHeartbeat` +
   `CompleteLifecycleAction` on the ASG. (See **Worker ASG → Graceful drain**,
   **IAM**.)
5. **MEDIUM — conflicting scaling policies; target tracking can't reach 0.**
   Addressed by dropping target tracking entirely and using **one step-scaling
   scheme** with two disjoint alarms: `video-queue-backlog` owns 0→N, and
   `video-queue-idle` (visible+not-visible = 0 for 15×60 s) owns N→0. Exact
   metric/period/evaluation/threshold parameters specified. (See **Worker ASG →
   Scaling signal**.)
6. **MEDIUM — signed cookies wouldn't cross the ALB→CloudFront domain boundary.**
   Addressed by Finding 3's single-domain choice: API and media share one
   CloudFront host, so the API's `Set-Cookie` is attached to `/media/*` requests.
   Cookie `Domain`/`Path`/attributes and the per-video scoped policy are spelled
   out. (See **CloudFront + signed-cookie playback**.)
7. **MEDIUM — CloudFront key-pair lifecycle unspecified.** Addressed. Documented
   out-of-band RSA-2048 generation, public PEM committed and passed to
   `cloudfront.PublicKey` at synth, private PEM loaded into Secrets Manager via a
   one-time `put-secret-value` (not in source), secret `removalPolicy=DESTROY`.
   (See **CloudFront → Signing-key pair lifecycle**.)
8. **NIT — no Secrets Manager VPC endpoint.** Addressed. Added a
   `secretsmanager` interface endpoint so the signing-key read stays on the AWS
   network. (See **VPC endpoints**.)
9. **NIT — TypeScript construct syntax.** Addressed. Replaced with the Python
   `bucket.add_event_notification(s3.EventType.OBJECT_CREATED, s3n.SqsDestination(queue), …)`.
   (See **SQS + DLQ**.)
10. **NIT — playlist TTL vs long sessions.** Addressed. Cookie expiry set to 6 h
    (longer than any expected clip) with `hls_playlist_type=vod`, and the SPA
    re-calls `play-url` on a segment `403` to refresh. (See **CloudFront → TTL vs
    long sessions**.)

## Responses to design-review findings — round 2

Revision against the second `.agents/tasks/design-review.md` (verdict
CHANGES_REQUESTED: 6 MEDIUM, 5 NIT). All eleven findings are **addressed** — none
backlogged, none ignored.

1. **MEDIUM — IAM `s3:prefix` condition used `${video_id}`, not a valid IAM
   variable.** Addressed. The `s3:ListBucket` grant now uses a literal
   `StringLike s3:prefix` of `["input/*"]` on the Input bucket and `["output/*"]`
   on the Output bucket; added a note that IAM has no `${video_id}` variable so
   templating a per-request id can't work. `s3:DeleteObject` already used the
   correct `input/*` / `output/*` literals. (See **IAM → Web-tier role** and the
   note after the table.)
2. **MEDIUM — H.264 baseline `-level 3.0` invalid for 720p.** Addressed. Changed
   to **`-level 3.1`** (covers 1280×720 ≤ 30 fps) and added a paragraph explaining
   the macroblock-limit reason and the `-2:480`-if-3.0-required fallback. (See
   **FFmpeg sourcing + downscale**.)
3. **MEDIUM — worker didn't handle `s3:TestEvent`/non-`ObjectCreated` bodies.**
   Addressed. Added a **control-message guard**: the worker inspects each body
   and `delete_message`s (log at info, no processing) any body that isn't valid
   JSON, is `s3:TestEvent`, or lacks a parseable `input/<video_id>/…` key — so a
   shapeless body never burns to `maxReceiveCount`. The DLQ-marker Lambda applies
   the same guard symmetrically. (See **`video_id` → Control-message guard**,
   **SQS + DLQ**, **Testability**.)
4. **MEDIUM — web-tier ASG type/capacity unspecified.** Addressed. Web ASG is
   **`t3.small`**, `minCapacity=1, maxCapacity=2, desiredCapacity=1`, with a
   single **CPU target-tracking policy at 60%** (never scales to zero because the
   ALB needs a live target). (See **VPC layout → Web-tier ASG sizing**.)
5. **MEDIUM — how the pinned FFmpeg binary enters `BucketDeployment` was
   unspecified.** Addressed. Pinned to `BtbN/FFmpeg-Builds` tag
   `autobuild-2024-11-01-14-16` (asset `…n7.1…linux64-gpl-7.1.tar.xz`) with tag +
   `SHA256` committed in `iac/assets/ffmpeg/FFMPEG.lock`; a prebuild script
   (`fetch-ffmpeg.sh`) `curl -L`s + checksum-verifies + extracts into a gitignored
   `assets/ffmpeg/bin/` that `BucketDeployment` points at, with synth failing if
   it's empty. Git-LFS vendoring noted as the rejected alternative. Set
   `memory_limit=1024`, `ephemeral_storage_size=2 GiB` on the deployer for the
   ~80–100 MB payload. (See **FFmpeg sourcing → Exact pin**.)
6. **MEDIUM — CloudFront→ALB origin hop was plaintext HTTP over the public
   internet.** Addressed by switching to a **CloudFront VPC origin** to an
   **internal** ALB (no public IP, private subnets): the edge→ALB hop carrying the
   signed-cookie `Set-Cookie` and upload bytes now stays on AWS's private network
   rather than traversing the public internet. `alb-sg` inbound is scoped to the
   CloudFront→ALB path (round 3 makes this the concrete private-subnet-CIDR rule —
   round-3 response 1). The internet-facing-ALB-with-ACM alternative is
   recorded as considered-and-rejected. (See **VPC layout**, **security groups →
   `alb-sg`**, **CloudFront** table.)
7. **NIT — local playback validation was internally inconsistent.** Addressed.
   Local mode (`playbackMode: "signed-url"`) has the local API return a
   **CloudFront signed URL** and serve a **signed-URL-rewritten playlist** so
   `hls.js` plays with no cross-domain cookie; production stays on signed cookies.
   The signing logic is identical; only the delivery vehicle differs, in one
   gated branch. (See **Local-dev → Local playback uses signed URLs**.)
8. **NIT — local SPA config load mechanism unspecified.** Addressed. Convention:
   the SPA always fetches `config.json`; local dev runs
   `cp spa/config.local.json spa/config.json` (the copy is gitignored). No
   hostname branching. (See **Local-dev → Local config convention**.)
9. **NIT — empty `get_item` not distinguished from `ResourceNotFoundException`.**
   Addressed. Routes branch on **`"Item"` not in response → `404`** and reserve
   `ResourceNotFoundException` for a missing table/index (`500`). The exception
   table now has three distinct `get_item`/`Query` rows. (See **FastAPI →
   `GET /videos/{video_id}`**, **`play-url`**, and the exception table.)
10. **NIT — hls.js cross-path credentialed fetch not called out.** Addressed.
    Added a sentence: media is same-origin under the one CloudFront domain, so
    scoped-`Path` cookies attach to `hls.js` XHRs automatically — no
    `withCredentials`/`xhrSetup` needed (only relevant if ever cross-origin, which
    it isn't). (See **CloudFront + signed-cookie playback**.)
11. **NIT — cited reference CDK is TypeScript while the build is Python.**
    Addressed. Added a **Language note** to the overview flagging the
    clear-thinking-app reference as TypeScript and directing the implementer to
    translate API names (`aws_cdk` imports, snake_case, `Source.json_data` not
    `jsonData`) rather than copy TS signatures. (See **Overview**.)

## Responses to design-review findings — round 3

Revision against the third `.agents/tasks/design-review.md` (verdict
CHANGES_REQUESTED: 3 MEDIUM, 5 NIT). All eight findings are **addressed** — none
backlogged, none ignored.

1. **MEDIUM — ALB ingress for the CloudFront VPC origin was an unverified
   "SG CDK creates" claim.** Addressed. Pinned **`aws-cdk-lib ^2.170.0`** (matches
   the clear-thinking-app reference; ≥ 2.166 carries `cloudfront.VpcOrigin`) and
   replaced the claim with a concrete, verifiable rule: the `cloudfront.VpcOrigin`
   L2 does not surface a referenceable SG for its managed ENIs, so `alb-sg`
   inbound is **TCP 80 from the VPC's private-subnet CIDRs**
   (`vpc.select_subnets(PRIVATE_WITH_EGRESS)`), where CloudFront places the
   VPC-origin ENIs and nothing else can reach the internal ALB. Showed the CDK
   loop and noted that a future version exposing the origin SG should be preferred
   if/when available. (See **Overview** version pin, **VPC security groups →
   `alb-sg`**.)
2. **MEDIUM — `put_object` of up to 2 GB on a 2 GB-RAM web instance.** Addressed.
   `POST /videos` now uses **`s3.upload_fileobj(file.file, …)`** (boto3 managed
   multipart) streaming from FastAPI's spooled `UploadFile`, never reading the
   body whole into RAM; the size cap is enforced on `Content-Length` and again by
   aborting the stream mid-transfer. Exception table row and validation updated.
   (See **FastAPI → `POST /videos`**, **Input validation**, exception table.)
3. **MEDIUM — "orphan swept by lifecycle" contradicted the lifecycle section.**
   Addressed. Removed the false claim: the Input lifecycle only tiers (no
   expiration), so the route now does a **best-effort compensating
   `delete_object`** of the just-uploaded key in the `except` branch when the
   catalog write fails, logging for manual cleanup if that delete also fails. The
   DLQ-marker's conditional update (below) keeps any residual queued message
   harmless. (See **FastAPI → Orphan handling**, exception table.)
4. **NIT — production uses signed cookies; the decision said signed URLs.** No
   change to the mechanism (cookies are the right fit for HLS fan-out and local
   dev still uses signed URLs), but added an explicit **callout block** stating
   the requirement is met and asking the user to confirm the cookie vehicle.
   Surfaced to the user in the step summary. (See **CloudFront + signed-cookie
   playback** callout.)
5. **NIT — worker wrote `Failed` on the first non-zero exit (spec said "repeated
   failure").** Addressed. Stated that a **non-zero FFmpeg exit is a deterministic
   rejection** (write `Failed`, delete, no retry — retrying can't help), while
   **transient infra errors** (S3 download, disk-full, DynamoDB `ClientError`) are
   raised/left for redelivery and only dead-letter after `maxReceiveCount=3`.
   `worker.py` distinguishes by which operation raised. (See **SQS + DLQ →
   writer 1**.)
6. **NIT — Secrets Manager signing-key read per request.** Addressed. The web
   process loads and parses the private key **once at startup** (lifespan hook),
   reuses the in-memory `RSAPrivateKey`, with an optional 12 h TTL refresh for
   rotation; startup-read failure fails the health check rather than serving
   unsignable URLs. (See **CloudFront → Signing-key caching**.)
7. **NIT — `original_filename` embedded in the S3 key unsanitized.** Addressed.
   Added sanitization (Unicode-normalize, strip control chars + path separators,
   reduce to `[A-Za-z0-9._-]`, clamp to 200 bytes keeping the extension, empty →
   `video`); the verbatim name is kept only as a display attribute, and the note
   restates that correlation parses the hex `video_id` from the key prefix, never
   the filename. (See **`video_id` → step 2**, **Input validation**.)
8. **NIT — broken reference link `clear-thinking-app/iac`.** Addressed. The
   wikilink now points at **`[[projects/clear-thinking-app]]`** (the note),
   naming its `iac/` CDK app in prose. (See **Overview** header.)

## Post-deploy remediation — Finding 3 (CloudFront → internal ALB)

The round-2/round-3 design used a **CloudFront VPC origin** straight to the
internal ALB for `/api/*`. The live deploy (see `walkthrough.md` §9a) proved that
path does **not** carry edge→ALB traffic — every `/api/*` request returned a 30 s
CloudFront 504 despite a textbook-correct SG / port / target-health / NACL
configuration. The VPC-origin feature was the single thing that didn't work.

**Remediation (applied in code, synth-verified).** The `/api` hop is now a
well-trodden pattern: CloudFront `/api/*` → an **API Gateway HTTP API** (its
AWS-managed `execute-api` HTTPS endpoint, used as an `HttpOrigin` with
`protocol_policy=HTTPS_ONLY`) → a **VPC Link** (ENIs in the private subnets,
`vpclink-sg`) → the **still-internal ALB** → the web ASG (FastAPI on `:8000`).

- The ALB stays `internet_facing=False` in the private subnets (hardening
  preserved); its SG admits TCP 80 from `vpclink-sg` only — never `0.0.0.0/0`,
  never a private-CIDR range.
- The CloudFront→origin hop is HTTPS end-to-end (the `execute-api` cert), so the
  signed-cookie `Set-Cookie` is never plaintext over the internet.
- Everything stays on the single CloudFront domain (no CORS / cross-domain-cookie
  issues), and the obsolete `cloudfront.VpcOrigin` construct is removed.
- The `/api` prefix is stripped at the HTTP API (route `ANY /api/{proxy+}`,
  integration `overwrite:path = /${request.path.proxy}`), so the FastAPI app is
  **unchanged** and keeps its unprefixed routes; local dev (which calls those
  routes unprefixed) keeps working.

This supersedes round-2 response 6 and round-3 response 1 (both of which described
the now-removed VPC-origin + private-CIDR-ingress approach). **Confirmed live on
the second pass (2026-10-22):** `GET /api/videos` → `200` in ~0.13 s through this
path, ALB still `internal` (see `walkthrough.md` §9a "Second live pass").

## Post-deploy remediation — Finding 4 (`/media/*` → `output/` prefix mismatch)

The second live pass surfaced a playback defect that `synth` + mocked tests could
not: a video reached `Ready` but stalled at 0:00. The signed-cookie machinery was
**correct** — CloudFront accepted the cookies and forwarded to S3; **S3** returned
the 403 because the requested key did not exist. The public playback contract is
`/media/<id>/*` (the API signs cookies and returns play-urls under it), but the
worker writes HLS to the Output bucket under `output/<id>/*`, and the `/media/*`
behaviour had an empty origin path — so CloudFront asked S3 for
`media/<id>/playlist.m3u8`, a key that is never written. The `/media/` → `output/`
mapping was simply never wired.

**Remediation (applied in code, synth-verified, confirmed live).** A CloudFront
**viewer-request Function** on the `/media/*` behaviour rewrites the `/media/`
prefix to `/output/` so the edge fetches the real key. Origin path cannot do this:
it *prepends* to the URI and cannot strip the matched `/media` segment. `cdk synth`
shows the `AWS::CloudFront::Function`; live verification served the real keys and
re-fetched through the edge with signed cookies (manifest + segment both `200`).

## Future enhancements (out of scope this pass)

- **Video thumbnails / poster frames.** Gallery cards render a placeholder, not a
  frame of the video. A proper preview needs the worker to extract one frame at
  transcode time (`ffmpeg -frames:v 1`) and store it on a **publicly-served path**
  (the site bucket, behind the default behaviour — *not* `/media/*`, which is
  signed-cookie gated and so cannot be loaded by a plain gallery `<img>`); the API
  would then return `thumbnail_url` (the SPA already renders it if present). Costs
  a worker + API + IAM change and a redeploy, so it was deferred — it is UI polish,
  not a hardening objective.
- **Auth (Cognito)**, customer-managed KMS, and WAF on CloudFront remain the
  security follow-ups already noted in the Well-Architected mapping.
