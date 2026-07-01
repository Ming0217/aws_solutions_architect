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
