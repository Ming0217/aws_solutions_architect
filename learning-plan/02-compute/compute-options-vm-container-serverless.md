---
title: Compute Options — VMs vs Containers vs Serverless
type: note
domain: compute
date: 2026-06-17
source: "Book: Amazon Web Services in Action (compute chapter) + own notes"
tags:
  - aws
  - compute
  - ec2
  - containers
  - ecs
  - eks
  - fargate
  - lambda
  - serverless
---

# Compute Options — VMs vs Containers vs Serverless

> Part of [[learning-plan/02-compute/02-compute|Compute]].
> Related: [[learning-plan/01-cloud-foundations/levels-of-abstraction|Levels of Abstraction]]
> · [[learning-plan/01-cloud-foundations/cloud-service-models|Cloud Service Models]]
> · [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|Connecting to EC2]]
> · [[learning-plan/10-architecting/decoupling-sync-vs-async|Decoupling (sync vs async)]]

## The model

> At a fundamental level, three compute options exist: **virtual machines (VMs)**,
> **container services**, and **serverless**.

The real insight: these aren't three separate boxes — they're points on **one spectrum**
of *how much of the stack you manage vs. how much AWS manages*. It's
[[learning-plan/01-cloud-foundations/cloud-service-models|IaaS → CaaS → FaaS]] made
concrete.

```
You manage MORE  ◄──────────────────────────────────►  AWS manages MORE
   VMs (EC2)            Containers (ECS/EKS)          Serverless (Lambda)
   ─────────           ──────────────────             ──────────────────
 OS, patching,         app + container image,         just your code
 scaling, capacity     orchestration choices          (+ config)
```

Move **right** → hand off more (OS, patching, scaling, capacity) to AWS, in exchange for
**less control + tighter constraints**. The whole tradeoff = **control vs. operational
burden**.

## The three types on AWS

### 1. Virtual machines — EC2

- Rent a virtual server: full OS access, install anything, long-running.
- **You** own OS, patching, scaling, capacity. Most control, most work.
- This is *why* concerns like SSH and IPs exist (see
  [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|EC2 connectivity]] and
  [[learning-plan/04-networking/elastic-ip-addresses|Elastic IPs]]) — you manage the box.
- **Use when:** legacy / lift-and-shift, specific OS/kernel/software, long-running stateful
  workloads, need full control.

### 2. Containers — ECS / EKS

- Package app + dependencies into a portable **image**; AWS runs and orchestrates them.
- Two orchestrators: **ECS** (AWS-native, simpler) and **EKS** (managed Kubernetes,
  portable/standard).
- **Launch type** sub-choice: **EC2 launch type** (you still manage host VMs) vs.
  **Fargate** (serverless containers — no hosts). This is why containers sit in the middle
  but blur toward serverless with Fargate.
- **Use when:** microservices, want portability + consistent environments, already
  containerized, need higher packing density / faster startup than VMs.

### 3. Serverless — Lambda (+ Fargate)

- Deploy just **code** (a function); AWS handles all servers, scaling, capacity. Scales to
  zero, pay per invocation/duration.
- Most constraints: execution-time limits, statelessness, cold starts, runtime limits.
- **Use when:** event-driven, spiky/unpredictable traffic, glue between services, want to
  manage nothing. Pairs with [[learning-plan/10-architecting/decoupling-sync-vs-async|async
  decoupling]] (Lambda triggered off SQS/SNS/S3 events).

## Decision heuristic

| Question | Lean toward |
| --- | --- |
| Need full OS control / specific software / legacy app? | **EC2 (VM)** |
| Want portability, microservices, consistent envs? | **Containers (ECS/EKS)** |
| Event-driven, spiky, want zero infra management? | **Serverless (Lambda)** |
| Using containers but "don't want to manage hosts" | **Fargate** (serverless containers) |

> **Common modern default:** start **serverless**, drop to **containers** when you outgrow
> its constraints, drop to **EC2** only when you need real control. Move left only when
> something forces you to.

## The nuance the "three types" model glosses over

**Fargate proves it's a spectrum, not three boxes** — it's serverless *compute* running
*containers*, sitting between the middle and the right. Don't over-rigidify the
categories; the real axis is always **"how much do I want to manage?"**

## Quick recall

| Term | Service(s) | You manage | AWS manages |
| --- | --- | --- | --- |
| VM | **EC2** | OS, patching, scaling, capacity | Hardware, hypervisor |
| Container | **ECS / EKS** (on EC2 or Fargate) | App image, orchestration config | Control plane (+ hosts if Fargate) |
| Serverless | **Lambda** (Fargate for containers) | Just code + config | Everything else |
