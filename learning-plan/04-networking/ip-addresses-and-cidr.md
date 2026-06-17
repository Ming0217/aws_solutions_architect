---
title: IP Addresses & CIDR Notation
type: note
domain: networking
date: 2026-06-11
source: Skill Builder course (VPC intro) + ELI-fourth-grader explanation
tags:
  - aws
  - networking
  - vpc
  - cidr
  - ip
---

# IP Addresses & CIDR Notation

> Part of [[learning-plan/04-networking/04-networking|Networking & Content Delivery]].

## The simple version (explain like I'm in 4th grade)

An **IP address** is a computer's home address, so messages can find it — just like
every house on a street has a number. An IPv4 address looks like `172.31.6.85`: four
numbers separated by dots.

When you see a **slash and a number** (e.g. `172.31.0.0/16`), that describes a whole
*neighborhood* of addresses, not a single house. AWS calls this **CIDR notation**
(Classless Inter-Domain Routing).

### The one rule to anchor on

> **Big number = tiny network. Small number = huge network.** (the number after the `/`)

Think of the slash number as *how much of the address is frozen* as the neighborhood
name, leaving the rest free for house numbers (hosts):

- `/16` freezes the first two parts (`172.31`), last two are free → **big** network.
- `/32` freezes all four parts → no room left → exactly **one single IP address**.
- `/0` freezes nothing → **every possible address**. In AWS, `0.0.0.0/0` means "the
  entire IPv4 internet / everywhere."

## Where does the /number come from?

A computer sees the address as 32 on/off switches (bits), in four groups of 8 (octets).
The slash number counts how many switches from the left are frozen as the network name:

```
/16  ->  11111111.11111111.00000000.00000000
         |--- 8 ---||--- 8 ---|   = 16 frozen bits  ->  /16
```

The frozen part (`172.31`) identifies the **network**; the free part is where **hosts**
live. The same `/16` can also be written as the **subnet mask** `255.255.0.0` — same
idea, different notation. (The Linux `ipcalc` utility will show you this breakdown.)

**Gut check:** `172.31.6.85` is in the `172.31.x.x` network. Something like `10.4.2.9`
is a completely different network — not a neighbor.

## IPv4 vs IPv6

| | IPv4 | IPv6 |
| --- | --- | --- |
| Introduced | early 1980s | 1998 (to replace IPv4) |
| Size | 32-bit (four 8-bit octets) | 128-bit (eight groups of 4 hex digits) |
| Notation | dot-decimal, e.g. `172.31.6.85` | colon-separated hex, e.g. `50b2:6400::6c3a:b17d:0:10a9` |
| Total addresses | ~4.3 billion (must be reused/masked) | ~3.4 × 10^38 (≈340 trillion trillion trillion) |
| Extras | — | supports automatic configuration |

IPv6 exists because IPv4's ~4.3 billion addresses ran out — the world has far more
devices than that. IPv6 has so many addresses that every device can have its own.
AWS VPC supports both IPv4 and IPv6.

> **Shortening IPv6:** consecutive groups of zeros can be collapsed to `::` once.
> e.g. `50b2:6400:0000:0000:0000:6c3a:b17d:0:10a9` → `50b2:6400::6c3a:b17d:0:10a9`.

## CIDR quick reference (IPv4)

| CIDR | Subnet mask | Total addresses | Typical meaning |
| --- | --- | --- | --- |
| /0 | 0.0.0.0 | all ~4.3 billion | everywhere (`0.0.0.0/0`) |
| /8 | 255.0.0.0 | 16,777,216 | very large network |
| /16 | 255.255.0.0 | 65,536 | large network (common VPC size) |
| /24 | 255.255.255.0 | 256 | small subnet |
| /32 | 255.255.255.255 | 1 | a single host |

> Note: in an AWS VPC subnet, AWS reserves 5 addresses in every block, so a /24
> gives you 251 usable host addresses rather than 256.

## Why this matters for AWS

- A **VPC** is defined by a CIDR block (e.g. `172.31.0.0/16`); **subnets** carve smaller
  ranges out of it (e.g. `172.31.1.0/24`).
- Security group and route table rules use CIDR to describe sources/destinations —
  `0.0.0.0/0` = open to the whole internet (use carefully!).
