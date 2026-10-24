---
title: Scaling Strategies (vertical vs horizontal, ASG policies, DB autoscaling)
type: note
domain: compute
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - compute
  - scaling
  - auto-scaling
  - asg
  - dynamodb
  - aurora
  - saa-c03
---

# Scaling Strategies

> Part of [[learning-plan/02-compute/02-compute|Compute]] · feeds
> [[learning-plan/10-architecting/task-2-1-scalable-loosely-coupled|SAA Task 2.1]].
> Related: [[learning-plan/10-architecting/stateless-compute-shared-state|Stateless compute & shared state]]
> · [[learning-plan/10-architecting/sqs-decoupling-and-dlq|SQS + DLQ]]

> One-liner: **prefer horizontal scaling (add copies) over vertical (bigger box)**,
> and the thing that makes horizontal possible is **statelessness**. "Scaling
> strategy" questions are usually really "is this component stateless, and what
> metric drives the scaling?"

## Vertical vs horizontal

| | Vertical (scale up/down) | Horizontal (scale out/in) |
|---|---|---|
| Move | Bigger/smaller instance type | More/fewer instances |
| Ceiling | Hard limit (max instance size) | Near-unbounded |
| Downtime | Usually a restart/resize | None (add/remove behind an ELB) |
| HA benefit | None (still one box) | Yes (spread across AZs) |
| Needs | Nothing special | **Stateless** components + a load balancer |

Default to **horizontal** for elasticity and availability; use **vertical** for a
single hard-to-split component (e.g., an RDS **writer**, which scales reads via
replicas but writes mostly vertically).

## EC2 Auto Scaling — pick the right policy

An **Auto Scaling Group (ASG)** keeps a desired count across AZs and replaces
unhealthy instances. The scaling policy decides *when* to change count:

| Policy | When to use |
|---|---|
| **Target tracking** | Default choice — keep a metric at a target (e.g., CPU 50%, or ALB requests/target). Simplest. |
| **Step scaling** | Different-sized adjustments based on how badly an alarm is breached. |
| **Simple scaling** | Legacy — one adjustment + cooldown. Avoid for new work. |
| **Scheduled scaling** | Known time patterns (business hours, nightly batch). |
| **Predictive scaling** | ML forecasts cyclical load and scales **proactively** (ahead of the spike). |

- **Dynamic (target/step)** reacts to live metrics; **scheduled** is time-based;
  **predictive** forecasts. Combine predictive + dynamic for cyclical + surprise load.
- **Warm pools** pre-initialize instances for faster scale-out of slow-booting AMIs.
- Health checks (EC2 + ELB) let the ASG cull and replace bad instances → this is
  also your self-healing / availability mechanism.

## Buffer instead of scale: queue-based load leveling

Scaling isn't the only answer to spikes. Put an **SQS queue** in front of workers
so a 10× burst becomes queue depth, not dropped requests; workers drain at their
own rate, and the ASG scales on **queue depth / backlog-per-instance**. This is
exactly the [[learning-plan/10-architecting/sqs-decoupling-and-dlq|video-app worker]]
(queue-depth scaling, scale-to-zero when idle).

## Scaling the data tier

- **DynamoDB** — **on-demand** (auto, pay-per-request, spiky/unknown) or
  **provisioned + auto scaling** (target utilization %, steadier/cheaper at scale).
- **Aurora** — up to **15 read replicas**; **Aurora Auto Scaling** adds/removes
  replicas on load; **Aurora Serverless v2** scales capacity (ACUs) finely and fast.
- **RDS** — **read replicas** scale **reads**; **storage autoscaling** grows disk;
  **writes** scale **vertically** (bigger instance) or by sharding at the app layer.
- **ElastiCache** — scale out with shards (Redis cluster mode) / nodes.
- **Lambda** — scales concurrency automatically; use **reserved concurrency** to cap
  and **provisioned concurrency** to kill cold starts for latency-sensitive paths.

## Stateful vs stateless (the hinge)

Horizontal scaling **requires** that any instance can serve any request → keep
instances **stateless** and push state to a shared store (DynamoDB, ElastiCache,
S3). See [[learning-plan/10-architecting/stateless-compute-shared-state|the stateless note]].
Sticky sessions are a crutch, not a strategy.

## Exam-relevant notes

- "Scale a **stateless web tier**" → **ASG + ELB**, target-tracking on CPU/requests.
- "Handle **predictable** daily/weekly peaks" → **scheduled** (or **predictive**) scaling.
- "Absorb an **unpredictable spike** without dropping work" → **SQS** buffer + scale on queue depth.
- "Scale **reads** on a relational DB" → **read replicas** (Aurora/RDS).
- "Spiky, unknown DB traffic, no capacity planning" → **DynamoDB on-demand** / **Aurora Serverless**.
- "Can't scale out because session is on the instance" → **externalize state** first.
