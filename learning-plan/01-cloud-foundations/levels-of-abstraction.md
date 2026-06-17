---
title: Levels of Abstraction in AWS
type: note
domain: cloud-foundations
date: 2026-06-11
source: "Book: Amazon Web Services in Action (+ own notes)"
tags:
  - aws
  - cloud-foundations
  - abstraction
  - storage
  - compute
---

# Levels of Abstraction in AWS

> Part of [[learning-plan/01-cloud-foundations/01-cloud-foundations|Cloud Foundations]].
> Related: [[learning-plan/01-cloud-foundations/cloud-service-models|Cloud Service Models (IaaS, PaaS, SaaS)]]

AWS offers services for compute, storage, and networking at **different layers of
abstraction**. For example, you can attach a volume to a virtual machine (low level of
abstraction) or store and retrieve data via a REST API (high level of abstraction).

## What "abstraction" means

Abstraction is *how much detail the service hides from you*.

- **Low abstraction** = raw building blocks. More control and flexibility, but more work
  and responsibility (you assemble and manage the pieces).
- **High abstraction** = the machinery is hidden behind a simple interface. Less work and
  faster, but less control over the internals.

It's the same control-vs-effort trade-off as IaaS → PaaS → SaaS.

## The storage example, unpacked

**Low level — attach a volume to a VM (EBS + EC2):**
You launch a virtual machine and attach a block-storage volume — essentially a raw
virtual hard disk. To use it you format it with a filesystem, mount it, manage free
space, handle snapshots/backups, and grow it when it fills. You think in disks and
partitions, like a physical server. Maximum control, maximum responsibility.

**High level — store/retrieve data via a REST API (Amazon S3):**
You never see disks. You make a web request — `PUT` to store an object, `GET` to
retrieve it — and S3 handles where the bytes physically live, replication, durability,
and scaling automatically. You think in "objects" and "buckets," not hardware. Less
control over internals, almost no operational work.

Same job (keep my data), two very different abstraction levels.

## The pattern repeats across every category

| Category | Lower abstraction | Higher abstraction |
| --- | --- | --- |
| Storage | EBS volume (raw disk on a VM) | S3 (objects via REST API) |
| Compute | EC2 (manage the VM + OS) | Lambda (just supply a function) |
| Database | Run your own DB on EC2 | RDS (managed) → DynamoDB / Aurora Serverless |
| Containers | Run Kubernetes on EC2 | EKS/ECS → Fargate (no servers to manage) |

Moving right, AWS takes over more undifferentiated heavy lifting (provisioning,
patching, scaling, hardware), and you focus more on your application and data.

## Why an architect cares

The goal isn't "always pick the most abstracted option" — it's **matching the abstraction
level to what the workload needs**:

- Need a specific OS, kernel tuning, or licensed software? → lower abstraction (EC2/EBS).
- Want speed, less ops burden, and pay-per-use scaling? → higher abstraction
  (S3/Lambda/Fargate).

Same control-vs-effort decision behind choosing IaaS, PaaS, or SaaS.
