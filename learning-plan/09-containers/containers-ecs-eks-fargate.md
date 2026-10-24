---
title: Containers — when to use them, and ECS vs EKS vs Fargate
type: note
domain: containers
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - containers
  - ecs
  - eks
  - fargate
  - compute
  - saa-c03
---

# Containers — when to use them, and ECS vs EKS vs Fargate

> Part of [[learning-plan/09-containers/09-containers|Containers]] · feeds
> [[learning-plan/10-architecting/task-2-1-scalable-loosely-coupled|SAA Task 2.1]].
> Related: [[learning-plan/02-compute/compute-options-vm-container-serverless|VM vs container vs serverless]]
> · [[learning-plan/02-compute/when-to-use-serverless-and-patterns|Serverless: when + patterns]]

> Two separate decisions, often conflated:
> 1. **Should I use containers at all?** (vs plain EC2, vs Lambda)
> 2. **If yes: which orchestrator (ECS vs EKS) and which launch type (Fargate vs EC2)?**

## Decision 1 — containers vs the alternatives

Think of a **control ↔ convenience** ladder:

```
EC2 (VM)  →  Containers (ECS/EKS)  →  Lambda (serverless functions)
most control                              least ops, most constraints
```

- **Use containers when** you want consistent packaging/portability, microservices,
  faster startup than a VM, long-running or always-on services, custom runtimes,
  or you're migrating an already-containerized app.
- **Prefer Lambda instead when** the work is short (≤15 min), event-driven, and
  spiky — you want zero idle cost and no infra. (See the serverless note.)
- **Prefer plain EC2 instead when** you need full OS control, specialized/legacy
  software, or GPU/instance specifics and don't want an orchestration layer.

## Decision 2a — ECS vs EKS (the orchestrator)

| | **ECS** | **EKS** |
|---|---|---|
| What | AWS-proprietary orchestrator | Managed **Kubernetes** |
| Complexity | Lower — AWS-native, fewer moving parts | Higher — full k8s to learn/operate |
| Portability | AWS-locked | Portable / multi-cloud, huge k8s ecosystem |
| Cost | No control-plane fee | **Control-plane hourly fee** per cluster |
| Pick when | You want the **simplest AWS-native** orchestration | You **already use k8s**, need its ecosystem, or multi-cloud |

Hook: **"already on Kubernetes / need portability"** → EKS. **"just run containers on AWS simply"** → ECS.

## Decision 2b — Fargate vs EC2 launch type (who runs the servers)

Both ECS and EKS can run tasks/pods on **either** launch type:

| | **Fargate** | **EC2 launch type** |
|---|---|---|
| Servers | **None to manage** (serverless containers) | You manage the EC2 instances |
| Scaling | Per-task, automatic | You scale the instance fleet (ASG) |
| Cost | Pay per task vCPU/mem; great for variable/bursty | Cheaper at **steady high utilization**; reserved/spot |
| Control | Limited (no GPU in most cases, no privileged, no daemonsets) | Full — GPU, special instances, host access |
| Pick when | Don't want to manage servers; variable load | Need special hardware, max control, or cost at scale |

Hook: **"don't want to manage servers"** → Fargate. **"need GPU / host control / cheapest at steady scale"** → EC2 launch type.

## Project tie-in
The [[projects/video-streaming-app/DESIGN.md|video-streaming-app]] explicitly
**considered Fargate and rejected it**, staying faithful to a hardened **EC2 +
FFmpeg worker** (control over the media toolchain, long transcode jobs, cost at
the chosen instance). That rejection rationale is a model answer for "when NOT
Fargate." The [[projects/clear-thinking-app.md|clear-thinking-app]] went the other
way — fully serverless, no containers — because its workload is spiky and event-driven.

## Exam-relevant notes

- "Run containers **without managing servers**" → **Fargate** (on ECS or EKS).
- "Team already uses **Kubernetes** / needs portability" → **EKS**.
- "Simplest way to run containers on AWS" → **ECS**.
- "Containers needing **GPUs** or special instances / cheapest at steady scale" → **ECS/EKS on EC2**.
- "Short, event-driven, spiky, no infra" → not containers → **Lambda**.
