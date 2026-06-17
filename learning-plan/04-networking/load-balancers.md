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

## How a load balancer works

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

## Tie-in: prefer stateless backends

Load balancers can do **sticky sessions** (pin a user to one server), but the cleaner
design is stateless servers + shared state (RDS/EFS) so the LB can send any request to any
server.
