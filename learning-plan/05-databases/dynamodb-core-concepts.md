---
title: DynamoDB Core Concepts
type: note
domain: databases
date: 2026-10-19
source: Skill Builder course + own notes
tags:
  - aws
  - dynamodb
  - databases
  - nosql
---

# DynamoDB Core Concepts

> Part of [[learning-plan/05-databases/05-databases|Databases]].
> Related: [[learning-plan/05-databases/rds-core-concepts|RDS Core Concepts]]
> (the relational contrast) ·
> [[learning-plan/01-cloud-foundations/aws-is-services-over-hardware-via-api|The API is the only door in]]

Amazon DynamoDB is AWS's **fully managed, serverless NoSQL** database. Where RDS
gives you a managed *relational* engine (MySQL/Postgres with rigid tables, joins,
SQL), DynamoDB trades that flexibility of *querying* for flexibility of *schema*
and predictable speed at **any scale**. There are no servers, no instance sizes,
no patching — you interact with it purely through the API.

> **Defining trait: single-digit millisecond latency at any scale.** Consistent
> fast reads/writes regardless of how large the table grows is *why* hyperscale
> apps (Amazon.com, Uber, Airbnb) reach for DynamoDB. That performance is a
> direct payoff of the primary-key/partitioning model below: items are addressed
> **by key** (hash the partition key → go straight to the item) rather than
> *searched*, so lookups don't slow down as the table grows. Modeling keys and
> managing capacity are the first two skills precisely because they're what buy
> you that latency.

## The vocabulary

| Term | What it is | Relational analogy |
| --- | --- | --- |
| **Table** | Container for records; only the **primary key** must be defined upfront | Table |
| **Item** | A single record | Row |
| **Attribute** | A field on an item | Column (but per-item, not fixed) |
| **Primary key** | The mandatory unique identifier for every item | Primary key |

## Schema-on-item, not schema-on-table (the NoSQL part)

The thing that separates it from RDS: **you don't define columns upfront.** The
*only* thing fixed at table creation is the **primary key**. Every other
attribute is defined per-item.

- Item A can have `Color` and `Size`; item B in the **same table** can have only
  `Weight`. Both are valid.
- This is "schema-on-item" — each item carries its own shape — vs. RDS's
  "schema-on-table" where every row must match the columns you declared.
- **Why it's powerful:** you can evolve your data shape without migrations, and
  store heterogeneous records together.
- **The tradeoff:** the database enforces *nothing* about structure except the
  key. Validation and consistency of the non-key attributes become **your
  application's job**, not the database's. No joins either — you model data for
  how you'll read it, not in normalized tables.

## The primary key — this is the whole game

In DynamoDB, the primary key isn't just "a unique id" — it determines **how data
is physically partitioned and how you're allowed to query it**. Get this right
and DynamoDB is fast and cheap; get it wrong and you fight it forever. Two shapes:

### Simple primary key — Partition Key only

- A single attribute (e.g. `UserID`). Must be **unique** across the table.
- DynamoDB hashes the partition key to decide which physical partition the item
  lives on → direct, O(1)-style lookups by that key.
- Good when you always fetch a single item by its id.

### Composite primary key — Partition Key + Sort Key

- Two attributes together (e.g. `Artist` as partition key + `SongTitle` as sort
  key). The **combination** must be unique (the partition key alone need not be).
- All items sharing a partition key are **stored together, sorted by the sort
  key** — which unlocks efficient range queries: "all songs by this artist,"
  "all songs by this artist from A–M," "the most recent N."
- This is the model you reach for when you need to query a *group* of related
  items, not just one.

> **Mental model:** partition key = *which bucket* the item goes in (and how
> lookups are distributed); sort key = *the order within that bucket* (and what
> range queries you can do). You design these around your **access patterns up
> front** — the #1 DynamoDB skill, and the biggest difference from relational
> design where you normalize first and query however later.

## Capacity modes — how you pay for throughput

DynamoDB throughput is measured in **read/write capacity units**, and you choose
how to provision it. (The course has you switch between these — worth
understanding the tradeoff.)

| Mode | How it works | Best for |
| --- | --- | --- |
| **On-demand** | DynamoDB auto-scales to whatever traffic arrives; pay per request | Spiky, unpredictable, or new workloads where you don't know the traffic yet |
| **Provisioned** | You set target reads/writes per second (optionally with auto-scaling); pay for the capacity reserved | Steady, predictable traffic — cheaper at scale if you know your numbers |

- **On-demand** = zero capacity planning, higher per-request price, no throttling
  surprises. The safe default when you don't know your load.
- **Provisioned** = cheaper per request if traffic is steady, but under-provision
  and requests get **throttled**; over-provision and you pay for idle capacity.
- You can **switch between modes** (with a cooldown), so starting on-demand and
  moving to provisioned once traffic is understood is a common, sane path.

## When DynamoDB vs. RDS

| Reach for **DynamoDB** when… | Reach for **RDS** when… |
| --- | --- |
| Key-based access patterns known up front | Ad-hoc queries, reporting, joins |
| Massive scale / unpredictable spikes | Moderate, relational workloads |
| Flexible/evolving item shape | Strong relational integrity, fixed schema |
| Serverless, no capacity management | You want SQL and a familiar engine |

Not "better/worse" — different tools. DynamoDB wins on scale + flexibility +
no-ops; RDS wins on query flexibility + relational guarantees. See
[[learning-plan/05-databases/rds-core-concepts|the RDS note]] for the other side.

## Where this shows up in projects

- **[[projects/video-streaming-app|Video Streaming Platform]]** — DynamoDB tracks
  **job/video state** (e.g. `uploaded → queued → processing → ready/failed`) and
  metadata. A natural fit: lookups are key-based (by video/job id), the shape can
  evolve, and it's serverless like the rest of the event-driven pipeline. The
  primary-key choice there is a real design decision — e.g. a simple key on a
  video id, or a composite key if multiple renditions/segments per video need to
  be queried as a group.

## Exam-relevant notes

- DynamoDB = **fully managed, serverless, NoSQL** key-value/document store.
- Only the **primary key** is fixed at table creation; other attributes are
  **per-item** (schema-on-item).
- **Simple key** = partition key only; **composite key** = partition + sort key
  (enables range queries over items sharing a partition key).
- **Design around access patterns first** — no joins, no ad-hoc querying like SQL.
- **Capacity modes:** on-demand (auto-scale, pay-per-request, unpredictable load)
  vs. provisioned (reserve throughput, cheaper if steady, risk of throttling).
