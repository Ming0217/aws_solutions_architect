---
title: Service-Selection Framework (requirement → AWS service)
type: note
domain: architecting
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - architecting
  - decision-framework
  - compute
  - storage
  - networking
  - databases
  - saa-c03
---

# Service-Selection Framework (requirement → AWS service)

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & best practices]] ·
> the synthesis skill behind [[learning-plan/10-architecting/task-2-1-scalable-loosely-coupled|SAA Task 2.1]].
> Related: [[learning-plan/10-architecting/requirements-gathering-checklist|Requirements-gathering checklist]]
> · [[learning-plan/10-architecting/purpose-built-services|Purpose-built services]]

> The exam rarely asks "what is service X?" It asks "given these requirements,
> **which** service?" Answer by scoring the requirement on a fixed set of
> **dimensions**, then matching to the purpose-built option.

## Step 1 — extract the dimensions from the requirement

Always read the scenario for these (from the
[[learning-plan/10-architecting/requirements-gathering-checklist|requirements checklist]]):

- **Workload pattern** — steady / spiky / batch / event-driven?
- **Latency** — ms-sensitive or tolerant?
- **Scale & throughput** — small / large / unbounded?
- **State & access pattern** — stateless? key-value, relational, graph, search, time-series?
- **Consistency & durability** — strong vs eventual; how durable?
- **Cost model** — pay-per-use (idle=0) vs steady reserved?
- **Ops tolerance** — fully managed vs hands-on control?
- **Compliance / isolation** — single-tenant, data residency, encryption needs?

## Step 2 — map to the layer

### Compute (control ↔ convenience ladder)
`Lambda → Fargate → ECS/EKS on EC2 → EC2`
- Event-driven/spiky/short → **Lambda**. Containers without servers → **Fargate**.
- Containers needing control/GPU/scale → **ECS/EKS on EC2**. Full OS/legacy/special → **EC2**.
- See [[learning-plan/02-compute/when-to-use-serverless-and-patterns|serverless]] and
  [[learning-plan/09-containers/containers-ecs-eks-fargate|containers]].

### Storage
| Need | Service |
|---|---|
| Object store, web-scale, static assets | **S3** |
| Block volume for **one** instance | **EBS** |
| Shared file system across **many** instances | **EFS** |
| High-perf / Windows / HPC file system | **FSx** |
| Ephemeral scratch, fastest | **Instance store** |
| Archive, cheapest | **S3 Glacier** tiers |

### Networking / delivery
| Need | Service |
|---|---|
| HTTP/HTTPS, path/host routing (L7) | **ALB** |
| TCP/UDP, ultra-low latency, static IP (L4) | **NLB** |
| Cache + TLS + DDoS at the edge | **CloudFront** |
| Managed REST/HTTP/WebSocket API front door | **API Gateway** |
| DNS, health-check failover, routing policies | **Route 53** |
| Private access to AWS services (no internet) | **VPC endpoints / PrivateLink** |

### Database — pick by data shape (see [[learning-plan/10-architecting/purpose-built-services|purpose-built]])
| Data shape / need | Service |
|---|---|
| Relational, familiar SQL | **RDS** / **Aurora** |
| Key-value, massive scale, single-digit ms | **DynamoDB** |
| In-memory cache / leaderboard | **ElastiCache** (Redis/Memcached) |
| Document (Mongo-compatible) | **DocumentDB** |
| Graph / relationships | **Neptune** |
| Full-text search / log analytics | **OpenSearch** |
| Time-series (IoT/metrics) | **Timestream** |
| Immutable ledger | **QLDB** |
| Data warehouse / BI | **Redshift** |

## Step 3 — apply the two Task-2.1 reflexes
Once services are chosen, sanity-check: **does each tier scale horizontally**
(stateless + ASG/auto-scaling), and **are slow/failing parts decoupled** (queue/
topic/bus)? If not, revise. See
[[learning-plan/10-architecting/task-2-1-scalable-loosely-coupled|the Task 2.1 index]].

## Worked examples from the projects
- **photoshare** — relational metadata → **RDS**; images → **S3**; async processing → **Lambda**.
- **video-streaming** — catalog/status → **DynamoDB** (key-value by `video_id`);
  media → **S3**; decoupling → **SQS+DLQ**; edge delivery → **CloudFront**; private API hop → **API Gateway**.
- **clear-thinking** — fully serverless: **Lambda** + **DynamoDB**, scale-to-zero.

## Exam-relevant notes

- Match **keywords → dimensions → service**; eliminate options that fail a hard
  requirement (latency, 15-min limit, single-instance vs shared storage) first.
- "Shared file system, many instances" → **EFS** (not EBS). "One instance, block" → **EBS**.
- "L7 path routing" → **ALB**; "L4 / static IP / extreme throughput" → **NLB**.
- Don't force one database onto every problem — that's what Task 2.1 "purpose-built" tests.
