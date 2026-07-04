---
title: Load Balancers (ELB)
type: note
domain: networking
date: 2026-06-11
source: Own notes (context: WordPress on AWS example)
tags:
  - aws
  - networking
  - load-balancer
  - elb
  - high-availability
---

# Load Balancers (ELB)

> Part of [[learning-plan/04-networking/04-networking|Networking & Content Delivery]].
> Related: [[learning-plan/10-architecting/stateless-compute-shared-state|Stateless Compute + Shared State]]
> · [[learning-plan/02-compute/apache-web-server|Apache Web Server]]

## Quick recap: why & how

**Why does ALB exist?**

- Prevents one server from being overloaded.
- Keeps the app running even if one server fails.
- Gives you one stable address (DNS name) for your app.

**How does it work?**

1. A user opens a website in a browser.
2. The request goes to the ALB.
3. The ALB sends the request to a healthy EC2 server.
4. The EC2 server responds with the web page.

## Is it built on open-source tech?

Not the way RDS/EFS are. A pattern in AWS is managed wrappers around open-source tech
(RDS literally runs MySQL; EFS implements the open NFS protocol). The load balancer is
**different**: AWS **Elastic Load Balancing (ELB)** is a **proprietary, AWS-built managed
service**, not a managed version of a named open-source load balancer. AWS doesn't
publish its internals, so it can't be claimed to "be" HAProxy or Nginx — it's AWS's own
implementation. *(Based on AWS not disclosing internals, not inside knowledge.)*

Contrast:
- **Open-source load balancers** you could run yourself: HAProxy, Nginx, Envoy, Traefik.
- **ELB** = the managed, AWS-native alternative — you don't run or patch any LB software;
  AWS operates it and it's highly available by default.

So it fits the managed / higher-abstraction idea, but it's not a rebadged OSS project.

### Brief history (where the concept came from)

No single inventor — it evolved in stages (dates/attributions paraphrased for licensing
compliance):

1. **DNS round-robin (early/mid-1990s)** — the first widespread technique: one name → many
   IPs, handed out in rotation. Crude and cache-dependent (the TTL problem below). See
   [DN.org on DNS round-robin](https://dn.org/the-evolution-of-dns-round-robin-and-load-balancing-for-efficient-resource-distribution/).
2. **Dedicated hardware appliances (mid-1990s)** — built to make many servers **look like
   one** to the outside world, for scalability + availability, per
   [F5's "Load Balancing 101"](https://www.f5.com/es_es/resources/white-papers/load-balancing-101-nuts-and-bolts).
   - **Cisco LocalDirector** — conceived **late 1995** (John Mayes & Robert Andrews),
     generally credited as the **first commercial dedicated load balancer**
     ([Wikipedia](https://en.wikipedia.org/wiki/Cisco_LocalDirector)).
   - **F5 Networks** — founded **1996**; its **BIG-IP** became a dominant commercial LB.
3. **Today** — software proxies (**HAProxy, Nginx, Envoy**) + managed cloud services
   (**AWS ELB**).

The *concept* of distributing work across resources is older still (mainframe /
distributed-computing scheduling); **network/web load balancing as a product** traces to
those mid-1990s pioneers.

## Why not just use a public IP or DNS? (the motivation)

The book frames this as **three attempts**, each fixing the previous one's flaw. This is
the "public IP = the cafe location" coupling from
[[learning-plan/10-architecting/decoupling-sync-vs-async|decoupling]].

**Attempt 1 — expose the EC2 instance's public IP directly.** Once users have the IP, it
becomes a contract you can't break:

- **Can't change it** — too many clients rely on it; if the instance dies, its replacement
  gets a new IP and every client points at a dead address.
- **Can't scale** — add a second instance (new IP) and *no existing client knows it
  exists*. They keep hammering the first IP; the new one sits idle.

**Attempt 2 — put a DNS name in front (`example.com → IP`).** Better (you can update the
record), but **DNS isn't fully under your control because of caching**:

- DNS is cached everywhere — resolvers, intermediate servers, the client OS/browser.
- **TTL is a request, not a guarantee.** You may set 1 minute; some resolvers impose a
  minimum and cache for a *day*. So after an IP change you **can't predict when all clients
  see it** — some keep hitting the old/dead IP for hours. DNS also doesn't spread load
  across servers in real time.

**Attempt 3 — a load balancer (the fix).** Expose only the **LB** to the world; servers
hide behind it.

```
        BEFORE                            AFTER
 client → 52.1.2.3 (EC2 #1)      client →  ┌──────────────┐
 client → ??? (EC2 #2 ignored)   client →  │ Load Balancer│ → EC2 #1
                                 client →  └──────────────┘ → EC2 #2 → EC2 #3
```

- **Changeability** — clients depend only on the LB's stable endpoint; swap/re-IP/replace
  instances freely, clients never notice.
- **Real-time scaling (the DNS-beating part)** — the LB distributes *every request* across
  healthy instances instantly. Add an instance → it gets traffic immediately, with **no
  client cache** in the routing path. DNS spreads load only as fast as caches refresh; an
  LB spreads it per request.
- **Health** — a dead instance is detected and routed around; the client is oblivious.

> **The "aha":** DNS isn't *wrong*, it's just too slow and uncontrollable for real-time
> changes because **you don't own the caches**. The LB wins because routing happens on
> *its* side, per request, with nothing cached on the client. This removes the **"same
> place" coupling** (client needs only the LB, not the server address) while client +
> server still meet at the **same time** → **synchronous** decoupling.

## How a load balancer works

> **TL;DR:** the load balancer is the front door of your application. Users don't talk to
> your servers directly — they talk to the load balancer, and it decides which server
> handles the request.

Core job: sit in front of multiple backend servers and spread requests across them, so no
single server is overwhelmed and the system survives individual failures.

1. Clients send all requests to the load balancer's address (not the servers directly).
2. It picks a healthy backend via a distribution algorithm — **round robin** (rotate) or
   **least outstanding requests** (send to least busy).
3. It forwards the request, gets the response, returns it to the client.

Two key features:

- **Health checks.** It regularly probes each backend (e.g. a health URL). If a server
  stops responding it's marked unhealthy and the LB **stops sending it traffic** —
  automatically routing around failures. (Exactly the WordPress reliability behavior: if
  one EC2 instance fails, the rest keep serving until it's replaced.)
- **Enables a server pool.** Clients use one stable front door instead of knowing each
  server's address; backends can come and go behind it.

## Layer 4 vs Layer 7 (exam-relevant)

- **ALB (Application Load Balancer)** — **Layer 7 (HTTP/HTTPS)**. Can read URL paths,
  headers, hostnames and route on content (e.g. `/api/*` vs `/images/*`). Used in the
  WordPress example.
- **NLB (Network Load Balancer)** — **Layer 4 (TCP/UDP)**. Doesn't inspect content; just
  forwards connections at very high performance / low latency. Good for non-HTTP or
  extreme throughput.

Supporting concepts: a **listener** checks for connections on a port/protocol; a **target
group** is the set of backends it routes to. ELB is itself distributed across Availability
Zones, so it's not a single point of failure.

> **Beyond web servers (any TCP protocol).** A load balancer works in front of *anything*
> doing request/response over **TCP** — not just HTTP. Databases/proxies, caches (Redis),
> message brokers, gRPC, mail/game servers, custom TCP protocols. This is really the
> **NLB (Layer 4)** generalization: because it forwards raw TCP connections without
> inspecting content, it doesn't need to understand the protocol. Rule: content-aware
> routing → **Layer 7 (ALB, HTTP only)**; spread any TCP protocol at high speed →
> **Layer 4 (NLB)**.

## Target Groups

The **target group** is the actual list of backends the ALB is allowed to send traffic to
— the ALB itself never talks to a hardcoded server list, only to a target group.

- **Listener → rule → target group.** A **listener** watches a port/protocol (e.g. HTTPS on
  443). Attached to it are **rules** ("if path starts with `/api/*`, send here"); each rule
  points at a **target group**. This is what makes **path-based routing** possible — one
  ALB, multiple target groups, one per backend service (e.g. `/api/*` → API servers,
  `/images/*` → image servers).
- **Target type — what's actually in the group:**
  - **Instance** — EC2 instances, referenced by instance ID. Most common for the
    ASG-backed pattern below.
  - **IP address** — any routable IP (on-prem servers, containers, another VPC). Useful
    when the target isn't a "real" EC2 instance ALB can look up by ID.
  - **Lambda** — a single function, invoked instead of forwarded to a server. Turns the ALB
    into an HTTP front door for serverless code, no EC2 involved at all.
- **Health checks live on the target group, not the ALB globally.** Each target group
  defines its own health check (path, interval, thresholds). This means different backend
  services behind the same ALB can have independent health-check rules — the `/api/*`
  target group and the `/images/*` target group don't have to agree on what "healthy" means.
- **Registration is what "auto-registers" (from the ASG section below) actually means:**
  an instance being "in" a target group is just an entry in that group's member list. The
  ASG adds/removes entries as it launches/terminates instances — nothing about the ALB
  itself changes.

## ALB + Auto Scaling Group (the core reliability pattern)

Individually an ALB and an **Auto Scaling Group (ASG)** each solve one problem; together
they solve the whole reliability + scalability story — and the magic is **auto-registration**.

- **ALB** — decouples users from server IPs (users only know the ALB).
- **ASG** — maintains a **desired count** of healthy instances (e.g. "always two web
  servers"). Replaces failures automatically; scales the count up/down with load.

```
            ┌──────────────┐
 users ───► │     ALB      │ ──► EC2 #1 ┐
            └──────────────┘ ──► EC2 #2 ┘  ← Auto Scaling Group keeps desired = 2
                   ▲                          (replaces failures, scales on load)
                   └── new instances auto-register with the ALB as they launch
```

Key line from the book: **servers started in the ASG automatically register with the
ALB.** That makes it self-managing:

1. ASG launches a new instance (replacement or scale-out).
2. It **auto-registers** into the ALB's target group.
3. ALB **health-checks** it; once healthy, sends it traffic.
4. On failure: ALB stops routing to it **and** ASG terminates + replaces it.

No human updates a server list, no client notices, no IP is hardcoded → **self-healing +
elastic + decoupled** at once.

**Two health checks, two jobs (complementary, not redundant):**

| | ALB health check | ASG health check |
| --- | --- | --- |
| Reaction to a sick instance | **Stop sending it traffic** (route around) | **Terminate and replace it** |
| Effect | Protects the *user experience* now | Restores *capacity* to desired count |

Ties to [[learning-plan/10-architecting/decoupling-sync-vs-async|synchronous decoupling]]
(ALB removes the user↔IP coupling) and to
[[learning-plan/10-architecting/stateless-compute-shared-state|stateless backends]] (the
ASG freely adds/kills instances, so no request can depend on state on a specific server).

## Tie-in: prefer stateless backends

Load balancers can do **sticky sessions** (pin a user to one server), but the cleaner
design is stateless servers + shared state (RDS/EFS) so the LB can send any request to any
server.
