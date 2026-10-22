---
title: "Project: Video Streaming Platform — event-driven ingest, transcode & HLS"
type: project
domain: architecting
date-started: 2026-10-19
services:
  - iam
  - s3
  - dynamodb
  - sqs
  - ec2
status: v1-built-and-tested-live; hardened-deployed-tested-torndown-2026-10-22 (one open finding: CloudFront VPC-origin→ALB)
tags:
  - aws
  - project
---

# Project: Video Streaming Platform — event-driven ingest, transcode & HLS

> Related: [[projects/projects|projects index]]
> Design source: course project (console build first, same architecture pattern
> behind real services that ingest, transcode, and stream video at scale).
> Part of the [H2 2026 AWS OKR](../README.md) — counts toward KR1 (documented
> architecture), KR2 (working project — **project 3 of 3**), KR3
> (Well-Architected), and KR4 (walkthrough).

> **Hardened build (Phase 2) — status.** The tutorial v1 below was **console-built
> and verified live**; those console resources have since been shut down. The
> hardened rebuild is **AWS CDK (Python)** — three stacks that synthesize — with
> the FastAPI web tier + vanilla SPA **runnable locally** against env-injected
> resource names (see [`video-streaming-app/LOCAL_DEV.md`](./video-streaming-app/LOCAL_DEV.md)).
> **No `cdk deploy` or `cdk destroy` was run in this workflow — nothing was
> provisioned in AWS this pass.** How each hardening flag is closed by the
> as-built code is in [the architecture walkthrough](./video-streaming-app/walkthrough.md)
> and [`video-streaming-app/DESIGN.md`](./video-streaming-app/DESIGN.md).
>
> **Confirmed branch-point decisions:** IaC = **CDK in Python**; transcode compute
> stays faithful (hardened EC2/FFmpeg worker); frontend = **vanilla HTML/JS static
> SPA** verified locally first; **no auth** this pass. Playback uses **CloudFront
> signed COOKIES in production** (confirmed) — scoping `/media/{video_id}/*` with
> one signing op for the whole HLS fan-out — and signed URLs in local dev (a
> browser on `127.0.0.1` can't carry a CloudFront-domain cookie). This meets the
> "CloudFront + signed URLs" spec substance (private Output bucket, CloudFront-gated
> playback, per-video-scoped credentials); only the production delivery vehicle
> differs. See the walkthrough §5 for the full rationale.

## Use case / goal

An **event-driven video processing and streaming platform** — the same pattern
behind real services that ingest, transcode, and stream video at scale. The core
idea is **decoupling** the three stages of the pipeline so they scale and fail
independently:

1. **Upload (ingest)** — raw video lands in S3.
2. **Process (transcode)** — an FFmpeg worker turns raw video into HLS segments.
3. **Deliver (stream)** — the browser plays HLS from S3 via the frontend.

State is tracked in **DynamoDB**, and transcoding jobs are **buffered through an
SQS queue** (with a **Dead Letter Queue** for poison messages) so a slow or
failing worker never blocks uploads.

## Architecture

The whole point is **decoupling**: video transcoding is CPU-heavy, so running it
on the web server would freeze the site for every other user. Instead the web
server just accepts the upload and returns instantly; a separate worker does the
heavy lifting asynchronously, buffered by SQS. (See
[[learning-plan/10-architecting/sqs-decoupling-and-dlq|the SQS decoupling note]]
for why this pattern exists.)

```
                         user
                          │  ▲
                   upload │  │ stream video (HLS)
                          ▼  │
 ┌─ VPC / Public subnet ───────────────────────┐
 │  ┌──────────────┐  Read/Update  ┌──────────┐ │       ┌─────────────┐
 │  │  Web Server  │◄─────────────►│          │ │       │   Input     │
 │  │ (EC2, Flask) │──── Upload ─────────────────┼──────►│  Bucket (S3)│
 │  └──────┬───────┘               │ DynamoDB │ │       └──────┬──────┘
 │         │ read status           │ (status: │ │              │ S3 event
 │         │                       │ Queued → │ │              ▼
 │  ┌──────▼───────┐ Update/Meta   │  Ready)  │ │       ┌─────────────┐
 │  │ Worker Server│──────────────►│          │ │       │  SQS Queue  │
 │  │ (EC2, FFmpeg)│               └──────────┘ │       └──────┬──────┘
 │  └──┬────────▲──┘                            │              │ poll
 │     │        └─ Download raw video ──────────┼──────────────┘
 │     │ Upload HLS                             │  (worker pulls from Input Bucket)
 │     ▼                                        │
 │  ┌──────────────┐                            │
 │  │ Output Bucket│ ── HLS (.m3u8 + .ts) ──────┼──► streamed to the browser
 │  │ (S3)         │                            │
 │  └──────────────┘                            │
 └──────────────────────────────────────────────┘
   IAM — instance-profile roles for Web Server & Worker (least privilege)
```

### End-to-end flow

1. **Upload.** User uploads an MP4 through the **Web Server (EC2 + Flask)**. The
   web server puts the raw file in the **Input Bucket (S3)** and writes a
   **`Queued`** status row to **DynamoDB**. The upload returns immediately — no
   waiting on transcoding.
2. **Buffer (S3 event → SQS).** The moment the object lands in the Input Bucket,
   **S3 fires an event notification** that enqueues a job in the **SQS Queue**.
   The queue holds the job safely until a worker is free. (Native S3→SQS
   integration — the web server doesn't enqueue manually.)
3. **Process (Worker).** The **Worker Server (EC2 + FFmpeg)** constantly **polls
   SQS**, receives the job, **downloads** the raw video from the Input Bucket,
   runs **FFmpeg** to transcode it into **HLS** (`.m3u8` playlist + `.ts`
   segment chunks), **uploads** the HLS output to the **Output Bucket (S3)**, and
   **updates DynamoDB** to **`Ready`**. Then it deletes the SQS message.
4. **Deliver (Player).** The browser reads the **`Ready`** status (via the web
   server → DynamoDB) and **streams the HLS** output directly from the Output
   Bucket.

### Why each piece is here

| Component | Role | Note |
| --- | --- | --- |
| **Web Server** (EC2 + Flask) | Serves UI; accepts upload → Input Bucket + `Queued` in DynamoDB; serves playback | Public subnet (internet-facing) |
| **Input Bucket** (S3) | Stores raw uploaded video; its event triggers the pipeline | [[learning-plan/03-storage/s3-core-concepts\|S3 note]] |
| **SQS Queue** | Decouples upload from transcode; buffers burst load | [[learning-plan/10-architecting/sqs-decoupling-and-dlq\|SQS note]] |
| **Worker Server** (EC2 + FFmpeg) | Polls SQS, transcodes raw → HLS, writes output + state | CPU-bound; the reason for decoupling |
| **Output Bucket** (S3) | Stores HLS `.m3u8` + chunks; streamed to viewers | — |
| **DynamoDB** | Job state (`Queued → Ready`) + metadata | [[learning-plan/05-databases/dynamodb-core-concepts\|DynamoDB note]] |
| **IAM** | Instance-profile roles for web + worker, least privilege | [[learning-plan/06-security-iam/iam-users-groups-roles-policies\|IAM note]] |

### Hardening flags (tutorial v1 → hardened, same story as PhotoShare)

Recording where the tutorial design takes the simpler path, so the hardened
version becomes explicit OKR/Well-Architected evidence later (exactly how
PhotoShare went v1 → Phase 2):

- **Worker Server is in the public subnet** in the tutorial, but it only needs to
  **poll SQS, read/write S3, and update DynamoDB** — all reachable without being
  internet-facing. Hardened: move the worker to a **private subnet** (outbound via
  NAT or VPC endpoints for S3/SQS/DynamoDB), admin via **Session Manager** (no
  inbound SSH — see [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|SSM note]]
  and [[learning-plan/02-compute/ec2-key-pairs|key pairs note]]).
- **No DLQ in the base diagram — ⚠️ VERIFIED LIVE as a real crash loop.** An
  un-processable upload (here: a 4K file that **OOM-kills** FFmpeg — see Gotchas)
  is a **poison pill**. Because the worker dies before `delete_message`, the SQS
  message reappears after the visibility timeout and OOM-loops **forever** with no
  DLQ to catch it. Hardened: attach a **DLQ** with a `maxReceiveCount` so bad
  videos are quarantined after N attempts (the DLQ pattern practiced earlier).
- **Visibility timeout must exceed transcoding time.** Video transcode can be
  slow; if the SQS visibility timeout is shorter than a job takes, the message
  reappears mid-work and a second worker double-processes it. Set it generously +
  keep the worker idempotent (DynamoDB status check).
- **S3 public access / playback path — ✅ RESOLVED (task 7, the good way).** The
  diagram implied "browser streams HLS **directly** from the Output bucket," but
  `server.py` actually **proxies** it: the `/stream/<video_id>/<file>` route has
  Flask `get_object` from the Output bucket (via the instance role) and relays the
  bytes to the browser (`stream_with_context` + `iter_chunks`). So the **Output
  bucket stays private** — the browser never touches S3, only the web server does.
  No world-readable bucket needed. (Possible further optimization, not a security
  gap: CloudFront or presigned URLs to offload the byte-relay from the web
  server — but the private-bucket goal is already met.)
- **IAM role is over-broad (`*FullAccess`) and possibly shared.** The tutorial's
  `iam_role_video_lab` uses `AmazonS3FullAccess` / `AmazonSQSFullAccess` /
  `AmazonDynamoDBFullAccess` — every action on *every* bucket/queue/table in the
  account, not just this project's. Same finding PhotoShare flagged ("scope
  `AmazonS3FullAccess` down"). Hardened: **two scoped roles** matching each
  server's actual job —
  - **Web Server:** S3 `PutObject` to Input + read Output, DynamoDB read/write on
    the jobs table. **No SQS** (S3 fires the event, not the web server).
  - **Worker Server:** SQS receive/delete, S3 read Input + write Output, DynamoDB
    update. **No upload path.**
  …each via least-privilege inline policies on the specific bucket/queue/table
  ARNs (like PhotoShare's `iam_role_ec2` + `iam_role_lambda`). Resolved as **one
  shared role** in task 5, so this split is the hardening target.
- **Worker is NOT idempotent + visibility timeout too short = latent
  duplicate-processing bug.** Two issues that compound (both predicted by
  [[learning-plan/10-architecting/sqs-decoupling-and-dlq|the SQS note]]):
  - `worker.py` never checks "is this `video_id` already `Ready`? skip" — so a
    **redelivered** message (SQS is at-least-once) re-transcodes from scratch.
  - `VideoQueue` uses the **default 30s visibility timeout**, but transcoding a
    video easily exceeds 30s → the message **reappears mid-transcode** → a second
    receive double-processes it (and feeds the DLQ receive count). Hardened: set
    the **visibility timeout > worst-case transcode time** *and* make the worker
    **idempotent** (check DynamoDB status before processing). Need both — the
    timeout prevents most duplicates, idempotency makes the rest harmless.
- **No `Failed` status on error — ⚠️ VERIFIED LIVE.** The worker's `except` prints
  and *doesn't* delete the message (good — it retries / eventually dead-letters),
  but it never writes a `Failed` status to DynamoDB. On the 4K OOM failure (see
  Gotchas) this meant the **UI gave no signal** — the user just hit a broken
  player ("media could not be loaded") with no "Failed" state to explain why.
  Hardened: on repeated failure, write `Failed` so the frontend can surface it.
- **`put_item` on completion overwrites the row.** Mid-progress uses
  `update_item` (merge) but the finish uses `put_item` (full replace), wiping any
  other attributes on the item. Minor, but use `update_item` consistently.
- **FFmpeg pulled from a flaky third-party host at build time** — see Gotchas;
  bake into an AMI / pin the artifact for reproducibility.
- **`video_id` is derived differently by web vs worker — latent "stuck on
  Queued" bug.** The two scripts compute the id from the filename independently:
  - **Web** (`server.py`): `filename.split('.')[0].replace(' ','_').replace('+','_')`
  - **Worker** (`worker.py`): `unquote_plus(key)` then `key.split('.')[0].replace(' ','_')` (no `+`→`_`)

  For a filename with spaces/pluses these can produce **different ids** → the web
  server writes the `Queued`/listing row under one `video_id` while the worker
  writes `Processing`/`Ready` under another → the UI polls the wrong key and the
  video appears **stuck on `Queued`** forever. Hardened: derive `video_id` in
  **one** place (ideally the web server at upload) and **pass it through** (S3
  object key / metadata / the message), so both sides use the identical id — this
  is the pipeline correlation id from the DynamoDB build-log note.
- **Web app runs as root on port 80.** Started with `sudo python3.11 server.py` to
  bind privileged port 80 — a Flask exploit would mean **root** on the box.
  Hardened: run unprivileged on a high port behind a reverse proxy (nginx) or an
  ALB, or grant only `CAP_NET_BIND_SERVICE` instead of full root.
- **Flask dev server used as the app server.** `app.run(host='0.0.0.0', port=80)`
  is Werkzeug's **development** server (not built for concurrency/load). Fine for
  the lab; a real deploy uses **gunicorn/uwsgi behind nginx**.
- **`/api/videos` does a full DynamoDB `scan`.** `table.scan()` reads the **entire
  table** every poll (every 3s per browser). Fine at lab scale, but `scan` is the
  DynamoDB anti-pattern at scale (cost + latency grow with table size) — contrary
  to the key-based access the
  [[learning-plan/05-databases/dynamodb-core-concepts|DynamoDB note]] argues for.
  Hardened: a GSI or a dedicated listing access pattern instead of scanning.
- **Bare `except:` in `/stream` returns 404 for everything.** Masks auth/permission
  errors as "Not Found," making broken playback hard to debug. Hardened: catch
  specific exceptions and log/return distinct statuses.
- **Web tier rebuild — replace the tutorial UI + fix the server (planned
  hardening).** The tutorial fuses UI and backend into one `server.py` (a giant
  inline `HTML_TEMPLATE` string served by Flask), and the UI is weak. Rebuild the
  web tier properly — same move PhotoShare made (swapped the tutorial's prebuilt
  image for a self-built FastAPI app + custom frontend). This bundles several
  already-flagged fixes into one coherent change:
  - **Frontend:** build a real UI (not an inline HTML blob). *Decision to make:*
    keep it server-rendered, or split into a **static SPA on S3 + CloudFront**
    talking to a JSON API. The SPA path is cleaner and composes with the playback
    decision below.
  - **Backend/server:** address the Flask-tier flags together — stop running
    **as root** (unprivileged + reverse proxy / ALB), replace the **Flask dev
    server** (gunicorn/uwsgi), fix the **`scan`** listing (GSI / proper access
    pattern), and the **bare `except`**.
  - **Playback path:** *decision to make:* keep the Flask **HLS proxy**, or front
    the Output bucket with **CloudFront + signed URLs** (offloads byte-relay from
    the web server; natural fit if the frontend goes static). Ties to the
    playback flag above.
  - **Also fold in** the `video_id` derivation fix (derive once, pass through) so
    web and worker can't disagree.

## Design decisions & tradeoffs

Describes the **as-built tutorial design (v1)** and the tradeoff each choice
makes; the Hardening flags section above is the v2 target for each gap.

- **Security:** No hardcoded credentials anywhere — both EC2 instances use the
  `iam_role_video_lab` instance profile for all S3/SQS/DynamoDB calls. S3 buckets
  keep **Block Public Access ON**; playback is **proxied through Flask** so the
  Output bucket stays private. The S3→SQS event is locked to the specific bucket
  via an `aws:SourceArn` condition (confused-deputy protection). *Tradeoff taken:*
  one shared, over-broad `*FullAccess` role across both servers, and SSH open
  `0.0.0.0/0` — both flagged for hardening.
- **Reliability:** SQS decouples upload from transcode so the web tier stays
  responsive regardless of worker state or file size. *Tradeoff taken:* **no DLQ**
  and a **non-idempotent worker** with the **default 30s visibility timeout** —
  verified live as a real poison-pill crash loop when a 4K file OOM-killed the
  worker. Hardening adds a DLQ + idempotency + a longer timeout.
- **Scalability:** SQS buffers burst uploads; the transcode worker scales
  independently of the frontend (queue depth is the natural scaling signal).
  *Tradeoff taken:* a single fixed worker (no Auto Scaling Group yet), and
  `/api/videos` uses a full DynamoDB `scan`.
- **Cost:** Pay-per-use DynamoDB (On-Demand) + S3; t3.micro instances chosen for
  lab cost. *Tradeoff taken:* t3.micro is **too small for real transcoding**
  (OOM'd on 4K) — a correct build right-sizes the worker (compute-optimized) and
  could scale it to zero when the queue is empty.

## Well-Architected review

Tutorial build is **v1**; "Improvement identified" = the hardening target (the
same v1→Phase-2 pattern as PhotoShare). Items marked **⚠️ verified live** were
confirmed by the first end-to-end test, not just predicted.

| Pillar | Finding (v1 as-built) | Improvement identified |
| --- | --- | --- |
| Operational Excellence | Console-built, not reproducible; FFmpeg pulled from a flaky third-party host at boot; **no `Failed` state** so failures are invisible in the UI (⚠️ verified live) | Rebuild as **IaC** (CloudFormation/CDK); bake FFmpeg into a **custom AMI** / pin the artifact; write a `Failed` status on error so the frontend surfaces it |
| Security | No hardcoded creds (instance-profile role); S3 Block Public Access on; playback proxied (bucket private); S3→SQS `SourceArn`-guarded. But: **one shared `*FullAccess` role**; **SSH `0.0.0.0/0`**; web app runs **as root** | Split into **two least-privilege per-server roles** scoped to this project's resources; remove inbound SSH (use **Session Manager**); run the web app unprivileged behind a reverse proxy/ALB |
| Reliability | SQS decouples upload from transcode. But: **no DLQ** + **non-idempotent worker** + **30s default visibility timeout** → real **poison-pill OOM crash loop** (⚠️ verified live) | Add a **DLQ** (`maxReceiveCount`); make the worker **idempotent** (DynamoDB status check); set **visibility timeout > worst-case transcode time** |
| Performance Efficiency | **t3.micro** worker **OOM-killed** on a 4K transcode (⚠️ verified live) — burstable + ~1 GB RAM is wrong for CPU/memory-heavy FFmpeg; worker downscaling absent | Use a **compute-optimized** worker (c-family); **downscale** output (`scale=-2:720`) so large inputs fit; explicit H.264/AAC for HLS |
| Cost Optimization | Pay-per-use DynamoDB (On-Demand) + S3; small instances for lab | Right-size the worker; **scale worker to zero** when the queue is empty (ASG on queue depth); S3 **lifecycle** to move raw source to IA/Glacier after processing |
| Sustainability | Managed services (S3/SQS/DynamoDB) reduce idle footprint | Scale-to-zero worker + lifecycle-tiered storage avoid provisioning for peak / storing hot what should be cold |

## Build log / steps

Building end-to-end through the AWS console (CloudShell for CLI steps, since the
lab user is blocked from creating long-term access keys):

1. **IAM** ✅ — created **`iam_role_video_lab`**: EC2 service trust
   (`ec2.amazonaws.com`, wrapped in an instance profile), with
   `AmazonS3FullAccess` + `AmazonSQSFullAccess` + `AmazonDynamoDBFullAccess`
   attached. No hardcoded keys — the EC2 service-role pattern from
   [[learning-plan/06-security-iam/iam-users-groups-roles-policies|the IAM note]].
   - **RESOLVED (task 5):** it's **one shared role** — both Web-Server and
     Worker-Server attach the same `iam_role_video_lab` instance profile. The IAM
     hardening flag (split into two scoped per-server roles) stands.
2. **S3** ✅ — created two buckets (names globally unique, random suffix per the
   [[learning-plan/03-storage/s3-core-concepts|S3 note]]):
   - **Input Bucket** `lab-video-input-[id]` — raw uploads.
   - **Output Bucket** `lab-video-output-[id]` — HLS output.
   Both left at **defaults → Block Public Access ON**. Fine for Input; **watch the
   Output bucket** — playback streams HLS from it, so a later step must either
   disable Block Public Access (world-readable — hardening concern, see flag
   below) or serve via a controlled path (presigned URLs / web server /
   CloudFront). Event notification (Input → SQS) wired in **task 4** (see step 4).
3. **DynamoDB** ✅ — created table **`VideoCatalog`** with a **simple primary
   key**: partition key `video_id` (String), no sort key. Defaults → **On-Demand**
   capacity mode. See [[learning-plan/05-databases/dynamodb-core-concepts|the
   DynamoDB note]].
   - **Why simple key (not composite):** every access is "look up *one* video by
     id" — web server reads status by `video_id`, worker updates the same item by
     `video_id`. No "all items in a group" query → no sort key needed.
   - **`video_id` is the pipeline's correlation id** — the same id ties the S3
     objects, the SQS message, and this DynamoDB item together. It's also what
     makes the worker **idempotent** (already `Ready` for this `video_id`? skip) —
     the SQS at-least-once backstop from
     [[learning-plan/10-architecting/sqs-decoupling-and-dlq|the SQS note]].
4. **SQS** ✅ — created Standard queue **`VideoQueue`**, then wired S3→SQS (both
   halves, per [[learning-plan/10-architecting/sqs-decoupling-and-dlq|the SQS
   note]]):
   - **Queue resource policy** — allows `s3.amazonaws.com` to `sqs:SendMessage`
     to `VideoQueue`, guarded by an **`aws:SourceArn` condition** pinned to the
     Input bucket (the **confused-deputy** protection — without it, *any* S3
     bucket could send to the queue). First **resource-based policy** built in
     this course.
   - **S3 event notification** `VideoUploadEvent` on the Input bucket → **All
     object create events** → destination **VideoQueue**. This closes the
     "event notification TODO" from step 2 above.
   - Noted the **Queue URL** (distinct from the ARN) for the Python worker code.
   - DLQ still a hardening step (not in the base tutorial).
5. **EC2 instances** ✅ — launched **Worker-Server** and **Web-Server**, both:
   **Amazon Linux 2023**, **t3.micro**, public subnet, SG inbound **SSH + HTTP
   from Anywhere (`0.0.0.0/0`)**, and **both attach the same
   `iam_role_video_lab`** instance profile. "Proceed without a key pair" + **EC2
   Instance Connect** for browser terminal access (per
   [[learning-plan/02-compute/ec2-key-pairs|key pairs note]] /
   [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|SSM note]]).
   - **RESOLVED open question:** it's **one shared role** across both servers (not
     per-server) — the IAM hardening flag below stands as written.
   - **Confirmed hardening gaps (already flagged):** worker is public with SSH+HTTP
     open though it needs **no inbound at all** (it only polls SQS outbound);
     **SSH from `0.0.0.0/0`** on both — the pattern the SSM note argues against
     (note plain EC2 Instance Connect still needs inbound SSH; only the EIC
     *Endpoint* avoids it).
   - **Perf-efficiency note (Worker) — ⚠️ VERIFIED LIVE:** `t3.micro` is
     **burstable** with ~1 GB RAM — not just CPU-credit throttling, it has too
     little **memory**: a 4K transcode **OOM-killed FFmpeg** on first live test
     (see Gotchas). Real transcoding wants a larger / compute-optimized type
     (c-family). → Well-Architected table.
6. **Worker-Server app** ✅ — on the Worker-Server: installed **FFmpeg** (via the
   GitHub/CDN fallback — see Gotchas) + **boto3**, wrote **`worker.py`**, started
   it (long-polls SQS, "Worker started. Listening…"). The loop:
   `receive_message(WaitTimeSeconds=20)` → handle `s3:TestEvent` → download raw
   from Input → `ffmpeg … -f hls playlist.m3u8` → upload HLS to Output under
   `video_id/` → DynamoDB `Processing`(with %)→`Ready` → `delete_message`. Maps
   cleanly onto the [[learning-plan/10-architecting/sqs-decoupling-and-dlq|SQS]]
   consume→process→delete lifecycle and the
   [[learning-plan/05-databases/dynamodb-core-concepts|DynamoDB]] `video_id`
   state row. Several latent bugs — see hardening flags below.
7. **Web-Server app** ✅ — on the Web-Server: installed **Flask** + **boto3**,
   wrote **`server.py`** ("KodeTube" UI + video.js HLS player), started it on
   **port 80** (`sudo python3.11 server.py`). Routes:
   - `POST /upload` → `s3.upload_fileobj` to Input Bucket + DynamoDB `put_item`
     status `Queued` (kicks off the pipeline).
   - `GET /api/videos` → `table.scan()` for the grid (polled every 3s).
   - `GET /stream/<video_id>/<file>` → **proxies** HLS from the Output Bucket
     through Flask (so the bucket stays private — resolves the playback hardening
     flag).
   - `POST /api/delete/<video_id>` → DynamoDB delete + S3 prefix cleanup.
   All S3/DynamoDB calls run via `iam_role_video_lab` — **no credentials in code**
   (the IAM-role payoff). Latent bugs in hardening flags (esp. the `video_id`
   derivation mismatch vs the worker).
8. **Playback** ✅ — end-to-end pipeline **verified live**: upload → Input Bucket
   → S3 event → SQS → worker transcodes to HLS → Output Bucket → DynamoDB `Ready`
   → UI polls status → video.js streams HLS **proxied through the web server**.
   First attempt (4K clip) **OOM-failed** (see Gotchas); recovered via **Option
   A** — cleared the stuck 4K job (deleted the Input object + purged VideoQueue)
   and re-ran with a smaller clip, which played end-to-end. Build complete.

_Buckets:_ `lab-video-input-video-streaming-lab` / `lab-video-output-video-streaming-lab`.
_Table:_ `VideoCatalog` (PK `video_id`). _Queue:_ `VideoQueue`. _Instances:_
Web-Server + Worker-Server (Amazon Linux 2023, t3.micro). _Role:_ `iam_role_video_lab`.

## Gotchas & troubleshooting

- **FFmpeg download from the tutorial's single third-party host hung/failed.**
  The tutorial pulls the static build from `johnvansickle.com`, which was
  unreachable at build time: HTTPS failed with "Unable to establish SSL
  connection," and plain HTTP hung at "Connecting... :80." **Not an instance
  problem** — confirmed egress + TLS were healthy via `curl -I
  https://aws.amazon.com` (returned `HTTP/2 200`), which isolates the fault to
  that specific host. **Fix:** pulled the static build from the CDN-backed GitHub
  release instead (`BtbN/FFmpeg-Builds`, `linux64-gpl` for x86_64 / t3.micro),
  `curl -L` to follow the redirect, and copied `ffmpeg`/`ffprobe` to
  `/usr/local/bin`. `ffmpeg -version` confirmed libx264/libx265 + HLS support —
  a superset of what the tutorial build provides, so the rest of the worker setup
  is unchanged.
  - **Reproducibility lesson (→ hardening):** pinning a boot-time dependency to a
    live third-party URL is fragile. A hardened/IaC build should **bake FFmpeg
    into a custom AMI** or pull from a **pinned, reliable artifact** (e.g. own S3
    object), so the worker doesn't depend on a flaky origin host at launch.
  - **Debug pattern worth keeping:** when a download stalls, `curl -I` a known-good
    HTTPS host first — if that works, the problem is the *source*, not your
    egress/SG/routing; if it also fails, it's the instance's outbound path.
- **First live test FAILED — FFmpeg OOM-killed transcoding a 4K file on the
  t3.micro.** Uploaded a **46 MB, 3840×2160 (4K)** clip. Upload worked (file
  landed in the Input bucket), but the player showed *"The media could not be
  loaded… format not supported."* Diagnosis chain:
  - Output bucket was **completely empty** (`aws s3 ls` → nothing) → no HLS ever
    produced.
  - `sudo dmesg | grep -i "out of memory"` on the Worker-Server →
    `Out of memory: Killed process … (ffmpeg) total-vm:1881692kB` — the kernel
    **OOM-killed FFmpeg** (~1.8 GB virtual mem on a ~1 GB-RAM t3.micro).
  - The player's *"Not Found"* was partly the bare `except: 404` in `/stream`
    masking "the object genuinely doesn't exist."
  - **Three documented hardening flags converged in one failure** (and are now
    **verified live**, not just predicted): (1) t3.micro too small for
    CPU/memory-heavy transcode, (2) no DLQ → the killed job's SQS message was
    never deleted, so it **reappears and OOM-loops forever** (textbook poison
    pill), (3) no `Failed`-status write → the UI couldn't report the failure.
  - **Fix / remediation:**
    1. **Clear the stuck job first** (or it OOM-loops): delete the 4K object from
       the Input bucket + **Purge** the VideoQueue (no DLQ to catch it).
    2. **Make the worker downscale** so large inputs fit — the tutorial command
       transcoded at *source* resolution (4K in → 4K out = the memory blowup).
       Cap output and set HLS-safe codecs explicitly:
       ```python
       cmd = ['ffmpeg', '-i', local_in,
              '-vf', 'scale=-2:720',          # 720p, keep aspect ratio
              '-c:v', 'libx264', '-profile:v', 'baseline', '-level', '3.0',
              '-c:a', 'aac',                  # HLS-compatible audio
              '-f', 'hls', f'{out_dir}/playlist.m3u8']
       ```
    3. For real workloads: a **larger / compute-optimized** worker (not burstable
       t3.micro) — see the perf-efficiency flag.
  - **Takeaway:** the lab's v1 failed *exactly* where the hardening analysis said
    it would — a clean demonstration that the flagged gaps were real, not
    theoretical.

## Cleanup

- [x] **Tutorial v1 (console) resources shut down** — the console-built build was
  torn down earlier; nothing from v1 is still running.
- [x] **Hardened Phase 2 — deployed, tested live, and torn down (2026-10-22).**
  `cdk deploy` to `us-east-1`, exercised end-to-end, then `cdk destroy` the same
  day with a verified-nothing-lingers sweep (stacks, `video-*` buckets,
  `VideoCatalog`, both queues, the signing-key secret, `/video/*` log groups, the
  CloudFront distribution, both ASGs). The live pass fixed two runtime defects
  (Python 3.9→3.11 on the AMI; CloudFront bare-root 403) and surfaced one open
  issue — CloudFront **VPC-origin → internal ALB** won't carry `/api` traffic
  despite a correct SG/port/NACL/health (a newer-feature gotcha). Full record,
  root-cause evidence, and the remediation are in
  [the walkthrough §9a](./video-streaming-app/walkthrough.md). The fix is a
  code/`synth` change; re-proving it live is a future one-command redeploy.

## Walkthrough summary

This platform is an **event-driven media pipeline** whose whole reason for
existing is **decoupling**: video transcoding is CPU- and memory-heavy, so doing
it inline on the web server would freeze the UI for everyone. Instead the three
stages run independently. A **Flask web server (EC2)** accepts an MP4 upload,
drops the raw file in an **S3 Input bucket**, and writes a `Queued` row to
**DynamoDB** — then returns instantly. The upload *event* is what drives the
rest: S3's **event notification** pushes a job to an **SQS queue** (authorized by
a resource policy pinned to that one bucket via `aws:SourceArn`, so no other
bucket can inject jobs). A separate **FFmpeg worker (EC2)** long-polls SQS,
downloads the raw video, transcodes it to **HLS** (`.m3u8` + `.ts` chunks),
uploads the result to an **S3 Output bucket**, flips DynamoDB to `Ready`, and
deletes the message. The browser polls status and, once `Ready`, streams the HLS
— **proxied through Flask**, so the Output bucket stays private. Every AWS call
runs through a single **EC2 instance-profile role** (`iam_role_video_lab`), so
there are **no credentials in the code**.

**Key design choices & tradeoffs.** DynamoDB uses a **simple `video_id`
partition key** because every access is a single-item lookup — and `video_id` is
the **correlation id** threading S3 ↔ SQS ↔ DynamoDB. SQS's visibility timeout +
the consume→process→*delete-only-on-success* lifecycle give free retries. The
tutorial (v1) deliberately takes the simple path in several places; the honest
tradeoffs are a single **over-broad shared role**, **SSH open to the world**, the
app **running as root** via the Flask dev server, a **`scan`** for the listing, a
**t3.micro** worker, and **no DLQ / non-idempotent worker / 30s visibility
timeout**.

**Failure modes (observed, not just theorized).** The first live test used a
**4K** clip and **FFmpeg was OOM-killed** on the t3.micro — producing no HLS, a
broken player, and (because the worker dies before deleting the message, with no
DLQ) an **infinite poison-pill retry loop**. This single failure confirmed
*three* predicted gaps at once — undersized compute, missing DLQ, and no `Failed`
status to surface the error. The pipeline then ran clean end-to-end with a
smaller clip. The documented fixes (downscale with `scale=-2:720` + explicit
H.264/AAC, a DLQ, idempotency, a right-sized worker) are the v2 hardening target
— the same v1→Phase-2 arc as PhotoShare.

## Takeaways

- **Decoupling is the point, and it holds under stress.** Even when the worker
  died, the web tier stayed responsive and the upload was never lost — SQS
  absorbed the failure. That's the event-driven payoff in one observation.
- **A real failure validated the hardening analysis.** The 4K OOM crash hit
  *exactly* the three gaps flagged in advance (t3.micro, no DLQ, no `Failed`
  state). Predicting a gap is cheap; watching it fire is the convincing evidence.
- **`video_id` as a single correlation id** is what lets four services (S3, SQS,
  DynamoDB, the player) coordinate without tight coupling — and deriving it
  *inconsistently* across web vs worker is a subtle, real bug.
- **Least privilege by role pays off visibly** — neither script holds a single
  credential; all access flows through the instance profile.
- **Resource policies + `aws:SourceArn`** are the standard, reusable way to let
  one AWS service trigger another safely (the confused-deputy guard) — first
  built here, applicable far beyond this project.
- **Diagnose from the data plane inward** — empty Output bucket → `dmesg` OOM
  line → root cause, in three commands. The bare `except: 404` nearly hid it;
  good error surfacing matters.
