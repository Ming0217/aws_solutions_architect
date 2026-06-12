---
title: Well-Architected as a Process, Not a Checklist
type: note
domain: architecting
date: 2026-06-11
source: Skill Builder transcript (Joe & Melissa dialogue)
tags:
  - aws
  - architecting
  - well-architected
  - customer-engagement
---

# Well-Architected as a Process, Not a Checklist

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & Best Practices]].
> Builds on [[learning-plan/10-architecting/requirements-gathering-checklist|Requirements Gathering Checklist]].

## The core lesson

The Well-Architected Framework is **not a yes/no checklist** you complete once to get a
"perfect" architecture. It's an **iterative process**, and each pillar is a **lens** that
helps uncover hidden risks and optimization opportunities across the whole architecture.
The right question isn't "do you have encryption?" but "how does your encryption strategy
align with your security objectives?"

## Key takeaways

- **Pillars are evaluated against business requirements, not in the abstract.** The
  framework picks up where requirements gathering leaves off — e.g. the Reliability
  pillar isn't "do you have backups?", it's "does your recovery strategy meet the RTO/RPO
  and SLOs we uncovered?"
- **Use pillar questions as discussion prompts.** Walking the pillars during an
  architecture session naturally opens the right conversations — e.g. Performance
  Efficiency leads into "do your workload patterns actually make Lambda more efficient
  than EC2?" rather than just "have you considered serverless?"
- **The framework exposes cost mismatches.** Mapping real business needs against the
  current design surfaces waste. Example from the transcript: a customer's "everything
  must be real time" approach was expensive, but only ~20% of the workload truly needed
  real-time processing — the rest could be batched, cutting cost significantly.
- **The framework is a teaching tool, not a rulebook to enforce.** When customer wants
  conflict with best practices (single-AZ to save money, "no encryption because the data
  isn't sensitive"), treat them as teaching moments about risk vs reward — not roadblocks.

## Techniques for the tough conversations

- **Ask for their reasoning first.** Instead of immediately pushing back (e.g. on putting
  everything in public subnets), ask them to walk you through *why* — then explore it
  together.
- **The "future story" approach.** Walk through scenarios: what happens if there's a
  security breach? What if industry regulations change? Helps customers see past
  immediate convenience.
- **Share anonymized real-world examples.** e.g. the customer who saved money skipping
  redundancy, then lost 10x that during their first major outage. Make it relevant to
  *their* situation.
- **Translate guidelines into business impact.** Learning happens when best practices are
  framed as practical, real-world consequences — not quoted as rules.

## Crawl, walk, run

You can't always reach "perfect" immediately. Build a **roadmap for gradual alignment**
rather than demanding instant compliance: start with the most critical aspects and build
from there. It makes the transformation manageable and builds trust.

## A living framework

- Treat the architecture as something that **evolves with the workload**. As business
  needs change or new services launch, use the framework to re-evaluate and optimize.
- **Sustainability pillar:** thinking about environmental impact often aligns with cost
  optimization — right-sizing instances, auto-scaling, etc.
- The goal is a **culture of continuous improvement**: cloud architecture is a journey,
  not a destination.

## My take

This reframes the framework from an audit artifact into a *consulting method*. Two things
worth internalizing: (1) the soft skills — asking why, storytelling, roadmapping — are as
important as knowing the pillars; and (2) the six pillars (Operational Excellence,
Security, Reliability, Performance Efficiency, Cost Optimization, Sustainability) are most
useful as recurring review lenses, not a one-time gate.
