---
title: SQS vs SNS vs EventBridge — Queue, Broadcast, Router
type: note
domain: architecting
date: 2026-10-19
source: own notes (messaging/integration triad)
tags:
  - aws
  - sqs
  - sns
  - eventbridge
  - messaging
  - decoupling
  - architecting
---

# SQS vs SNS vs EventBridge — Queue, Broadcast, Router

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & Best Practices]]
> (the module lists "decoupling (SQS/SNS)" directly).
> Related: [[learning-plan/10-architecting/sqs-decoupling-and-dlq|SQS — decoupling, visibility timeout & DLQ]] ·
> [[learning-plan/10-architecting/decoupling-sync-vs-async|Decoupling — sync vs async]]

The three AWS messaging/integration services overlap just enough to confuse. The
durable distinction is **one word each**:

- **SQS** = a **queue**. One producer drops messages; **one consumer group** pulls
  them at its own pace. *Point-to-point, pull, buffered.*
- **SNS** = a **broadcaster** (pub/sub). One message **fans out to many
  subscribers** at once, immediately. *One-to-many, push, fire-and-forget.*
- **EventBridge** = a **router**. Events hit a bus; **rules filter on content** and
  route each to different targets. *Content-based routing, with a schema brain.*

## The comparison

| | **SQS** | **SNS** | **EventBridge** |
| --- | --- | --- | --- |
| Pattern | Queue (1 → 1 group) | Pub/sub (1 → many) | Event bus + router |
| Delivery | **Pull** (consumer polls) | **Push** (to subscribers) | **Push** (to targets) |
| Consumers | One logical worker pool shares the messages | Many — **each** gets its own copy | Many — routed by rules |
| Buffering / durability | **Yes** — messages wait until pulled | **No** — delivered now or missed* | No native buffer |
| Routing smarts | None | Topic-level only | **Rich filtering on event content** |

\*If an SNS subscriber is down, it misses the message — unless an **SQS queue** is
the subscriber (see fan-out below).

## When to reach for each

- **SQS** — work must be **done once, by a worker, at its own pace, and not lost**.
  A task queue: transcoding, order processing, "do this job."
- **SNS** — **one event must notify several systems right now**. "Order placed" →
  simultaneously trigger billing, email the customer, update analytics. Each is a
  separate subscriber getting its own copy.
- **EventBridge** — you need **routing logic** ("route `amount > 1000` to the
  fraud Lambda, everything else to the normal queue"), many event *types* on one
  bus, or integration with **AWS-service / SaaS** events. The event backbone of an
  event-driven architecture.

## The pattern that ties them together — SNS → SQS fan-out

SNS alone **loses messages if a subscriber is down** (no buffer). So the classic
production pattern is **SNS fanning out to multiple SQS queues**:

```
                         ┌──► SQS (billing)   ──► billing worker
"order placed" ──► SNS ──┼──► SQS (shipping)  ──► shipping worker
                         └──► SQS (analytics) ──► analytics worker
```

Now you get **both** one-to-many broadcast (SNS) **and** per-consumer buffering +
durability (each SQS queue survives its worker being down and drains at its own
pace). Broadcast **+** durability. This is a very common exam answer — memorise it.

## Decision rule (fast)

- "Done once, by a worker, at its pace, mustn't be lost." → **SQS**.
- "Tell several systems right now." → **SNS**.
- "Tell several systems **and** survive them being down." → **SNS → SQS** fan-out.
- "Route by what's *in* the event, or wire AWS/SaaS events." → **EventBridge**.

## One-liner each

- **SQS** = "hold this task until a worker is ready." (buffer)
- **SNS** = "shout this to everyone subscribed, now." (broadcast)
- **EventBridge** = "read this event and send it to the right place." (route)

## Exam-relevant notes

- The services **overlap** — you can fan out with SNS *or* EventBridge, buffer with
  SQS *or* an EventBridge→SQS target. Real choices weigh cost, latency, and
  existing wiring; the queue/broadcast/router identities decide ~90% of cases.
- **SNS has no buffer** → pair with SQS when a subscriber may be offline. The
  **SNS → SQS fan-out** is the canonical "broadcast + durability" answer.
- **EventBridge** is the only one that filters on **event content** and integrates
  natively with **100+ AWS services** and **SaaS** sources (plus schema registry,
  archive/replay).
- All three are **decoupling** primitives — see
  [[learning-plan/10-architecting/decoupling-sync-vs-async|sync vs async decoupling]].
