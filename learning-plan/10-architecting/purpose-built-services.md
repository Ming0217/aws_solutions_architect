---
title: Purpose-Built Services (right tool for the workload)
type: note
domain: architecting
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - architecting
  - databases
  - analytics
  - purpose-built
  - saa-c03
---

# Purpose-Built Services (right tool for the workload)

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & best practices]] ·
> focus area 7 of [[learning-plan/10-architecting/task-2-1-scalable-loosely-coupled|SAA Task 2.1]].
> Related: [[learning-plan/10-architecting/service-selection-framework|Service-selection framework]]
> · [[learning-plan/05-databases/05-databases|Databases]]

> The philosophy: **don't force one general-purpose tool (usually a relational DB)
> onto every problem.** AWS offers a service shaped to each data/access pattern;
> matching the shape beats bending a mismatched tool. This is the modern successor
> to "one big RDBMS for everything."

## Purpose-built databases (match the data shape)

| Data shape / access pattern | Service | Why it fits |
|---|---|---|
| Relational, transactions, SQL | **RDS** (MySQL/Postgres/…) | Managed classic RDBMS |
| Relational, cloud-native, high perf/HA | **Aurora** | 5× MySQL / 3× Postgres throughput, auto-healing storage |
| Key-value, massive scale, predictable ms | **DynamoDB** | Serverless, single-digit-ms, horizontal by partition key |
| In-memory cache / session / leaderboard | **ElastiCache** (Redis/Memcached) | Sub-ms reads; offload the DB |
| Durable in-memory | **MemoryDB** | Redis API + durability |
| Document (JSON, Mongo API) | **DocumentDB** | Document model, Mongo-compatible |
| Highly connected data (graph) | **Neptune** | Relationships/traversals (social, fraud, recommendations) |
| Full-text search / log analytics | **OpenSearch** | Search + dashboards |
| Time-series (IoT, metrics) | **Timestream** | Built for time-ordered data at scale |
| Immutable, verifiable ledger | **QLDB** | Cryptographically verifiable history |
| Wide-column (Cassandra) | **Keyspaces** | Managed Cassandra-compatible |

Hook: **shopping cart** → DynamoDB · **social graph / fraud** → Neptune ·
**search box** → OpenSearch · **metrics feed** → Timestream · **cache** → ElastiCache ·
**reporting/BI** → Redshift (below).

## Purpose-built analytics & streaming

| Need | Service |
|---|---|
| Petabyte data warehouse / BI queries | **Redshift** |
| Ad-hoc SQL directly over S3 | **Athena** |
| Big-data processing (Spark/Hadoop) | **EMR** |
| ETL / data catalog | **Glue** |
| Real-time streaming ingest/processing | **Kinesis** (Data Streams/Firehose) |
| Managed Apache Kafka | **MSK** |
| BI dashboards | **QuickSight** |

> Streaming vs queue nuance: **Kinesis** = ordered, replayable **stream** with
> multiple independent consumers and a retention window; **SQS** = decoupling
> **queue**, message deleted after processing. "Replay / multiple readers / ordered
> shards" → Kinesis; "offload work, process-once" → SQS. (See
> [[learning-plan/10-architecting/sns-vs-sqs-vs-eventbridge|SNS vs SQS vs EventBridge]].)

## Why it matters (Task 2.1 angle)

Purpose-built services are usually **managed and horizontally scalable by design**,
so choosing the right one often *is* the scaling/decoupling answer — e.g.,
DynamoDB scales by partition key with no servers, Aurora scales reads via replicas,
Kinesis scales by shards. Picking the matched service avoids bolting scaling onto a
mismatched tool later.

## Project tie-ins
- **video-streaming** — **DynamoDB** for the catalog (key-value by `video_id`, status
  lookups via a GSI) rather than a relational DB it didn't need.
- **photoshare** — **RDS** for genuinely relational image metadata.

## Exam-relevant notes

- "Millisecond key-value at any scale, no capacity planning" → **DynamoDB**.
- "Relationships / shortest-path / recommendations" → **Neptune**.
- "Full-text search or log analytics" → **OpenSearch**.
- "Sub-ms reads, reduce DB load" → **ElastiCache**.
- "Warehouse / complex analytical SQL" → **Redshift**; "query S3 without loading" → **Athena**.
- "Ordered, replayable stream, multiple consumers" → **Kinesis** (not SQS).
