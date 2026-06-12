---
title: CapEx to OpEx Shift
type: note
domain: cloud-foundations
date: 2026-06-11
tags:
  - aws
  - cost
  - cloud-economics
  - well-architected
---

# CapEx to OpEx Shift

> Part of [[learning-plan/01-cloud-foundations/01-cloud-foundations|Cloud Foundations]].

One of the foundational "why cloud" arguments: converting large upfront capital
expenditures into predictable operational expenses, improving cash flow and planning.

## The two terms

- **CapEx (capital expenditure):** a large, upfront purchase of an asset you own —
  buying servers, building a data center, paying for it all before serving a single
  customer. In accounting terms it's a big lump that gets depreciated over years.
- **OpEx (operational expenditure):** ongoing, pay-as-you-go costs of running the
  business, like a utility bill. In cloud terms, you pay monthly for what you used.

## The shift

Instead of spending (say) $500K upfront on hardware that you *hope* matches future
demand, you rent capacity from AWS and pay as you go. Cost moves from one big bet at
the start to a stream of smaller, predictable payments.

## Why it matters

- **Cash flow:** Capital stays in the business (product, hiring, growth) instead of
  being sunk into depreciating hardware. Especially valuable for startups.
- **Predictable financial planning:** Costs scale with usage rather than arriving as
  occasional large purchases, so budgets track the actual shape of the business.
- **No over/under-provisioning bet:** CapEx forces you to guess capacity years ahead —
  overbuy and you waste money on idle hardware, underbuy and you can't serve demand.
  OpEx + elasticity means provisioning to current need and adjusting.

## Analogy

CapEx = buying a car (big upfront cost, you own it, you eat depreciation and
maintenance). OpEx = rideshares (pay per trip, no upfront cost, scale up/down freely).
Cloud is the rideshare model for compute.

## Nuance

The shift isn't automatically *cheaper* in absolute terms — at very large, steady-state
scale, owning hardware can cost less per unit. The win is flexibility, lower risk, and
not tying up capital. Connects to the Well-Architected **Cost Optimization** pillar.
