# Design Review — Video Streaming Platform (hardened, Phase 2 IaC)

**Design reviewed:** `projects/video-streaming-app/DESIGN.md`
**Authoritative spec:** `projects/video-streaming-app.md` (Hardening flags, Well-Architected review, Gotchas)
**Settled decisions:** CDK Python; hardened EC2+FFmpeg worker; FastAPI behind ALB (unprivileged); vanilla HTML/JS SPA on S3+CloudFront; CloudFront+signed URLs to private Output bucket; no auth.
**Review round:** 4 (design already carries responses to rounds 1–3).

**Verdict: CHANGES_REQUESTED** — 1 HIGH + 4 MEDIUM (+ 3 NIT). Mechanical rule: any HIGH or MEDIUM blocks.

This is a mature, heavily-revised design that closes the great majority of the hardening scope concretely. The findings below are the gaps that remain, concentrated in the CloudFront signing wiring and the local-dev playback path.

---

## Findings

### 1. HIGH — The CloudFront signer has no wired source for the `CloudFront-Key-Pair-Id`

**Where:** "CloudFront + signed-cookie playback" (the three cookies include `CloudFront-Key-Pair-Id`), "Signing-key pair lifecycle" (step 2), "Clean teardown + outputs" (`CfnOutput`s list `CfKeyGroupId`), "Local-dev approach" (env var list).

**Problem:** Generating a CloudFront signed cookie or signed URL requires three inputs: the private key (handled — read from Secrets Manager), the per-resource policy (handled), and the **CloudFront public key ID** used as the `CloudFront-Key-Pair-Id` field. That ID is the physical id of the `cloudfront.PublicKey` resource (e.g. `K2JCJMDEHXQW5F`) — **not** the key group id. The design:
- outputs `CfKeyGroupId` (the key *group*, which the distribution trusts) but never outputs the `PublicKey` id;
- omits any `CF_KEY_PAIR_ID` from the web tier's env var list (`INPUT_BUCKET`, `OUTPUT_BUCKET`, `TABLE_NAME`, `ARTIFACT_BUCKET`, `CF_KEY_SECRET_ARN`, `CF_DOMAIN`).

So the implementer has no value to put in `CloudFront-Key-Pair-Id`. Signing will either be unbuildable or will emit an invalid id, and every `play-url` cookie/URL will be rejected by CloudFront — breaking the core playback feature for both production and local dev.

**Concrete fix:** Add `CfnOutput("CfPublicKeyId", value=public_key.public_key_id)` and inject it into the web tier (deployed via launch-template env, local via the env list) as `CF_KEY_PAIR_ID`. The signer uses `CF_KEY_PAIR_ID` for the `Key-Pair-Id`/`CloudFront-Key-Pair-Id` field; keep `CfKeyGroupId` only for the distribution's trusted-key-group reference. Add `CfPublicKeyId` to both the local env list and the `CfnOutput`s.

### 2. MEDIUM — Out-of-band secret population vs. web-tier startup: ordering and recovery unspecified

**Where:** "Signing-key pair lifecycle" (step 3: private PEM loaded by a one-time `put-secret-value` *after* deploy) and "Signing-key caching" (startup read failure → fail health check).

**Problem:** The private key is populated **after** `cdk deploy`, but the web process reads it **once at startup** and fails its health check if the read fails. Web ASG instances launched by the deploy therefore come up unhealthy and stay unhealthy. The design states the TTL-refresh (12 h) covers rotation, but that refresh only runs on a process whose startup *succeeded* — it does not describe how an instance that failed the startup read ever recovers once the operator populates the secret. Whether recovery happens by ASG health-check-driven instance replacement, by a lazy per-request retry, or by a manual instance refresh is left ambiguous. As written, the app is down after a clean deploy until an unspecified manual step.

**Concrete fix:** Pick and state one: (a) make the signing-key load **lazy with retry** — the process starts healthy, serves non-signing routes, and attempts the secret read on first `play-url` (and caches on success), so populating the secret needs no instance churn; or (b) state explicitly that the ASG uses **ELB health-check type** and the documented deploy order is "deploy → `put-secret-value` → wait for ASG to replace the initial unhealthy instances," and give that as a numbered step in the README. Option (a) is less operationally fragile for a lab.

### 3. MEDIUM — Local-dev HLS segment fetches are cross-origin to CloudFront, but no media CORS is configured

**Where:** "Local-dev approach" ("Local playback uses signed URLs" and the claim playback is "exercised end-to-end locally"), "CloudFront + signed-cookie playback" (the `withCredentials` note asserts media is "explicitly not" a different origin).

**Problem:** The design's CORS handling covers only the FastAPI app (API responses to the SPA). In local dev the SPA runs at `http://127.0.0.1:5500` and segment URLs are CloudFront signed URLs on the `*.cloudfront.net` domain. `hls.js` fetches each `.ts` segment via XHR/fetch, so those requests are **cross-origin** and the browser requires `Access-Control-Allow-Origin` on the CloudFront/S3 media responses to let hls.js read the bytes. No CloudFront response-headers CORS policy or S3 CORS configuration is specified for the `/media/*` path. The design's own note ("media is same-origin … explicitly not our case") is true only for production; it does not hold for the local-dev vehicle the design itself introduces. Result: local playback — an explicit user requirement ("test and verify locally before deploying") — fails at the segment fetch.

**Concrete fix:** Either (a) attach a CloudFront `ResponseHeadersPolicy` with a CORS config on the `/media/*` behavior allowing the localhost dev origin (and set S3 CORS on the Output bucket), or (b) in local mode, have the local API **proxy** the segment bytes (same-origin to the SPA) instead of handing out CloudFront signed URLs — mirroring the tutorial's proxy and keeping all local fetches same-origin. State which, and note that production (same-origin) still needs none.

### 4. MEDIUM — Production playback deviates from the settled decision (signed cookies, not signed URLs) and is still unconfirmed

**Where:** "CloudFront + signed-cookie playback" callout ("flagged here for the user to confirm the cookie vehicle is acceptable"), round-2 Finding 4 / round-3 Finding 4.

**Problem:** The settled decision and the spec flag both say "CloudFront + signed URLs." The design uses signed **cookies** for production (signed URLs only in local dev). The technical justification (HLS fan-out, avoid per-URL playlist rewrite) is sound, but the design explicitly asks the user to confirm the cookie vehicle and that confirmation has not been recorded. An unconfirmed deviation from a settled decision is an open item that gates implementation — the implementer cannot know which vehicle to build.

**Concrete fix:** Get an explicit user decision and record it in the design: either (a) user confirms signed cookies for production (then remove the "to confirm" hedge and mark the decision settled), or (b) implement per-object signed URLs with a playlist rewrite in production too (as local dev already does). Until one is chosen, the playback vehicle is ambiguous.

### 5. MEDIUM — The ALB-ingress linchpin (CloudFront VPC-origin ENIs source from the private-subnet CIDRs) is an unverified claim about AWS behavior

**Where:** "VPC security groups → `alb-sg`" and round-3 Finding 1.

**Problem:** All inbound reachability to the web tier depends on one assertion: that `cloudfront.VpcOrigin` places its managed ENIs in the VPC's `PRIVATE_WITH_EGRESS` subnets and that origin-bound traffic therefore sources from IPs inside those subnet CIDRs, so a `TCP 80 from private-subnet CIDRs` rule admits CloudFront and nothing else. The design itself hedges this ("the implementable, verifiable ingress source is the private-subnet CIDR set … until then"). This is an unverified assumption about where CloudFront provisions VPC-origin ENIs and what source IPs it uses. If CloudFront places ENIs elsewhere or sources differently, the ALB is unreachable and the failure only surfaces at integration time. The design also correctly rejects the public CloudFront origin-facing prefix list (which applies to internet-facing origins, not VPC origins) — good — but that leaves the CIDR rule as the sole, unconfirmed path.

**Concrete fix:** Before implementation, confirm against the CloudFront VPC origins documentation (and/or a quick console/CLI probe in the lab account) exactly which subnets the VPC-origin ENIs land in and their source IPs; if CloudFront chooses subnets you don't control, pin the ALB and the VPC-origin subnet selection to the same explicit subnet set so the CIDR rule is provably correct. Record the verified behavior in the design so the ingress rule is a confirmed contract, not an inference. (Also verify `cloudfront.VpcOrigin` is an available L2 in the pinned `aws-cdk-lib ^2.170.0`; the version reasoning is plausible but not confirmed in this review.)

### 6. NIT — EBS volume sizing unspecified for both ASGs despite 2 GB uploads/transcodes

**Where:** "VPC layout → Web-tier ASG sizing" (`t3.small`), "Worker ASG" (`c7i.large`), "Input validation" (`MAX_UPLOAD_BYTES` default 2 GB).

**Problem:** `upload_fileobj` spools the (up to 2 GB) body to a temp file on the web instance, and the worker downloads the (up to 2 GB) raw input plus writes HLS output locally before upload. The default Amazon Linux 2023 root volume (~8 GiB) can be tight for a 2 GB spool or a 2 GB download concurrent with OS usage. `ENOSPC` is listed as a handled transient error, but a predictable disk shortage should be sized out, not retried.

**Concrete fix:** Set explicit `block_devices` on both launch templates (e.g. gp3, size ≥ `ceil(MAX_UPLOAD_BYTES) + headroom`, so ~16–20 GiB for the 2 GB cap), or lower `MAX_UPLOAD_BYTES` to match a stated volume size.

### 7. NIT — Local-dev playlist delivery is described two ways

**Where:** "Local-dev approach → Local playback uses signed URLs."

**Problem:** The text says `play-url` "returns a **CloudFront signed URL** for the playlist" and also that "the local playlist is served through a … signed-URL rewrite: the API fetches the `.m3u8`, rewrites each segment line … and returns the rewritten playlist." Those are two different delivery paths (hls.js loads the playlist from CloudFront vs. from the local API). If hls.js loads the playlist directly from CloudFront, the relative segment lines carry no signature and 403; only the API-served rewritten playlist works.

**Concrete fix:** State unambiguously that in local mode `play-url` returns a URL to the **local API's** rewritten-playlist endpoint (API-served, same origin), and the rewritten playlist's segment lines are absolute CloudFront signed URLs. Drop the "returns a CloudFront signed URL for the playlist" phrasing.

### 8. NIT — Deployed web/worker env injection mechanism not stated

**Where:** "Local-dev approach" ("resource names injected by env") and "FastAPI web tier."

**Problem:** The env-var contract (`INPUT_BUCKET`, `TABLE_NAME`, `CF_DOMAIN`, etc.) is specified for local dev, but the design never says how those env vars reach the deployed systemd service on the ASG instances (launch-template user-data writing an `EnvironmentFile`, presumably). Left implicit, an implementer may hardcode or miss a value.

**Concrete fix:** State that the launch-template user-data writes a systemd `EnvironmentFile` (or `Environment=` lines) populated from CDK-resolved references, so the deployed and local code paths read identical env vars.

---

## Hardening-scope coverage (checked against the task's checklist)

| Scope item | Addressed? | Note |
| --- | --- | --- |
| Two scoped per-server IAM roles on exact ARNs | Yes | Literal ARNs; web has upload+no-queue, worker has queue+output-write+no-upload. Asymmetry justified. |
| Worker private subnet + NAT/VPC endpoints + SSM (no SSH) | Yes | `PRIVATE_WITH_EGRESS`, gateway (S3/DDB) + interface (SQS/SecretsMgr/3×SSM) endpoints, no port 22 anywhere. |
| SQS DLQ + maxReceiveCount + idempotent worker + visibility > transcode | Yes | DLQ `maxReceiveCount=3`, visibility 900 s, worker skips if already `Ready`. |
| `Failed`-status writes | Yes | Two writers: worker on non-zero FFmpeg exit; DLQ Lambda on crash/OOM path with `attribute_exists` guard. |
| Single `video_id` derived once, passed through | Yes | `uuid4().hex` at upload; parsed from key prefix downstream; control-message guard for `s3:TestEvent`. |
| Compute-optimized worker + `scale=-2:720` + H.264 baseline + AAC + pinned FFmpeg | Yes | `c7i.large`; level corrected to 3.1 for 720p; BtbN pin + `FFMPEG.lock` + checksum prebuild. |
| ASG scale-to-zero | Yes | Step scaling, `min=0`; two disjoint alarms (backlog 0→N, idle N→0). |
| S3 lifecycle to IA/Glacier | Yes | Input `input/` → IA@30d, Glacier@90d; multipart cleanup. |
| GSI/key-based listing (no scan) | Yes | GSI `by-status-created`, `Query` newest-first, `Limit=100`. |
| Specific FastAPI exception handling + `update_item` | Yes | Per-operation exception table; `update_item` throughout; `"Item" not in response` → 404 vs `ResourceNotFoundException` → 500. |
| CloudFront signed-URL playback to private Output bucket | Partial | Private bucket + OAC + gated playback: yes. Vehicle deviates to signed **cookies** in prod (Finding 4); signer wiring incomplete (Finding 1). |
| Local-dev `config.json` approach | Partial | `config.json`/`config.local.json` + `cp` convention: yes. Segment CORS gap (Finding 3) and playlist-delivery ambiguity (Finding 7). |
| Clean-teardown removal policies + `CfnOutput`s | Yes | `DESTROY` + `autoDeleteObjects` on buckets, tables, queues, secret, log groups; ASG scales to 0; `CfnOutput`s enumerated (but missing the PublicKey id — Finding 1). |

---

## Verified Assumptions

- **Reference CDK is TypeScript, pinned `aws-cdk-lib ^2.170.0`.** Confirmed by reading `projects/clear-thinking-app/iac/package.json` (`aws-cdk-lib: ^2.170.0`, `tsconfig.json`, `lib/clear-thinking-stack.ts`). The design's "Language note" correctly flags the TS→Python translation and the version pin matches.
- **Reference app's patterns (removal policies, OAC, CfnOutputs, private S3+CloudFront).** Confirmed present in the reference README ("S3 (private, block-all-public) + CloudFront (OAC)", "one-command teardown", "CfnOutputs for the table … bucket … distribution"). The design's claim to mirror structure is accurate.
- **Spec hardening flags each map to a design section.** Cross-checked all flags in `video-streaming-app.md` (shared `*FullAccess` role, SSH `0.0.0.0/0`, no DLQ, non-idempotent worker + 30 s timeout, no `Failed` status, `put_item` overwrite, flaky FFmpeg host, `video_id` derivation mismatch, root/port-80, Flask dev server, `scan` listing, bare `except`, web-tier rebuild). Each has a concrete corresponding decision.
- **H.264 level 3.1 for 720p.** The round-2 correction is right: baseline level 3.0 caps near 720×576, so 720p needs level 3.1. Spec's Gotchas code used 3.0; the design's upgrade is a genuine fix.
- **`s3:TestEvent` has no `Records[].s3.object.key`.** Correct; the control-message guard is warranted and the spec's step-6 worker already "handle[s] `s3:TestEvent`."

## Unverified / Wrong Assumptions

- **CloudFront VPC-origin ENIs source from the private-subnet CIDRs** (Finding 5) — not verified against AWS docs in this review; it is the linchpin of all ALB ingress and the design itself hedges it.
- **`cloudfront.VpcOrigin` L2 is available in `aws-cdk-lib ^2.170.0`** — the design asserts ≥ 2.166; plausible (CloudFront VPC origins GA'd Nov 2024) but not confirmed offline here. Verify the exact construct name/signature before synth.
- **Media CORS is unnecessary** (Finding 3) — true for production (same-origin) but **wrong for the local-dev signed-URL path**, where segment fetches from CloudFront are cross-origin to the `127.0.0.1` SPA.
- **The web tier can produce a valid signing identity** (Finding 1) — assumed, but no `Key-Pair-Id` value is wired through; as written this is effectively a wrong assumption until the PublicKey id is output and injected.
- **Default EBS root volume suffices for 2 GB uploads/transcodes** (Finding 6) — implicit and unstated; likely marginal on the AL2023 default.
