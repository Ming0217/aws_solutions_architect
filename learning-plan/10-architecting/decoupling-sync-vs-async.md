---
title: Decoupling — Synchronous (ELB) vs Asynchronous (SQS)
type: note
domain: architecting
date: 2026-06-17
source: "Book: Amazon Web Services in Action (cafe/meeting analogy) + own notes"
tags:
  - aws
  - architecting
  - decoupling
  - elb
  - sqs
  - resilience
  - scalability
---

# Decoupling — Synchronous (ELB) vs Asynchronous (SQS)

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & best practices]].
> Related: [[learning-plan/04-networking/load-balancers|Load Balancers]]
> · [[learning-plan/10-architecting/stateless-compute-shared-state|Stateless Compute + Shared State]]

## The cafe analogy → two dimensions of coupling

A meeting (or a request between components) can be coupled on **two independent
dimensions**:

1. **Place** — must both parties be in the same location?
2. **Time** — must both parties be present at the same moment?

| Method | Same place? | Same time? | What's left |
| --- | --- | --- | --- |
| Cafe | Yes | Yes | Fully coupled (place + time + find each other) |
| Video call | **No** | Yes | **Synchronous** decoupling (place removed) |
| Email | **No** | **No** | **Asynchronous** decoupling (place *and* time removed) |

- **Synchronous decoupling** = different place, **same time** — both must be "online" at
  once; you get an immediate back-and-forth.
- **Asynchronous decoupling** = different place **and** different time — send now, respond
  whenever; both need not be present together.

> The one thing that never goes away: **"find each other"** — you always need *some*
> address (the load balancer's DNS name, or the queue). That's the endpoint.

## Mapping to AWS services

### Synchronous → Elastic Load Balancing (ELB)

Used when the client **expects an immediate response** (e.g. loading a web page).

```
Client ──► ELB ──► [web server 1 / 2 / 3]
```

- Decouples **place**: the client talks only to the **stable load balancer**, not a
  specific server's IP. Servers behind it can come and go.
- Still coupled on **time**: it's a live request — a healthy target must respond now.
- Solves the "public IP = cafe location" problem (see below).

### Asynchronous → Simple Queue Service (SQS)

Used when the client **does not need an immediate response** (e.g. resize an uploaded
image in the background).

```
Producer ──► [SQS queue] ──► Consumer (processes whenever ready)
```

- Decouples **place AND time**: the consumer can be offline (scaling, patching, restart)
  when the message arrives — like email, the message waits in the queue.

## Why an architect cares (the two tight couplings to break)

1. **Public IP = the cafe location.** Hardwiring a client to a server's IP couples them —
   change the IP and *both* sides must update. A load balancer (or DNS name) gives a
   stable front so the backend can change freely.
2. **Server must be online = same time.** Calling a server directly fails if it's down
   (patching, hardware failure). A **queue** removes this — the request survives until a
   consumer can handle it.

**Payoff:** decoupling buys **resilience + scalability** — components can fail, restart,
scale, or be replaced without the other side noticing. It's also what makes
[[learning-plan/10-architecting/stateless-compute-shared-state|stateless horizontal scaling]]
possible.

## Quick recall

| Question | Answer |
| --- | --- |
| Client needs an immediate response, hide backend servers | **ELB** (synchronous) |
| Work can be processed later / in the background | **SQS** (asynchronous) |
| Which dimension does ELB remove? | **Place** (not time) |
| Which dimensions does SQS remove? | **Place and time** |
| What always remains? | "Find each other" — the endpoint (LB DNS / queue) |
