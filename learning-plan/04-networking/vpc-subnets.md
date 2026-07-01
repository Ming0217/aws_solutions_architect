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

## Questions / things to revisit

-
