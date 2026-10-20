---
title: "Project: Clear Thinking — AI-assisted decision framework"
type: project
domain: architecting
date-started: 2026-07-27
services:
  - cognito
  - dynamodb
  - lambda
  - apigateway
  - bedrock
  - s3
  - cloudfront
  - cloudwatch
  - iam
status: phase1-deployed-and-validated
tags:
  - aws
  - project
---

# Project: Clear Thinking — AI-assisted decision framework

> Related: [[projects/projects|projects index]] ·
> [architecture walkthrough](./clear-thinking-app/walkthrough.md) ·
> [IaC](./clear-thinking-app/iac/README.md)
> Design source: **inspired by Shane Parrish's _Clear Thinking_** (the decision
> framework — separating the moment of decision from the moment of reaction,
> defining the problem before solving it, seeking disconfirming views). Concepts
> are *attributed and applied*, not reproduced — no book text is copied into the
> app, prompts, or UI copy.
> Part of the [H2 2026 AWS OKR](../README.md) — Project #2 of 3 for **KR2**
> (working project), and it also feeds **KR1** (documented architecture),
> **KR3** (Well-Architected), and **KR4** (walkthrough).

> **Update 2026-07-27 — Phase 1 deployed, validated, and torn down.** The full
> serverless app was deployed via CDK to real AWS, validated end-to-end (see the
> [walkthrough §7](./clear-thinking-app/walkthrough.md)), and cleanly destroyed
> (verified nothing lingers). A real CloudFormation/Cognito gotcha
> (`AllowAdminCreateUserOnly` not applied) was found and fixed on the live pool.
> Phase 2 hardening is the next step.

> **Status 2026-07-27 — design settled, scaffolding in progress.** Requirements
> discovery is complete (see the [walkthrough](./clear-thinking-app/walkthrough.md)
> §3). This is a **greenfield serverless build** (contrast with PhotoShare's
> VPC/EC2/RDS design) so the portfolio spans both a classic 3-tier app and a
> fully serverless, event-driven, AI-integrated one.

## Use case / goal

A private, invite-only web app that helps a small group make better decisions by
walking a decision through a **structured form** (define the problem → frame
options → gather evidence → decide → write a memo), and letting an AI **challenge
the thinking on demand** at specific points. The AI does not decide for you and
is not an open-ended chat coach — **you drive; the AI pushes back** where that
adds the most value.

### Where the AI earns its place (the 4 assists)

| Assist | What it does | Book idea behind it |
| --- | --- | --- |
| **Devil's advocate** | Argues the strongest case *against* your leading option | Know the other side better than they do |
| **Premortem** | "Assume this failed — here's how" — surfaces blind spots | Imagining failure before it happens |
| **Force a third option** | If you entered only two options, generates a genuine third | The "3+ options" principle |
| **Generate the memo** | Summarizes your inputs into the structured decision memo | Writing forces clarity |

Everything else (progress nudges, "you only listed one option", "no downside
recorded") is **rule-based UI**, not an LLM call — cheaper, instant, and keeps
model spend tied to the moments that matter.

## Architecture (Phase 1 — serverless, no VPC)

```
                          ┌──────────────┐
        user ──────────►  │  CloudFront   │  (SPA: HTML/JS/CSS)
                          └──────┬───────┘
                                 │  static assets
                                 ▼
                          ┌──────────────┐
                          │  S3 (private) │  OAC only, block all public
                          └──────────────┘

        user (with Cognito JWT)
          │
          ├──► API Gateway (HTTP API) ──JWT authorizer──► Lambda (CRUD)
          │           └── /decisions  (create/read/update/delete)      │
          │                                                            ▼
          │                                                  DynamoDB (single table,
          │                                                  per-user by Cognito sub,
          │                                                  PITR 35-day, TTL)
          │
          └──► Lambda Function URL (RESPONSE_STREAM) ──► Amazon Bedrock
                      the 4 AI assists                    (ConverseStream,
                      stream tokens back to the browser    cheapest capable model)

        Amazon Cognito (email/password + Google federation, invite-only)
          └── PreSignUp Lambda trigger enforces an allowlist

        CloudWatch (logs, metrics, alarms)   IAM (per-Lambda least-privilege roles)
```

## Design decisions & tradeoffs

Full rationale + rejected alternatives are in the
[walkthrough](./clear-thinking-app/walkthrough.md) §2 and §4. Summary:

- **AI role — "you drive, AI challenges on demand"** (structured form + 4
  on-demand assists), **not** a chat coach. *Why:* aligns with the book's
  philosophy (the human owns the judgment), bounds cost, and makes guardrails
  tractable. *Rejected:* open chat coach (unbounded cost, weaker guardrails,
  philosophically off).
- **Auth-first — Amazon Cognito**, email/password **+ Google** federation,
  **invite-only** (self-signup disabled; a PreSignUp trigger checks an
  allowlist). *Why:* decision notes are sensitive; auth is not deferrable here
  (contrast PhotoShare, which deferred auth). 
- **Datastore — DynamoDB**, single table, partitioned per user by Cognito `sub`.
  *Why:* no idle cost (pay-per-request), scales to zero, and adds NoSQL breadth
  to the portfolio. *Rejected:* RDS (idle cost; PhotoShare already covers RDS).
- **Durability — DynamoDB PITR** (35-day continuous backup) for near-zero RPO.
  **Deletion = hard-delete** from the live table immediately; the item then ages
  out of the PITR window naturally (documented so "delete means gone" is honest).
- **Runtime — Node.js / TypeScript.** *Why:* native **Lambda response streaming**
  via Function URLs, so Bedrock tokens stream to the browser without API Gateway
  WebSockets or a Lambda Web Adapter. Adds TS breadth (PhotoShare is Python).
- **IaC — AWS CDK (TypeScript).** *Why:* one language across infra + app, and it
  adds CDK + synthesized-CloudFormation breadth (PhotoShare is raw CloudFormation).
  **Teardown is one command** — see below.
- **Model — cheapest capable Bedrock model** (evaluate Amazon Nova Lite/Micro vs.
  Claude Haiku at build time), called via **ConverseStream**, with output token
  caps. User-entered text is treated as **untrusted data, never instructions**.
- **Region us-east-1**, serverless (no VPC in Phase 1 — nothing private to
  isolate), **custom domain skipped for v1** (CloudFront + Cognito default domains).

## Cost guardrails

- **Cheapest capable model** + **max output-token caps** per assist.
- **Per-user daily quota counter** in DynamoDB (atomic increment + TTL) to cap
  AI calls per day per user.
- **Rule-based UI nudges** instead of LLM calls wherever a prompt doesn't need a
  model.
- Phase 2 adds **AWS Budgets** alerts and **WAF** rate limiting.
- Everything is **pay-per-use / scale-to-zero** (no RDS, no NAT, no idle EC2), so
  cost at rest is ~$0 aside from tiny fixed items (see teardown note on KMS).

## Teardown (why CDK makes this clean)

`cdk destroy` deletes the CloudFormation stack CDK manages, in one command. The
stack **bakes in clean-teardown** so stateful resources actually go (CDK retains
them by default):

- **S3 site bucket:** `removalPolicy: DESTROY` + `autoDeleteObjects: true`
  (empties the bucket first, so delete doesn't fail on a non-empty bucket).
- **DynamoDB / Cognito:** explicit `removalPolicy: DESTROY`.
- **Lambda log groups:** created explicitly with retention so they're
  stack-managed and deleted (Lambda's auto-created log groups are a classic
  orphan).

**Intentionally / necessarily lingers** (documented in the
[iac README](./clear-thinking-app/iac/README.md) verify checklist):

- **Customer-managed KMS key** (Phase 2 only): AWS enforces a 7–30 day *scheduled*
  deletion window; can't be destroyed instantly. Negligible cost.
- **CDK bootstrap stack** (`CDKToolkit` + its assets bucket): one-time,
  per-account/region, shared across CDK projects — left in place; effectively free.
- **Bedrock model access** is account-level enablement, not a stack resource —
  nothing to tear down.

## Status & next steps

- [x] Requirements discovery complete (walkthrough §3)
- [x] Architecture designed (Phase 1 faithful → Phase 2 hardened)
- [x] Project scaffold + CDK infra-shell (DynamoDB, Cognito, S3+CloudFront) that
      synthesizes
- [x] CRUD Lambda + HTTP API with a Cognito user-pool authorizer (create/read/
      update/delete decisions, per-user isolation by `sub`, hard-delete) — synth
      + `tsc` verified
- [x] AI streaming Lambda (Function URL, RESPONSE_STREAM) + Bedrock
      ConverseStream + the 4 assist prompts (original wording; user text handled
      as untrusted data); in-handler Cognito JWT verification — synth + `tsc` verified
- [x] Invite-only auth: email/password + PreSignUp allowlist trigger (the invite
      gate; allowlist via config, seeded with the owner's email). Google
      federation staged behind config — flips on when a Google OAuth client
      id/secret (secret in Secrets Manager) is supplied. synth + `tsc` verified
- [x] Frontend SPA — evolved the existing decision-framework HTML: kept the
      7-stage form + memo + local autosave, layered on Cognito Hosted-UI auth
      (Auth Code + PKCE), cloud persistence via the CRUD API (new/open/save/
      delete), and the four AI assists streamed from the Function URL. Deployed
      to S3+CloudFront via CDK `BucketDeployment` with a generated `config.json`.
      synth + `tsc` verified
- [x] Cost guardrails — per-user daily quota (atomic DynamoDB counter + TTL,
      fail-closed, returns 429 over cap; default 25/day, `-c dailyQuota=`),
      per-assist output-token caps; CloudWatch dashboard + 3 alarms (AI errors,
      CRUD errors, API 5xx). synth + `tsc` verified
- [x] Deployed to real AWS (us-east-1), validated end-to-end (auth boundaries,
      invite allowlist, Bedrock streaming, CRUD + per-user isolation, browser
      sign-in → assists), then **torn down clean** — verified nothing lingers.
      One real CloudFormation/Cognito gotcha found + fixed (see walkthrough §7)
- [ ] Phase 2 hardening (Bedrock Guardrails, WAF, customer-managed KMS, Budgets,
      + self-correct the Cognito self-signup setting so redeploys need no manual fix)

## Walkthrough summary

Clear Thinking is a private, invite-only serverless web app that structures a
decision (define → frame → evidence → decide → memo) and lets an AI challenge the
thinking on demand at four points (devil's advocate, premortem, force a third
option, generate the memo) — the human keeps the judgment. Auth-first with Cognito
(email/password + Google, invite-only), per-user data in DynamoDB (PITR for
near-zero RPO), AI via Bedrock streamed to the browser through a Lambda Function
URL, all fronted by CloudFront + S3. Built with **AWS CDK (TypeScript)**, fully
serverless (no VPC, scale-to-zero), cost-guarded, and torn down with a single
`cdk destroy`.
