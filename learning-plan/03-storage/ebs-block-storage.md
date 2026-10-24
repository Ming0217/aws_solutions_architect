---
title: EBS — Block Storage (volume types, IOPS/throughput, snapshots)
type: note
domain: storage
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - storage
  - ebs
  - block-storage
  - snapshots
  - gp3
  - io2
  - saa-c03
---

# EBS — Block Storage

> Part of [[learning-plan/03-storage/03-storage|Storage]] · the **block** leg of
> [[learning-plan/03-storage/object-block-file-storage|object vs block vs file]].
> Related: [[learning-plan/03-storage/network-filesystem|Network filesystem (EFS)]]
> · [[learning-plan/02-compute/scaling-strategies|Scaling strategies]]

> **Elastic Block Store = a virtual hard disk for one EC2 instance.** It's
> network-attached (not physically in the host), lives in **one AZ**, and
> **persists independently** of the instance's lifecycle (unlike instance store).
> The OS puts a filesystem on it and reads/writes **blocks** in place.

## Core facts

- **AZ-scoped** — a volume attaches only to instances **in its AZ**. To move it to
  another AZ/region, take a **snapshot** and restore there.
- **One instance at a time** — except **Multi-Attach** (io1/io2 only, same AZ, up to
  16 instances, and only with a **cluster-aware filesystem**; not for ext4/xfs).
- **Persists** across stop/start; survives instance termination if "delete on
  termination" is off. (Contrast **instance store** = ephemeral, gone on stop.)
- **Encryption** via KMS — encrypts data at rest on the volume, data **in transit**
  between instance and volume, and all snapshots. Enable at creation.

## Volume types (pick by IOPS vs throughput vs cost)

| Type | Media | Strength | Use when |
|---|---|---|---|
| **gp3** | SSD | General, cheap; **IOPS/throughput decoupled from size** | Default for most workloads, boot volumes |
| **gp2** | SSD | General (IOPS scale with size) | Legacy; prefer gp3 |
| **io1 / io2** | SSD | **Provisioned IOPS**, high & consistent; io2 more durable | I/O-intensive databases |
| **io2 Block Express** | SSD | **Highest** IOPS/throughput, largest | Largest, most demanding DBs |
| **st1** | HDD | High **sequential throughput**, cheap | Big data, logs, streaming reads (not boot) |
| **sc1** | HDD | **Cheapest**, cold | Infrequent access (not boot) |

Rough ceilings (know the *shape*, not exact digits): **gp3** ~3,000 IOPS / 125 MiB/s
baseline, provisionable to ~16,000 IOPS / 1,000 MiB/s; **io2** to ~64,000 IOPS (more
with Block Express); HDD types max out on **throughput**, not IOPS; HDD (`st1`/`sc1`)
**can't be boot volumes**.

## IOPS vs throughput (the distinction questions hinge on)

- **IOPS** = operations/second → matters for **small, random** I/O (transactional DBs)
  → SSD (`gp3`, `io2`).
- **Throughput** = MB/s → matters for **large, sequential** I/O (log processing, big
  scans) → HDD (`st1`) or S3.

`gp3`'s headline feature: you dial **IOPS and throughput independently of capacity**,
so you don't over-buy disk just to get performance (the `gp2` trap).

## Snapshots

- **Incremental** backups stored in **S3** (AWS-managed, you don't see the bucket);
  only changed blocks after the first.
- Used for **backup**, **cross-AZ/region copy** (copy a snapshot, restore a volume),
  and baking **AMIs**.
- Restoring creates a **new volume** (optionally in another AZ) — this is how you
  effectively "move" or "resize across AZ."

## Scaling an EBS volume

**Elastic Volumes** — grow size, change type, or adjust IOPS/throughput **online**
(no detach), then extend the filesystem in the OS. Write performance still scales
**vertically** here; to scale reads on a DB, use **read replicas**, not a bigger volume.

## EBS vs instance store vs EFS (quick contrast)

| | **EBS** | **Instance store** | **EFS** |
|---|---|---|---|
| Persistence | Independent, durable | **Ephemeral** (lost on stop) | Durable, managed |
| Attach | One instance (AZ) | The one host | **Many** instances |
| Latency | Low | **Lowest** (local) | Network (higher) |
| Use | Boot, DBs | Scratch/cache | Shared files |

## Project tie-in
The [[projects/video-streaming-app/DESIGN.md|video-streaming-app]] put **gp3** block
devices on both the web and worker launch templates — boot + local transcode scratch —
a textbook general-purpose block use (no provisioned-IOPS need, so `gp3` over `io2`).

## Exam-relevant notes

- "Database needing **consistent high IOPS**" → **io1/io2** (Block Express for the largest).
- "General boot/app volume, cost-efficient" → **gp3** (decoupled IOPS/throughput).
- "Big **sequential throughput** cheaply" → **st1**; "cold/cheapest" → **sc1** (neither boots).
- "Move/copy a volume across AZ or region" → **snapshot** then restore/copy.
- "Share one volume across many instances" → usually **wrong** → use **EFS**; Multi-Attach only for clustered FS on io1/io2.
- "Ephemeral/fastest local disk, data loss OK" → **instance store**.
