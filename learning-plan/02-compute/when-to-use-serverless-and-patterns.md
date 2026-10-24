---
title: Serverless — when to use it, patterns, and functional categorization
type: note
domain: compute
date: 2026-10-23
source: "Own notes + Kiro explanation; AWS 'Workloads / Serverless' slide"
tags:
  - aws
  - serverless
  - lambda
  - fargate
  - step-functions
  - eventbridge
  - saa-c03
---

# Serverless — when to use it, patterns, and functional categorization

> Part of [[learning-plan/02-compute/02-compute|Compute]] · feeds
> [[learning-plan/10-architecting/task-2-1-scalable-loosely-coupled|SAA Task 2.1]].
> Related: [[learning-plan/02-compute/compute-options-vm-container-serverless|VM vs container vs serverless]]
> · [[learning-plan/09-containers/containers-ecs-eks-fargate|Containers]]
> · [[learning-plan/10-architecting/sns-vs-sqs-vs-eventbridge|SNS vs SQS vs EventBridge]]

> Serverless = **no servers to manage, pay-per-use, automatic scaling (incl.
> scale-to-zero), built-in HA.** It is not a single service — it's a *property*
> that spans every layer of the stack.

## Framing: serverless spans all layers → categorize functionally

"Serverless" is a discoverability label; when you actually draw an architecture,
place each service in its **functional** box (from the AWS Workloads slide):

| Functional category | Serverless services |
|---|---|
| **Compute** | AWS Lambda |
| **Containers** | AWS Fargate |
| **Application Integration** | Amazon SQS, SNS, EventBridge, Step Functions, AppSync |
| **Storage** | Amazon S3 |
| **Database** | DynamoDB, RDS Proxy, Aurora Serverless |

Takeaway: don't think "the serverless service" — think "the serverless **option**
for this layer" (serverless compute = Lambda; serverless containers = Fargate;
serverless key-value DB = DynamoDB; serverless relational = Aurora Serverless).

## When to use serverless

**Good fit**
- Variable / unpredictable / **spiky** traffic (pay nothing when idle).
- **Event-driven** work (a file lands, a message arrives, a schedule fires).
- You want **minimal ops** and fast iteration.
- Glue / integration between services.

**Poor fit (reach for containers or EC2)**
- **Steady, high-volume** constant load — always-on compute is cheaper than per-invocation.
- **Long-running** jobs beyond **Lambda's 15-min** limit (→ Fargate/EC2, or Step Functions to orchestrate).
- **Latency-sensitive** paths hurt by **cold starts** (mitigate with provisioned concurrency).
- **Specialized hardware** (GPU) or heavy stateful processing.

## Lambda limits worth memorizing

- **15-minute** max execution; memory up to **10 GB** (CPU scales with memory).
- Ephemeral `/tmp`; deployment/payload size limits; concurrency account limits.
- **Cold starts** on scale-out → **provisioned concurrency** removes them; **reserved
  concurrency** caps/guarantees a function's share.

## Serverless patterns (the ones exams/designs love)

- **Event-driven trigger** — S3 `PutObject` → Lambda (thumbnailer, ingest).
- **Queue-based load leveling** — producer → **SQS** → Lambda/worker drains at its pace.
- **Fan-out** — **SNS** (or EventBridge) → multiple SQS/Lambda consumers in parallel.
- **Routing/filtering** — **EventBridge** rules route events by content to targets.
- **Orchestration / workflows** — **Step Functions** coordinates multi-step, retriable,
  long-running flows (replaces brittle Lambda-calls-Lambda chains).
- **API backend** — **API Gateway** (or **AppSync** for GraphQL) → Lambda → DynamoDB.
- **Stream processing** — Kinesis/DynamoDB Streams → Lambda.

## Project tie-ins
- [[projects/clear-thinking-app.md|clear-thinking-app]] — fully serverless (Lambda,
  scale-to-zero) → "cost at rest ≈ $0." The textbook good-fit case.
- [[projects/video-streaming-app/DESIGN.md|video-streaming-app]] — the transcode
  worker is **not** serverless (long FFmpeg jobs, faithful EC2) — a good "poor fit"
  contrast — but its glue (S3 event → SQS → DynamoDB) is serverless app-integration.

## Exam-relevant notes

- "No servers, pay-per-use, **spiky/event-driven**" → serverless (Lambda).
- "Job runs **longer than 15 min**" → not Lambda → Fargate/EC2 or Step Functions orchestration.
- "Coordinate a **multi-step workflow** with retries" → **Step Functions**.
- "**Fan-out** one event to many consumers" → **SNS** (or EventBridge).
- "Serverless **relational** DB that scales to zero" → **Aurora Serverless**; "serverless key-value" → **DynamoDB**.
- "Cold-start latency on a critical path" → **provisioned concurrency**.
