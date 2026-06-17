---
title: Economies of Scale
type: note
domain: cloud-foundations
date: 2026-06-11
source: "Book: Amazon Web Services in Action (+ own notes)"
tags:
  - aws
  - cloud-foundations
  - cost
  - cloud-economics
---

# Economies of Scale

> Part of [[learning-plan/01-cloud-foundations/01-cloud-foundations|Cloud Foundations]].
> Related: [[learning-plan/01-cloud-foundations/capex-to-opex-shift|CapEx to OpEx Shift]]
> · [[learning-plan/01-cloud-foundations/elasticity-and-flexible-capacity|Elasticity & Flexible Capacity]]

## The general concept

Economies of scale = **the more you produce, the less each unit costs.** As output grows,
the *per-unit* cost falls.

### Where the savings come from

- **Spreading fixed costs.** Costs that don't change with volume (a building, R&D, a
  platform) get amortized over more units. A $1M facility is $1,000/unit across 1,000
  units, but $1/unit across 1,000,000.
- **Bulk purchasing power.** Ordering millions of components earns a lower price per
  component than ordering ten (volume discounts).
- **Specialization & efficiency.** At scale you dedicate people/machines to narrow tasks
  and invest in automation that only pays off at high volume.
- **Operational leverage.** Logistics, management, and overhead get cheaper per unit.

**Analogy:** baking one cake at home is costly per cake (whole bag of flour, whole oven);
a bakery making 500/day buys flour by the pallet, runs ovens at full load, and has
specialized staff — far lower cost per cake.

### The catch: diseconomies of scale

Not infinite. Past a point, growth can *raise* per-unit costs (coordination overhead,
bureaucracy, slower communication). The cost curve is U-shaped: falls, flattens, can
eventually rise. "Bigger is cheaper" only holds up to a point.

## How it applies to AWS

AWS operates at huge scale, driving per-unit costs down via the same mechanisms:

- Buys servers/storage/networking in massive volume (bulk purchasing power).
- Amortizes data-center build-out and platform development across millions of customers.
- Runs hardware at high utilization; invests in custom silicon (e.g. Graviton) and
  automation that only make sense at scale.

As its infrastructure grows, AWS's per-unit costs drop — and it **passes part of the
savings on as periodic price cuts**:

- **Jan 2019** — Fargate down 20% (vCPU) and 65% (memory).
- **Nov 2020** — EBS Cold HDD volumes down 40%.
- **Nov 2021** — S3 storage down up to 31% across three storage classes.
- **Apr 2022** — removed inter-data-center traffic charges for PrivateLink, Transit
  Gateway, and Client VPN.

## Takeaways for an architect

- **You benefit *partially*.** AWS keeps some savings (margin) and passes some to
  customers — you're a beneficiary of its scale, not a full owner of it.
- **A structural argument for cloud over DIY.** Matching AWS's per-unit hardware costs
  yourself is hard — you can't reach that purchasing volume or utilization (same reason
  most companies don't run their own power plant).
