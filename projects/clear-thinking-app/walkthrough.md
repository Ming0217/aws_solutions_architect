---
title: "Clear Thinking — Architecture Walkthrough"
type: walkthrough
domain: architecting
date: 2026-07-27
status: deployed-and-tested
okr: H2 2026 — KR4 (architecture walkthrough)
tags:
  - aws
  - walkthrough
  - architecting
---

# Clear Thinking — Architecture Walkthrough

> Companion to the build doc [[projects/clear-thinking-app|clear-thinking-app]]
> and the IaC in [`iac/`](./iac/README.md). One of the walkthroughs for **KR4**:
> explain design choices, tradeoffs, assumptions, and failure modes.
>
> **Status: Phase 1 deployed via AWS CDK and validated end-to-end on real AWS
> (2026-07-27), then torn down.** Assumptions confirmed during discovery (§3);
> failure-mode mitigations verified against the live stack. See §7 for the
> deployment + validation record (including a real CloudFormation/Cognito gotcha).
> Phase 2 hardening (§6) is the next diff.
>
> **Attribution:** the decision framework is **inspired by Shane Parrish's
> _Clear Thinking_**. Concepts are applied and credited, never reproduced — no
> book text appears in the app, prompts, or UI copy.

## 1. Summary

Clear Thinking is a private, invite-only web app for making better decisions. The
core design idea is **the human owns the judgment; the AI is a challenger on
demand**. A decision moves through a structured form — define the problem, frame
options, gather evidence, decide, write a memo — and at four specific points the
user can ask the AI to push back (argue the other side, run a premortem, force a
third option, or draft the memo).

It is a **fully serverless, event-driven** design: a static SPA on
CloudFront + S3, a CRUD API on API Gateway + Lambda + DynamoDB, and a separate
streaming Lambda that calls Amazon Bedrock and streams tokens back to the browser.
This is a deliberate contrast with [[projects/photoshare-app|PhotoShare]]'s
VPC/EC2/RDS three-tier design, so the portfolio covers both ends of the spectrum.

## 2. Design choices (why each service)

| Component | Choice | Why |
| --- | --- | --- |
| Frontend hosting | S3 (private) + CloudFront (OAC) | Cheap, scalable static hosting; no public bucket |
| Identity | Amazon Cognito (email/password + Google), invite-only | Auth-first; managed OIDC; federation without building it (see the OAuth/OIDC note) |
| API | API Gateway **HTTP API** + JWT authorizer | Validates Cognito tokens at the edge; cheaper/simpler than REST API |
| CRUD compute | Lambda (Node.js/TS) | Scale-to-zero; per-user isolation enforced in code by `sub` |
| AI compute | Lambda **Function URL** with `RESPONSE_STREAM` | Native streaming of Bedrock tokens to the browser — no WebSockets/adapter |
| Model | Amazon Bedrock (cheapest capable), `ConverseStream` | Managed models, streaming API, pay-per-token |
| Data | DynamoDB single table, per-user by `sub`, PITR + TTL | No idle cost; near-zero RPO; NoSQL breadth |
| IaC | AWS CDK (TypeScript) | One language infra+app; one-command teardown; CDK breadth |
| Observability | CloudWatch logs/metrics/alarms | Errors, latency, throttles, AI spend signals |

Fuller rationale is in [[projects/clear-thinking-app|the build doc]].

## 3. Assumptions  *(confirmed 2026-07-27 during discovery)*

Agreed via the
[[learning-plan/10-architecting/requirements-gathering-checklist|requirements checklist]]:

| Requirement | Decision | Why it matters |
| --- | --- | --- |
| **Users** | Just me + a small **invite-only private group** | Invite-only auth; no public sign-up; low volume |
| **Auth method** | Cognito **email/password + Google** federation | Two sign-in paths; sensitive data ⇒ auth-first |
| **Region** | Single region, **us-east-1** | No cross-region DR; also where Bedrock models are broadly available |
| **RPO** | **Near-zero** — losing decision notes is unacceptable | → DynamoDB **PITR** (35-day continuous backup) |
| **RTO** | Minutes acceptable | Serverless + regional managed services; no hot standby needed |
| **Deletion** | User deletes a decision ⇒ **hard-delete now**, nothing retained | Item ages out of the PITR window; "delete means gone" (documented) |
| **AI budget** | **Cheapest capable model** for now | Nova Lite/Micro vs. Claude Haiku; token caps + per-user quota |
| **Custom domain** | **Skip for v1** | Use CloudFront + Cognito default domains |
| **Runtime** | **Node.js / TypeScript** | Native Lambda response streaming for Bedrock |
| **IaC** | **AWS CDK (TypeScript)** | One-command teardown; CDK/CFN breadth |

### Explicitly out of scope for v1

- **Custom domain / ACM certificate** — default CloudFront + Cognito domains.
- **VPC / private networking** — nothing private to isolate in Phase 1 (no RDS);
  all data access is via IAM-scoped managed services.
- **Multi-region DR** — single region; DR is regional-service durability + PITR.
- **Sharing / collaboration between users** — each user's decisions are private
  to them in v1 (partitioned by `sub`).

## 4. Tradeoffs (what was chosen NOT to do, and why)

- **AI as on-demand challenger, not a chat coach.** A free-form chat coach would
  be a more "wow" demo but has unbounded token cost, is harder to guardrail
  against prompt injection, and philosophically undercuts the book's point (the
  human should own the reasoning). *Tradeoff: less open-ended, but bounded,
  guardable, and on-message.*
- **DynamoDB over RDS.** DynamoDB scales to zero (no idle cost) and adds NoSQL
  breadth, but means no ad-hoc SQL and requires up-front access-pattern design
  (single-table). *Accepted:* the access patterns here are simple and per-user.
- **Node/TS over Python.** Chosen specifically for **native Lambda response
  streaming**; Python would need API Gateway WebSockets or a Lambda Web Adapter
  to stream. *Tradeoff:* diverges from PhotoShare's Python — which is also a
  *benefit* for portfolio breadth.
- **CDK over raw CloudFormation.** More magic/abstraction than PhotoShare's hand-
  written YAML, but far less boilerplate and one-command teardown. *Tradeoff:*
  slightly less "see every resource" transparency — mitigated by reviewing
  `cdk synth` output.
- **Hard-delete (Option A) over disabling/shortening PITR (Option B).** Option A
  keeps near-zero RPO for everything *not* deleted; a deleted item still exists
  inside the PITR window until it ages out (documented honestly). Option B would
  trade away RPO to make deletes instantly unrecoverable — not worth it.
- **No VPC in Phase 1.** Simpler, cheaper, no NAT. *Tradeoff:* if a future
  feature needs private networking (e.g., a VPC-only data source), that's a
  Phase 2 change.

## 5. Failure modes  *(intended mitigations — to verify on deploy)*

| Component | If it fails… | Blast radius | Mitigation |
| --- | --- | --- | --- |
| CRUD Lambda | requests error | Contained (per request) | Stateless; retries; alarm on error rate |
| AI Lambda / Bedrock | assist unavailable | **Degraded, not down** — the app still works without AI | Graceful UI fallback; the form is fully usable without an assist |
| Bedrock throttling / cost spike | assists slow or blocked | Contained | Per-user **daily quota** + output-token caps; cheapest model |
| DynamoDB | reads/writes fail | High (core data) | Regional managed service; **PITR** for recovery; on-demand capacity absorbs spikes |
| Accidental data loss / bad write | item corrupted/deleted | Per-item | **PITR** restore (35-day window) |
| Cognito outage | can't sign in | Total (auth gate) | Regional managed service; no self-hosted auth to fail |
| CloudFront/S3 | SPA won't load | Total (frontend) | Both highly available managed services; S3 11-nines durability |
| Prompt injection via user text | model misuse | Contained | User text passed as **data, never instructions**; Phase 2 adds Bedrock Guardrails |
| Cost runaway (abuse) | bill spike | Financial | Quota counter + token caps now; **WAF + AWS Budgets** in Phase 2 |

## 6. Well-Architected mapping (feeds KR3)

| Pillar | State (Phase 1 design) | Phase 2 improvement |
| --- | --- | --- |
| Operational Excellence | IaC via **CDK**; CloudWatch logs/metrics | Dashboard + alarms; X-Ray tracing |
| Security | **Auth-first** Cognito (invite-only), private S3 (OAC), per-user data isolation by `sub`, per-Lambda least-privilege roles, no static creds | **Bedrock Guardrails**, IAM scoped to the exact model ARN, customer-managed KMS, WAF |
| Reliability | Regional managed services; DynamoDB **PITR**; AI failure is degraded-not-down | Multi-region considerations if ever needed |
| Performance Efficiency | Serverless scale-to-zero; **streaming** AI responses; on-demand DynamoDB | Tune model choice + token caps after real use |
| Cost Optimization | Cheapest model, token caps, **per-user quota**, rule-based nudges instead of LLM calls, no idle infra | **AWS Budgets** alerts; WAF rate limiting |
| Sustainability | Fully managed + scale-to-zero (no idle compute) | — |

## 7. Deployment & validation record (2026-07-27)

### How it was built and deployed

- **AWS CDK (TypeScript)**, deployed with `cdk deploy` to `us-east-1`
  (account already bootstrapped). Lambdas bundle locally via **esbuild** (no
  Docker); the SPA + a generated `config.json` ship to S3 via a CDK
  `BucketDeployment` that also invalidates CloudFront.
- **51 resources, `CREATE_COMPLETE` in ~5.5 min** (CloudFront distribution is
  the long pole). Model: **`us.amazon.nova-lite-v1:0`** (Bedrock model access
  enabled in the account first).

### Live end-to-end validation — passed

Backend paths were exercised directly (CLI + direct Lambda invokes with
synthetic authorizer claims); the browser flow (sign-in → create → assists →
memo) was confirmed manually.

| Check | Result |
| --- | --- |
| SPA + `config.json` served via CloudFront | 200, config correct |
| CRUD API without a token | **401** (Cognito authorizer enforcing) |
| AI Function URL without a token | **401** "Missing bearer token" (in-handler JWT check) |
| Cognito Hosted UI login page | 200 |
| Invite allowlist — non-allowlisted sign-up | **blocked** with the exact trigger message |
| Bedrock `ConverseStream` (Nova Lite) | responds; assists stream token-by-token in the UI |
| CRUD create → DynamoDB | 201, item persisted |
| Per-user isolation (different `sub`) | `items: []` — no cross-user reads |
| CRUD delete | 204 (hard delete) |
| Browser: sign-in → new decision → autosave → assists → reload | working |

### The one real gotcha (worth remembering)

**CloudFormation created the Cognito user pool with
`AllowAdminCreateUserOnly: true` even though the template said `false`.** That
silently **disabled self-sign-up** — the Hosted UI showed no "Sign up" link. The
*deployed* template confirmed `false` (via `get-template`), but the live resource
was `true`, so a redeploy wouldn't fix it (no diff). Fixed on the live pool with
`aws cognito-idp update-user-pool` (re-supplying the PreSignUp trigger,
auto-verify, password policy, and recovery so nothing was reset) and setting
`AllowAdminCreateUserOnly: false`. This is the Clear-Thinking analogue of
PhotoShare's MySQL-8 `caching_sha2_password` crash: **a class of bug only a live
deploy surfaces, not `cdk synth`.**

> **Reproducibility caveat:** a fresh redeploy will hit the same drift and need
> the same one-line correction. Tracked as a Phase 2 item — either a small
> custom resource that self-corrects the setting post-deploy, or a documented
> post-deploy step (see [`iac/README.md`](./iac/README.md)).

### Teardown — clean

`cdk destroy` removed the stack; verified **stack, DynamoDB, Cognito pool, and
the S3 bucket are all gone** (the bucket auto-emptied first). Our own Lambda log
groups were removed automatically because they're created explicitly with
`removalPolicy: DESTROY` — but the **two CDK-helper Lambdas** (bucket-deployment
and auto-delete-objects) left their auto-created log groups behind, which were
deleted manually. Only the shared **`CDKToolkit`** bootstrap stack and
account-level **Bedrock model access** intentionally remain (both effectively
free). Net cost at rest: ~$0.

> **Takeaway reinforced:** explicit, `DESTROY`-policied log groups clean up on
> teardown; Lambda's *auto-created* log groups (including those from CDK's own
> custom-resource helpers) linger and must be swept.

## Screenshots

Images will live in `screenshots/` once built. Planned shots:

- [ ] `01-frontend.png` — the decision form (stages)
- [ ] `02-assist-devils-advocate.png` — an AI assist streaming a rebuttal
- [ ] `03-memo.png` — generated decision memo
- [ ] `04-cognito-hosted-ui.png` — sign-in (email/password + Google)
- [ ] `05-cdk-deploy.png` — `cdk deploy` outputs
- [ ] `06-dynamodb-pitr.png` — table with PITR enabled
