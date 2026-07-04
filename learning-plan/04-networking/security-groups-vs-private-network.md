---
title: Security Groups vs Private Network (VPC/subnets/routes)
type: note
domain: networking
date: 2026-06-17
source: "Book: Amazon Web Services in Action (security chapter) + own notes"
tags:
  - aws
  - networking
  - security
  - vpc
  - security-groups
  - subnets
  - route-tables
---

# Security Groups vs Private Network (VPC/subnets/routes)

> Part of [[learning-plan/04-networking/04-networking|Networking & Content Delivery]].
> Related: [[learning-plan/04-networking/ip-addresses-and-cidr|IP Addresses & CIDR]]
> · [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]]

Two of the book's "four bricks of security" sound alike but operate at **different
layers**:

- **#3 Controlling traffic to/from instances** → **Security Groups**
- **#4 Creating a private network** → **VPC, subnets, route tables**

> One-liner: #3 guards the **door** (which ports are open); #4 decides whether there's
> even a **road** to the building (does a network path exist at all).

## #3 — Security Groups (instance-level firewall)

A security group attaches to an instance's network interface and decides which **ports /
protocols / sources** are allowed in or out.

- Web server example: open **80 (HTTP)** and **443 (HTTPS)**, nothing else.
- About the **what**: which traffic may reach *this specific machine*.
- Per-instance — two instances in the same subnet can have totally different groups.
- Default posture: deny inbound; you punch specific holes.

Analogy: a **locked door + bouncer** on each individual building.

### Firewall vs Security Group vs Rules (nested layers)

These three aren't competing concepts — each **contains** the next:

```
Firewall  (the concept / mechanism — AWS builds & runs it)
   └── Security Group  (AWS's firewall object — you create it; it holds rules)
          └── Rules  (the individual allow-statements you add)
```

| Term | What it is | Who owns it |
| --- | --- | --- |
| **Firewall** | The general traffic-filtering mechanism | **AWS** (builds & operates it) |
| **Security Group** | AWS's specific firewall object on your instance | **You** (create/configure) |
| **Rules** | Individual allow-statements inside the group | **You** (define them) |

This is the [[learning-plan/06-security-iam/shared-responsibility-model|shared
responsibility model]] in miniature: AWS owns the **firewall** (security *of* the cloud);
you own the **rules** (security *in* the cloud). Analogy: AWS provides and staffs the
**checkpoint**; you write the **guard's instructions** ("let in anyone with an HTTPS badge").

A **rule** specifies: **protocol** (TCP/UDP) + **port** (e.g. 443) + **source** (inbound)
or **destination** (outbound — an IP range or another security group).

### One resource, two console entry points

Security groups show up under **both** the EC2 console (Network & Security →
Security Groups) **and** the VPC console (Security → Security Groups) — this
is not two different features, just one resource type surfaced twice.

- Technically, a security group is part of the **EC2 API**
  (`ec2:CreateSecurityGroup`, `ec2:AuthorizeSecurityGroupIngress`, etc.) — a
  holdover from before VPC existed (the old "EC2-Classic" era, when instances
  didn't live in a VPC at all). When VPC came along, security groups became
  **VPC-scoped** (each belongs to exactly one VPC), but the API kept living
  under the EC2 namespace.
- Create/edit one from either console screen and it shows up identically in
  the other — same object, same rules, just a UX convenience since managing
  security groups is fundamentally a networking task.
- Same pattern applies to a couple of other resources: **Elastic IPs** and
  **Network Interfaces (ENIs)** also appear in both the EC2 and VPC consoles
  for the same historical reason.

### The two defaults (asymmetric on purpose)

1. **Inbound = deny by default.** A new security group has *zero* inbound rules — nothing
   gets in until you explicitly allow it. Safe by default; you opt **in** to exposure.
2. **Outbound = allow-all by default.** One default rule permits all outgoing traffic, so
   the instance can reach the internet (updates, APIs, etc.).
3. **Hardening tip:** for high-security cases, **delete the allow-all outbound rule** and
   add specific ones. Locking egress limits **data exfiltration** and **command-and-control**
   traffic — a compromised box can't phone home or ship your data out.

**Stateful:** if you allow an inbound request, its response is automatically allowed back
out (and vice versa) — you never write a rule for the return traffic.

## #4 — Private network (VPC / subnets / route tables)

Network-*structure* security. Before ports even matter, you design the *shape* of the
network and where traffic can physically flow.

- Carve the VPC into **subnets** (CIDR ranges — see
  [[learning-plan/04-networking/ip-addresses-and-cidr|CIDR note]]).
- **Route tables** decide where a subnet's traffic can go:
  - **Public subnet** — has a route to an **internet gateway**.
  - **Private subnet** — **no route to the internet**, so its instances aren't reachable
    from outside at all.
- About the **where / whether**: is there even a path between this network and the
  internet (or between subnets)?

Analogy: **city planning + roads** — which neighborhoods connect to the highway and which
are gated cul-de-sacs with no road in.

### Public vs private subnet — the precise definition

A subnet is public or private purely because of its **route table**, not any setting on
the subnet itself:

- **Public subnet** — has a route `0.0.0.0/0 → Internet Gateway (IGW)`. *That line* is
  what makes it public. Remove it and the same subnet becomes private.
- **Private subnet** — no route to an IGW, so inbound traffic from the internet has
  nowhere to land.

> The book's one-sentence test: **public = has a route to the internet; private = doesn't.**
> Underneath, "a route to the internet" means a route-table entry pointing at an IGW.

### Inbound vs outbound (the nuance the definition skips)

"Private = no route to the internet" mainly means **not reachable *from* the internet
(inbound)**. Private resources often still need *outbound* access (OS patches, external
APIs) — that's what a **NAT Gateway** provides:

```
Public subnet:   instance ⇄ Internet Gateway ⇄ Internet            (two-way)
Private subnet:  instance → NAT Gateway → Internet Gateway → Internet  (outbound only)
                 (nothing on the internet can initiate a connection back in)
```

| | Public subnet | Private subnet |
| --- | --- | --- |
| Route to IGW | Yes (`0.0.0.0/0 → IGW`) | No |
| Reachable *from* internet (inbound) | Yes | No |
| Can reach internet *outbound* | Yes (direct via IGW) | Only via a NAT gateway, if added |
| Typical residents | Load balancer, bastion host | App servers, databases |

### Why at least two subnet types (separation of concerns)

Put only what *must* face the internet (a load balancer) in public subnets; hide
everything else in private subnets where there's no inbound road. Even if a security group
is misconfigured, the missing route is a hard backstop. Classic three-tier layout:

```
[Public subnet]   Load balancer        ← internet-facing
       │
[Private subnet]  App / web servers     ← no inbound from internet
       │
[Private subnet]  Database              ← most isolated
```

## Side by side

| | #3 Security Groups | #4 Private network (VPC/subnets/routes) |
| --- | --- | --- |
| Layer | Around the **instance** | The **network structure** itself |
| Controls | Which **ports/protocols** are allowed | Whether a **route/path** exists at all |
| Answers | "What traffic may reach *this machine*?" | "Is *this network* reachable, and from where?" |
| Analogy | Door + bouncer per building | Roads + gated neighborhoods |
| Granularity | Per instance / interface | Per subnet / whole network |

## Why you need both (defense in depth)

They're **layers, not alternatives.**

```
Internet
   │
   ▼
[Public subnet]  web server  ── SG: allow 80/443 from internet
   │ (route to internet gateway)
   ▼
[Private subnet] database     ── SG: allow 3306 only from web server's SG
   (no internet route — unreachable from outside, period)
```

- The **private network (#4)** ensures the database has *no road* from the internet — even
  a misconfigured firewall can't expose it, because there's no route.
- The **security group (#3)** ensures that, within allowed paths, only the right ports
  from the right sources get through.
- If someone fat-fingers a DB security group rule (#3 fails), the private subnet (#4) is
  still a backstop. **Two independent walls** — that's why they're separate bricks.

## Exam-relevant notes

- "Restrict which **ports** an instance exposes" → **Security Group**.
- "Make a tier **unreachable from the internet**" → **private subnet** (no IGW route).
- Security groups are **stateful** (return traffic auto-allowed); **NACLs** (subnet-level,
  stateless) are the other network-traffic control to know.
- Reference a security group as the *source* in another SG's rule (e.g. DB allows the web
  tier's SG) instead of hardcoding IPs.
