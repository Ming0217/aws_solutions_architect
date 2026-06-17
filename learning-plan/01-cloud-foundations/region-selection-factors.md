---
title: Factors Impacting Region Selection
type: note
domain: cloud-foundations
date: 2026-06-11
source: Skill Builder course slide
tags:
  - aws
  - regions
  - global-infrastructure
  - cloud-foundations
---

# Factors Impacting Region Selection

> Part of [[learning-plan/01-cloud-foundations/01-cloud-foundations|Cloud Foundations]].

Choosing which AWS Region to deploy a workload into comes down to four factors:

## 1. Governance

Legal, regulatory, and compliance requirements about *where* data can physically
live. Data residency / sovereignty laws (e.g. GDPR) or company policy may require —
or forbid — specific Regions.

## 2. Latency

Deploy close to your end users to minimize round-trip time. The nearer the Region
is to the people (or systems) consuming the workload, the lower the latency and the
better the experience.

## 3. Service availability

Not every AWS service or feature is available in every Region, and new services
often launch in a subset of Regions first. Confirm the services your architecture
depends on exist in the Region you're considering.

## 4. Cost

Pricing varies by Region for the same service. The same resource can cost noticeably
more in one Region than another, so price is a real input to the decision.

## Takeaway

These four often pull in different directions — the cheapest Region may not be the
closest to users, and the closest may not satisfy governance rules. Region selection
is a trade-off: usually start from the hard constraints (governance, then required
service availability), then optimize the remaining options for latency and cost.
