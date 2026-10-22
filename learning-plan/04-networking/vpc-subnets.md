---
title: VPC Subnets
type: note
domain: networking
date: 2026-06-30
source: https://www.youtube.com/watch?v=7eP8U2CnKdA (VPC hands-on lab)
tags:
  - aws
  - networking
  - vpc
  - cidr
  - subnets
---

# VPC Subnets

> Part of [[learning-plan/04-networking/04-networking|Networking & Content Delivery]].
> Builds on [[learning-plan/04-networking/ip-addresses-and-cidr|IP Addresses & CIDR Notation]].

## The simple version

A **VPC** is defined by one CIDR block, e.g. `10.0.0.0/16` (65,536 addresses). A
**subnet** is just another, smaller CIDR block carved out of that same range —
e.g. `10.0.1.0/24` (256 addresses). No new IP space is created; the VPC's block is
sliced into smaller, non-overlapping pieces.

Same "frozen bits" idea as CIDR in general — a subnet just freezes more bits than
its parent VPC:

```
VPC:      10.0.0.0/16   -> 11111111.11111111.00000000.00000000  (16 frozen bits)
Subnet A: 10.0.1.0/24   -> 11111111.11111111.00000001.00000000  (24 frozen bits)
Subnet B: 10.0.2.0/24   -> 11111111.11111111.00000010.00000000  (24 frozen bits)
```

The extra frozen octet (`.1.` vs `.2.`) is what makes each subnet distinct. Every
subnet's range must sit entirely inside the VPC's range, and subnets can't overlap
each other.

## Two things that trip people up

1. **A subnet lives in exactly one Availability Zone.** The VPC spans the whole
   region; subnets are how resources get placed into specific AZs for redundancy.
2. **"Public" vs "private" is not a property of the IP range itself.**
   `10.0.1.0/24` isn't inherently more "public" than `10.0.2.0/24`. A subnet
   becomes public because its **route table** sends `0.0.0.0/0` traffic to an
   Internet Gateway. Subnetting is pure IP math; public/private is a routing
   decision layered on top.

## Mental model

- VPC = one big address block for the region.
- Subnets = smaller, non-overlapping slices of it, each pinned to one AZ.
- Route tables (+ IGW/NAT) decide whether a given subnet can reach/be reached by
  the internet — that's a separate concept from the slicing itself.

## Worked example: three-tier app

Classic pattern from the lab video:

```
Public Subnet   -> Load Balancer
Private Subnet  -> EC2 (app server), RDS (database)
```

Traffic flow: internet → Load Balancer (public) → EC2 (private) → RDS (private).

- The Load Balancer's subnet routes `0.0.0.0/0` to an **Internet Gateway** — that's
  the only thing that makes it "public." It's the one component that must be
  internet-facing.
- EC2 and RDS sit in a subnet with **no route to an Internet Gateway**, so nobody
  on the internet can reach them directly, regardless of security group rules.
  They only need to talk to the Load Balancer and to each other.
- If the private subnet still needs outbound internet access (e.g. EC2 fetching OS
  patches), that goes through a **NAT Gateway** placed in the public subnet — it
  lets private resources initiate outbound connections without exposing an inbound
  route back in.

**Why bother splitting them?** It's blast-radius reduction, not a networking
requirement. Subnetting decides what's grouped together (which tier, which AZ);
routing decides what's exposed. The public subnet holds only what must be
internet-facing; everything else — app logic, data — defaults to private, blocked
at the network layer even before security groups come into play.

## The standard 4-subnet layout

The most common starting VPC topology is **two tiers (public + private) × two
Availability Zones = 4 subnets**. It's a 2×2 grid:

| | AZ-a (e.g. us-east-1a) | AZ-b (e.g. us-east-1b) |
| --- | --- | --- |
| **Public** | Public Subnet 1 — `10.0.1.0/24` | Public Subnet 2 — `10.0.3.0/24` |
| **Private** | Private Subnet 1 — `10.0.2.0/24` | Private Subnet 2 — `10.0.4.0/24` |

Each axis buys a different property:

- **Tier axis (public/private) = security.** The "road vs door" split — public
  subnets have `0.0.0.0/0 → IGW`, private subnets don't. Put only internet-facing
  things in public; workloads + data in private.
- **AZ axis (two columns) = availability.** AZs are physically separate
  datacenters, so spreading each tier across two AZs means one AZ's outage doesn't
  take down the whole tier (the ASG keeps running in the surviving AZ).

**Why four and not fewer** — two forces each force a doubling, and they multiply:

1. **Two tiers** — separation of concerns (1 → 2).
2. **Two AZs** — availability *and* two hard AWS requirements: an **ALB needs
   subnets in ≥2 AZs** to be created at all, and an **RDS DB Subnet Group spans
   ≥2 AZs** even for a single-AZ database (×2 → 4).

Because of #2, the **second-AZ subnets often exist before any resilience feature
is turned on** — they're there just to satisfy ALB/RDS validation (the "placeholder"
subnets). They become "real" only when an ASG places a second instance or RDS
Multi-AZ places a standby there.

**CIDR mechanics:** VPC `10.0.0.0/16`, subnets `/24` → per the
[[learning-plan/04-networking/ip-addresses-and-cidr|CIDR note]], only the **third
octet varies** (`.1`, `.2`, `.3`, `.4`). Which number maps to which subnet is pure
convention (AWS only requires each `/24` to fit the `/16` and not overlap); a
common one is odd = public, even = private, interleaved by creation order.

**Same skeleton, different fill** — the two projects in this repo both use this
4-subnet layout but place different things in the public tier:

| | Public subnets hold | Private subnets hold |
| --- | --- | --- |
| [[projects/photoshare-app\|PhotoShare]] | ALB (+ v1's EC2) | RDS; Phase-2 web ASG |
| [[projects/video-streaming-app\|Video Streaming]] (hardened) | **only the NAT gateway** | internal ALB, web ASG, worker ASG |

The video platform is the stricter **"private-by-default"** version: nothing is
allowed in a public subnet except what physically must be (the NAT) — see
[[learning-plan/04-networking/vpc-connectivity-model|the connectivity model note]]
for how the private tier still reaches everything it needs.

## Internet Gateway, Route Tables & Subnet Associations

Three pieces, like a house's connection to the street.

**Internet Gateway (IGW) — the front door of the VPC**

- A single, AWS-managed, highly-available component. You create one and **attach
  it to exactly one VPC**. Attaching it just means "this VPC now has a door to the
  internet" — nothing flows through it yet.
- It does the NAT translation between an instance's private IP and its public IP
  for internet-bound traffic, automatically, once traffic is routed to it.
- No subnet talks to the IGW directly by default. Attaching the IGW alone doesn't
  make anything public.

**Route Table — the directions, "for this destination, go this way"**

- A list of rules: `destination CIDR → target`. Every route table gets one rule
  for free: `<VPC CIDR> → local` — anything inside the VPC is delivered directly,
  no gateway needed. This is why subnets in the same VPC can always reach each
  other regardless of public/private status.
- To make a subnet public, add one more rule to *its* route table:
  `0.0.0.0/0 → igw-xxxx`.
- A private subnet stays private simply because its route table has **no such
  line** — only the local rule. Traffic to the internet has nowhere to go, so
  it's dropped.

**Subnet association — which directions apply to which subnet**

- A subnet itself has no "public" or "private" flag — it's just a CIDR block.
  What determines its behavior is **which route table it's associated with**.
- Each subnet is associated with exactly one route table at a time. A route table
  can be associated with multiple subnets (e.g. two public subnets in different
  AZs sharing the same route-table-with-IGW-rule).

**Lab checks, mapped to the concepts:**

| Check | What it verifies |
| --- | --- |
| IGW attached to VPC | The door exists and is connected to this VPC at all |
| Public subnet has route to IGW | That subnet's route table says "for the internet, use the door" |
| Private subnet has no route to IGW | That subnet's route table has no such line — nowhere to go, so it's isolated |

> **Gotcha:** a route to the IGW alone doesn't make an *instance* reachable from
> the internet. The instance also needs a public IP (or Elastic IP), and its
> security group needs to allow the inbound traffic. The route table gets you to
> the door — the instance still needs an address people can find and a security
> group that lets them knock.

## Questions / things to revisit

-
