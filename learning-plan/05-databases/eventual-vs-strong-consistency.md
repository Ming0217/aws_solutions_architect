---
title: Eventual vs Strong Consistency
type: note
domain: databases
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - databases
  - consistency
  - dynamodb
  - rds
  - s3
  - cap-theorem
  - saa-c03
---

# Eventual vs Strong Consistency

> Part of [[learning-plan/05-databases/05-databases|Databases]].
> Related: [[learning-plan/05-databases/dynamodb-core-concepts|DynamoDB core concepts]]
> · [[learning-plan/05-databases/rds-core-concepts|RDS core concepts]]
> · [[learning-plan/10-architecting/purpose-built-services|Purpose-built services]]

## The concept

A system is **eventually consistent** if, once writes stop, all replicas converge and
every read returns the latest value. The guarantee is about the **destination, not the
timing**: it says nothing about how long a stale read remains possible.

It exists because of **replication**. A write is acknowledged as soon as it lands on some
subset of replicas, and the rest catch up in the background. That is what buys **low
latency and availability**. **Strong consistency** means the opposite trade: a read
reflects every completed write, so the read path must coordinate with enough replicas to
prove it — which costs latency and fails when replicas are unreachable.

> One-liner: **eventual = fast/available now, correct eventually; strong = correct now,
> at the cost of latency and availability.** You are choosing *when* you pay for
> agreement, not *whether*.

## Why it's a trade, not a bug (CAP)

During a network **partition**, a distributed store must choose (CAP theorem):

- **AP** (availability + partition tolerance) → keep serving, reconcile later → **eventual**.
- **CP** (consistency + partition tolerance) → refuse/stall reads it can't prove → **strong**.

No partition? You can often have both. The choice only bites under failure — which is
exactly when it matters.

## The consistency spectrum (not a binary)

```
strong  ──►  bounded staleness  ──►  read-your-own-writes / session  ──►  eventual
tightest, costliest                                                    loosest, cheapest
```

Many systems let you pick **per operation** (e.g., DynamoDB) rather than globally.

## How this shows up in AWS

| Service | Default | Strong option / note |
|---|---|---|
| **DynamoDB** | **Eventually** consistent reads (cheaper — ½ the RCU) | `ConsistentRead=true` for **strongly** consistent reads (full RCU, higher latency). **GSIs are *always* eventually consistent.** Use **transactions** for ACID writes. |
| **DynamoDB Global Tables** | Eventually consistent across regions | Multi-region, **last-writer-wins** conflict resolution |
| **S3** | **Strong** read-after-write (since Dec 2020) for PUT/overwrite/DELETE **and** list | (Historically was eventually consistent — a common stale exam fact) |
| **RDS read replicas** | **Eventually** consistent (async replication → **replica lag**) | Reads off a replica can be stale; read the **primary** for latest |
| **RDS/Aurora Multi-AZ standby** | N/A — **not readable** | **Synchronous**, but for **failover/availability**, not read scaling (classic trap) |
| **Aurora replicas** | Eventually consistent (async reader endpoint) | Very low lag (shared storage, typically ms) |
| **Route 53 / DNS** | Eventually consistent (propagation) | Changes take time to spread |

> Exam trap: **Multi-AZ = availability** (standby, not readable); **read replicas =
> read scaling** (and they're eventually consistent). Don't mix them up.

## When eventual is fine vs when you need strong

**Eventual is fine** when a brief stale read is harmless:
- Social feeds, timelines, view counts, product catalogs, dashboards/metrics, search indexes.

**You need strong** when a stale read causes a wrong decision:
- Account balance after a transfer, inventory decrement (overselling), uniqueness checks,
  "read your own write" right after saving, anything gating a state transition.

## Mitigation patterns

- **Strongly consistent read on the hot path only** (pay the cost where correctness matters).
- **Read-your-own-writes / session consistency** — route a user's reads to where their write landed.
- **Quorum** — with N replicas, **R + W > N** guarantees a read overlaps the latest write (the Dynamo-paper trick).
- **Versioning / conditional writes** (optimistic locking) to detect conflicts; **last-writer-wins** or app-level merge to resolve them.

## Project tie-ins
- [[projects/video-streaming-app/DESIGN|video-streaming-app]] — lists videos via a
  **GSI** (`by-status-created`), which is **always eventually consistent**, so a
  just-uploaded item can briefly lag in the gallery before appearing. Per-item lookups by
  `video_id` on the base table can be made strongly consistent if ever needed.
- [[projects/clear-thinking-app|clear-thinking-app]] — per-user items in DynamoDB; reads
  tolerate eventual consistency, keeping reads cheap (½ RCU).

## Exam-relevant notes

- "Read must reflect the most recent write" → **strongly consistent read** (DynamoDB `ConsistentRead`) or read the **primary**.
- "GSI query returns slightly stale data" → **expected** — GSIs are always eventually consistent.
- "Scale reads" → **read replicas** (eventually consistent); "survive an AZ failure" → **Multi-AZ** (not for reads).
- "Lowest cost / highest throughput reads, staleness OK" → **eventually consistent reads**.
- "Strong consistency across a region partition" → you sacrifice **availability** (CAP).
