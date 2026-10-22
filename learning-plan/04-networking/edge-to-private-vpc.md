---
title: Reaching a Private VPC Resource from the Edge (CloudFront → API Gateway → VPC Link → internal ALB)
type: note
domain: networking
date: 2026-10-20
source: Own notes (synthesizing the video-streaming hardened edge→ALB path)
tags:
  - aws
  - networking
  - cloudfront
  - api-gateway
  - vpc-link
  - alb
  - privatelink
---

# Reaching a Private VPC Resource from the Edge

> Part of [[learning-plan/04-networking/04-networking|Networking & Content Delivery]].
> Builds on [[learning-plan/04-networking/load-balancers|Load Balancers]]
> (internet-facing vs **internal** ALB) and
> [[learning-plan/04-networking/vpc-connectivity-model|VPC Connectivity Model]]
> (interface endpoints / PrivateLink). Concrete example: the hardened
> [[projects/video-streaming-app|Video Streaming Platform]].

The chain **`CloudFront → API Gateway → VPC Link → internal ALB`** looks like a
lot of machinery. The key insight: **it exists *only* because the ALB was made
internal.** With a public (internet-facing) ALB you'd have none of it. Each hop
solves one specific problem created by the decision to keep the backend private.

## The problem it solves

- **CloudFront lives at the edge** — AWS's global network, **outside** your VPC.
- The **ALB is internal** — private IPs inside your VPC, **no public address**
  (per the minimize-public-surface principle in
  [[learning-plan/04-networking/load-balancers|the ALB note]]).
- **The gap:** how does edge traffic reach a thing with no public address? You
  **can't point CloudFront at a private IP** — the edge can't route into your
  private subnets. The three middle hops bridge that gap.

This is a general pattern, not a video-platform quirk: **whenever a managed/edge
service must reach a *private* VPC resource, you need a bridge into the VPC.**

## Hop by hop (left = outside the VPC, right = inside)

**1. CloudFront — the single public front door (edge / CDN)**
- The only internet-facing resource. Terminates user HTTPS, serves the SPA,
  caches, applies signed-cookie auth. For `/api/*` it must forward to the backend
  — but the backend is private, so it forwards to the next hop instead.

**2. API Gateway (HTTP API) — a public, managed HTTPS endpoint CloudFront *can*
reach**
- Gives you an AWS-managed public endpoint (`…execute-api….amazonaws.com`) usable
  as a CloudFront origin over HTTPS. This is the "reachable from the edge" piece.
- But API Gateway is *also* a managed service outside your VPC — it can't touch a
  private ALB directly either. It needs a bridge *into* the VPC → the next hop.
- Bonus in this build: it also **strips the `/api` prefix** (route
  `ANY /api/{proxy+}` with `overwrite:path = /${request.path.proxy}`), so the app
  behind the ALB sees `/videos`, `/health`, … unprefixed.

**3. VPC Link — the bridge from the managed API Gateway *into* your private VPC**
- The unfamiliar, load-bearing piece. A **VPC Link** is how an API Gateway (which
  lives outside your VPC) reaches **private** resources inside it. It provisions
  **ENIs (private-IP network interfaces) in your private subnets**, and API
  Gateway sends traffic through those ENIs.
- So the VPC Link is the literal **door into the private network** — what lets an
  outside-the-VPC service touch an inside-the-VPC, no-public-IP resource.
- **Same idea as an interface VPC endpoint**, just the other direction: an
  interface endpoint lets *your VPC* reach a managed service via ENIs; a VPC Link
  lets a *managed service* reach *your VPC* via ENIs. Both are PrivateLink ENIs
  bridging the VPC boundary.

**4. Internal ALB — the private load balancer, unchanged**
- Now reachable: the VPC Link's ENIs are inside the VPC, so they hit the ALB's
  private IP. The ALB does its normal job (listener, target group, health checks,
  spread to the web ASG on `:8000`).

## The full picture — the VPC boundary is the whole point

```
         OUTSIDE YOUR VPC (managed / edge)          │     INSIDE YOUR VPC (private)
                                                     │
 user ─https─► CloudFront ─https─► API Gateway ──────┼──► VPC Link ──► internal ALB ──► web ASG
   (edge; the               (managed public           │   (ENIs in      (private IPs,    (:8000)
    only public              HTTPS endpoint            │    private       internal
    resource)                CloudFront can            │    subnets,      scheme)
                             use as an origin)         │    PrivateLink)
                                               ── VPC boundary ──
```

Everything **left** of the boundary is a managed/edge service with **no VPC**;
everything **right** is **private inside your VPC**. The **VPC Link is the only
thing that straddles the line** — ENIs that live inside the VPC while being driven
by API Gateway outside it.

## Why not a shorter path? (these were rejected/failed — know why)

- **CloudFront → internal ALB directly** via the newer **CloudFront VPC origin**
  feature *should* do exactly this — but in the video platform's live deploy it
  **did not pass traffic** to the private ALB (textbook-correct config, still a
  30s 504; see that project's walkthrough §9a Finding 3). The API Gateway + VPC
  Link path is the well-trodden, reliable alternative.
- **Just make the ALB public** removes all three hops — but reintroduces a
  **second public front door**: another internet-exposed endpoint to secure, and a
  way for clients to **bypass CloudFront** (its WAF, caching, signed-cookie auth)
  by hitting the ALB's DNS directly. Rejected on the minimize-public-surface
  principle.

So the chain is the **price of keeping the ALB private while still serving it from
CloudFront**. Each hop is essential: API Gateway = "edge-reachable public
endpoint," VPC Link = "bridge into the private VPC," internal ALB = "the actual
private load balancer." Remove any one and edge traffic can't reach the private
backend.

## When you need this vs when you don't

| Situation | Edge→backend path |
| --- | --- |
| No CDN/edge requirement (e.g. [[projects/photoshare-app\|PhotoShare]]) | **Internet-facing ALB** — users hit it directly, no chain at all |
| CDN/edge already required, backend must stay private (e.g. [[projects/video-streaming-app\|Video Streaming]]) | **CloudFront → API Gateway → VPC Link → internal ALB** |

Only reach for this machinery when a requirement **already** put a public front
door (CloudFront) in place and you want the backend private. It is not a default.

## Exam-relevant notes

- **VPC Link** = how **API Gateway** reaches **private** VPC resources (ENIs in
  your subnets via PrivateLink). The keyword pairing: "API Gateway → private
  ALB/NLB" ⇒ **VPC Link**.
- **Interface VPC endpoint vs VPC Link** — mirror images: endpoint = *your VPC →
  managed service*; VPC Link = *managed service → your VPC*. Both are PrivateLink
  ENIs crossing the VPC boundary.
- An **internal** ALB has no public IP and can't be a CloudFront origin on its own
  — you bridge to it (API Gateway + VPC Link), or use CloudFront VPC origin (newer;
  verify it carries traffic).
- The whole chain is a consequence of **minimize public surface** (internal ALB);
  a public ALB needs none of it but adds an internet-exposed, bypassable door.
