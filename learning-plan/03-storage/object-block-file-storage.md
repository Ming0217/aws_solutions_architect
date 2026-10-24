---
title: Object vs Block vs File Storage (the storage decision framework)
type: note
domain: storage
date: 2026-10-23
source: "Own notes + Kiro explanation; AWS SAA-C03 Domain 3.1 slides"
tags:
  - aws
  - storage
  - s3
  - ebs
  - efs
  - fsx
  - object
  - block
  - file
  - saa-c03
---

# Object vs Block vs File Storage

> Part of [[learning-plan/03-storage/03-storage|Storage]] · the canonical framework for
> SAA-C03 **Domain 3.1** (determine storage that meets **performance** and **future-scale** needs).
> Related: [[learning-plan/03-storage/s3-core-concepts|S3 core concepts]] (object)
> · [[learning-plan/03-storage/ebs-block-storage|EBS block storage]] (block)
> · [[learning-plan/03-storage/network-filesystem|Network filesystem]] (file)
> · [[learning-plan/10-architecting/service-selection-framework|Service-selection framework]]

> The one discriminator that resolves most storage questions:
> **how is the data accessed and shared?**
> - Accessed by an **API** over HTTP, whole blobs → **Object (S3)**
> - Attached to **one instance** as a raw disk the OS mounts → **Block (EBS)**
> - **Mounted by many instances** as a shared filesystem → **File (EFS/FSx)**

## The three paradigms

| | **Object — S3** | **Block — EBS** | **File — EFS / FSx** |
|---|---|---|---|
| What it is | Blobs (data + metadata + key) in a flat bucket | Raw virtual disk; OS formats & mounts it | Shared filesystem over the network |
| Accessed via | **HTTP REST API** | **Attach** → mount on the instance | **Network mount** (NFS / SMB) |
| Shared by | Many clients via API | **One** instance (io2 multi-attach = niche) | **Many** instances at once |
| Update granularity | Replace the **whole object** | **Block/byte-level** in place | **File-level** |
| Scope | Regional bucket, global namespace | **Single AZ** (snapshot → S3 to move) | Regional, multi-AZ (EFS) |
| Scale ceiling | Effectively **unlimited** | Per-volume (to 64 TiB) | Elastic to petabytes |
| Typical use | Assets, backups, data lake, media, logs | Boot volumes, databases, low-latency disk | Shared content for a fleet, CMS, home dirs |

## The 3-question decision heuristic

1. **Storing/retrieving blobs over HTTP at scale?** (assets, backups, data lake) → **Object / S3**
2. **Does one instance or a database need a real disk — boot, low-latency, high-IOPS?** → **Block / EBS**
3. **Do many instances need to share the same files like a normal filesystem?** → **File / EFS** (FSx for Windows/HPC)

Fastest single discriminator between EBS and EFS: **"shared across instances?"** — no → EBS, yes → EFS.

## Domain 3.1 lens 1 — meeting performance demands

Category is step one; the **variant** is where performance lives:

- **EBS types:** `gp3` (general SSD, default) · `io1/io2` (provisioned IOPS — high-perf
  DBs; io2 Block Express highest) · `st1` (throughput HDD, big sequential) · `sc1`
  (cold HDD, cheapest). Detail: [[learning-plan/03-storage/ebs-block-storage|EBS note]].
- **Instance store:** ephemeral, physically attached, **lowest latency**, lost on stop — scratch/cache only.
- **S3:** scales throughput by **parallelism** (many requests); very high aggregate throughput, not single-disk latency.
- **EFS:** throughput modes (Bursting/Elastic/Provisioned); **FSx for Lustre** for HPC/ML.

> Pattern: "high **IOPS** for a database" → **io2**; "high sequential **throughput**" →
> **st1** or **S3**; "lowest-latency local scratch" → **instance store**.

## Domain 3.1 lens 2 — scaling to future needs

- **S3** — no provisioning, effectively unlimited; the default when growth is unknown.
- **EFS** — **elastic**, grows/shrinks automatically; shared file that scales itself.
- **EBS** — **provisioned**; grow with **Elastic Volumes** (online resize) and `gp3`
  **decouples IOPS/throughput from size** so you scale performance without growing the disk.
- **FSx** — scalable managed file systems for specific engines.

> Pattern: "scale **without re-architecting / no capacity planning**" → **S3** or **EFS**
> (elastic); "a disk that must grow" → **EBS Elastic Volumes**.

## Adjacent: hybrid & data-transfer (also on the Domain 3.1 slide)

Not object/block/file themselves, but the storage-domain services to recognize:

| Service | Role | Use when |
|---|---|---|
| **Storage Gateway** | Hybrid on-prem ↔ AWS (File/Volume/Tape gateway) | On-prem apps need cloud-backed storage with local cache |
| **AWS Snowball Edge** | Petabyte-scale **offline** transfer + edge compute | Too much data to move over the network; disconnected edge |
| **AWS DataSync** | **Online** bulk transfer (on-prem↔AWS, or AWS↔AWS) | Large one-time or scheduled migrations over the network |

> Hook: "**too much data for the wire**" → **Snowball**; "**online bulk migration**" →
> **DataSync**; "**on-prem app wants cloud storage**" → **Storage Gateway**.

## Project tie-in
The [[projects/video-streaming-app/DESIGN.md|video-streaming-app]] spans two of the
three: **object** (S3 for all media — unlimited, 11-nines durable) and **block**
(`gp3` EBS on the web/worker launch templates for boot + transcode scratch). No
**file** tier — nothing needed sharing across instances, which the heuristic confirms
is the right call.

## Exam-relevant notes

- "Blobs over HTTP, web-scale, cheap, durable" → **S3** (object).
- "Boot volume / database disk / low-latency block for one instance" → **EBS**.
- "Shared filesystem across many instances (Linux NFS)" → **EFS**; "Windows SMB" → **FSx for Windows**; "HPC" → **FSx for Lustre**.
- "Highest IOPS" → **io2 (Block Express)**; "big sequential throughput cheaply" → **st1**.
- "Scale to unknown future size, no provisioning" → **S3 / EFS** (elastic).
- "Move 80 TB with no time to upload" → **Snowball Edge**.
