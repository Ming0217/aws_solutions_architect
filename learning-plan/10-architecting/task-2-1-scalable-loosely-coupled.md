---
title: "SAA Task 2.1 — Design Scalable & Loosely Coupled Architectures (index)"
type: moc
domain: architecting
date: 2026-10-23
source: "AWS SAA-C03 exam guide, Domain 2 Task 2.1 + own notes"
tags:
  - aws
  - architecting
  - saa-c03
  - domain-2
  - scaling
  - decoupling
  - serverless
  - containers
  - index
---

# SAA Task 2.1 — Design Scalable & Loosely Coupled Architectures

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & best practices]].
> This is the **index** for SAA-C03 Domain 2, Task statement 2.1 — it maps each
> exam focus area to the decision criteria, the note that covers it, and the
> project that proves it.

**The task in one line:** given requirements, pick components and wire them so the
system **scales** (handles more load gracefully) and is **loosely coupled**
(parts fail/scale independently). Two capabilities the whole task tests:
**horizontal scaling** and **decoupling**.

## The seven focus areas → where to study each

| # | Focus area | Decision criteria (one line) | Note(s) | Proven in |
|---|---|---|---|---|
| 1 | **Event-driven / microservice / multi-tier** | Separate tiers; communicate via events/queues when work is async | [[learning-plan/10-architecting/what-is-decoupling-first-principles\|decoupling first-principles]] · [[learning-plan/10-architecting/decoupling-sync-vs-async\|sync vs async]] | video-streaming-app (event-driven), photoshare (multi-tier) |
| 2 | **Scaling strategies** | Horizontal > vertical; stateless + ASG; pick the right scaling policy | [[learning-plan/02-compute/scaling-strategies\|scaling strategies]] | video-app worker ASG (queue-depth, scale-to-zero) |
| 3 | **Loose coupling (which services)** | Queue for buffering, topic for fan-out, bus for routing | [[learning-plan/10-architecting/sns-vs-sqs-vs-eventbridge\|SNS vs SQS vs EventBridge]] · [[learning-plan/10-architecting/sqs-decoupling-and-dlq\|SQS + DLQ]] | video-app (SQS+DLQ) |
| 4 | **When to use containers** | Need packaging/portability; ECS (AWS-native) vs EKS (k8s) vs Fargate (no servers) | [[learning-plan/09-containers/containers-ecs-eks-fargate\|containers: ECS/EKS/Fargate]] | video-app (considered + rejected Fargate) |
| 5 | **When to use serverless + patterns** | Spiky/event-driven, scale-to-zero, minimal ops; mind the limits | [[learning-plan/02-compute/when-to-use-serverless-and-patterns\|serverless: when + patterns]] | clear-thinking-app (fully serverless) |
| 6 | **Recommend compute/storage/net/db** | Map requirement → purpose-built service on fixed dimensions | [[learning-plan/10-architecting/service-selection-framework\|service-selection framework]] | all three projects |
| 7 | **Purpose-built services** | Right tool for the job; don't force one DB onto every problem | [[learning-plan/10-architecting/purpose-built-services\|purpose-built services]] | video (DynamoDB) · photoshare (RDS) |

## The two reflexes to build

1. **"How does this scale?"** → default to **horizontal** (add instances), which
   requires **stateless** components ([[learning-plan/10-architecting/stateless-compute-shared-state|stateless compute]]).
   State goes to a shared store (DynamoDB/ElastiCache/S3), not the instance.
2. **"What happens when a part is slow or dies?"** → **decouple** it behind a
   queue/topic/bus so the rest keeps working ([[learning-plan/10-architecting/what-is-decoupling-first-principles|decoupling]]).

Both reflexes trace back to the [[learning-plan/10-architecting/requirements-gathering-checklist|requirements checklist]]:
you can't choose until you know the workload pattern, latency, scale, state, and cost model.

## Self-quiz (revisit for option A — the diagnostic)

- An image-processing job spikes 10× at unpredictable times. How do you absorb the
  spike without over-provisioning? (→ queue-based load leveling + ASG/Lambda)
- A web tier stores session in instance memory and can't scale out. What's the fix?
  (→ externalize state; stateless + ELB)
- When would you pick ECS over EKS? EKS over ECS? Fargate over EC2 launch type?
- When is Lambda the wrong choice? (→ >15 min, steady high volume, cold-start-sensitive, special hardware)
- Pick a database for: a shopping cart; a social graph; full-text search; a time-series metrics feed.
- Fan-out the same event to 3 independent consumers — which service, and why not the others?

> Next steps (deferred): **A** = run the diagnostic quiz against these; **C** =
> deep-dive one note. Both noted for later.
