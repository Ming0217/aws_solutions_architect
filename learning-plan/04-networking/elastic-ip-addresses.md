---
title: Elastic IP Addresses (fixed public IPs)
type: note
domain: networking
date: 2026-06-17
source: Amazon Web Services in Action (book) + own notes
tags:
  - aws
  - networking
  - ec2
  - elastic-ip
  - public-ip
  - dns
---

# Elastic IP Addresses (fixed public IPs)

> Part of [[learning-plan/04-networking/04-networking|Networking & Content Delivery]].
> Related: [[learning-plan/04-networking/ip-addresses-and-cidr|IP Addresses & CIDR]],
> [[learning-plan/02-compute/02-compute|Compute]]

## The problem: default public IPs are temporary

When you launch an EC2 instance, AWS hands it a public IPv4 from a **shared pool** so it
can reach the internet. That address is **borrowed, not owned** — its lifecycle is tied
to the running instance:

- **Stop** the instance → AWS reclaims the public IP into the pool.
- **Start** it again → you get a **different** public IP.
- **Terminate + relaunch** → different IP again.

Fine for throwaway experiments, but it breaks anything that depends on the address
staying constant.

## The fix: Elastic IP (EIP)

An **Elastic IP** is a public IPv4 address that **you allocate to your account and own**
until you release it. Because you own it, it survives stop/start. You **associate** it
with an instance (technically with the instance's **network interface**) and it stays put.

| | Default public IP | Elastic IP |
| --- | --- | --- |
| Who owns it | AWS pool (borrowed) | Your account |
| Survives stop/start | No | Yes |
| Can move to another instance | No | Yes — just re-associate |

The underrated part is that **last row**: if an instance dies, detach the EIP and
re-attach it to a healthy replacement. The address stays stable even though the machine
changed — a basic **failover** trick.

## When you actually need a fixed IP (vs just using DNS)

Usually the better answer is "give it a DNS name and point the name at whatever IP."
But the book lists three cases where DNS isn't enough:

1. **Clients can't resolve a DNS name** — legacy systems, embedded devices, or scripts
   hard-coded to talk to a raw IP. They need the IP to never change.
2. **A firewall rule is based on IP addresses** — corporate/partner firewalls often
   **allowlist specific IPs**. If your IP changed on every restart, you'd break their
   allowlist each time. A fixed EIP gives them a stable address to allow.
3. **Avoid DNS propagation delay** — changing a DNS record isn't instant; clients keep
   using the old cached IP until the **TTL** expires (minutes to hours). Keeping a fixed
   EIP and just moving it to a new instance means **no DNS change at all** → near-instant
   failover, no waiting on caches.

## Nuances worth remembering

- AWS prefers you use **DNS (Route 53)** for most stability needs; EIPs are deliberately
  scarce because IPv4 is a limited resource.
- Default limit is ~**5 EIPs per Region** (request an increase past that).
- AWS now **charges for every public IPv4 address**, including in-use EIPs — they're no
  longer free even when attached. Don't hoard them.
- Classic gotcha: an EIP that's **allocated but NOT associated** with a running instance
  is billed *and* wasteful. Release ones you aren't using.

## Exam-relevant notes

- "Instance needs a public IP that **survives stop/start**" → **Elastic IP**.
- "Partner firewall **allowlists our IP**" / "client uses a **hard-coded IP**" → EIP.
- "**Fast failover** without DNS propagation delay" → move the EIP to a standby instance.
- Prefer **Route 53 DNS** when clients can use a hostname; reach for an EIP only when the
  IP itself must be fixed.
- Idle/unassociated EIPs still cost money — a common cost-optimization cleanup target.
