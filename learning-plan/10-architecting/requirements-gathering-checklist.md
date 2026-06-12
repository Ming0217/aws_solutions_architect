---
title: Requirements Gathering Checklist
type: note
domain: architecting
date: 2026-06-11
source: AWS Requirements Checklist (Skill Builder, © 2025 AWS)
tags:
  - aws
  - architecting
  - discovery
  - requirements
  - well-architected
---

# Requirements Gathering Checklist

> Part of [[learning-plan/10-architecting/README|Architecting & Best Practices]].
> Source PDF: [[resources/Requirements_Checklist.pdf|Requirements Checklist (AWS)]]
> Related: [[learning-plan/10-architecting/well-architected-as-a-process|Well-Architected as a Process, Not a Checklist]]

## Key lessons

- **Architecture starts with discovery, not services.** The job of a solutions
  architect begins by understanding the business and its constraints — services are
  chosen *after* the requirements are clear. This checklist is a structured way to run
  that discovery conversation.
- **Requirements are both technical and organizational.** The very first category is
  business goals, stakeholders, and timelines — not tech. If you don't know how success
  is measured or who decides, you can't design the right thing.
- **The categories map closely onto the Well-Architected pillars.** Security, resilience,
  performance, cost, and operations (monitoring) all show up here. Treat this as the
  intake form that feeds a Well-Architected review.
- **Surface the non-negotiables early.** Compliance regimes, data residency, RTO/RPO,
  and budget ceilings are constraints that eliminate options before you start designing.
  Find them first so you don't design something you have to throw away.
- **Ask about the current state and the future.** Many questions ask "how do you do this
  today?" and "what are your plans?" — discovery captures the trajectory (migrations,
  growth, launches), not just a snapshot.

## The 17 discovery areas

| # | Area | What you're trying to learn | Maps to (WAF pillar) |
| --- | --- | --- | --- |
| 1 | Organization-based strategies | Business goals, stakeholders, mandates, timelines, dependencies | Operational excellence |
| 2 | Security | Encryption, data residency, identity/access, threat models, secrets, patching | Security |
| 3 | Storage needs | Data types, access patterns (hot/warm/cold), durability, retention, object/block/file | Reliability / Cost |
| 4 | Monitoring & alerting | Metrics, incident response, alert routing, SLIs/SLOs, existing tools | Operational excellence |
| 5 | Resilience | Multi-AZ/region, failover, downtime tolerance, failure modes, auto vs manual recovery | Reliability |
| 6 | Disaster recovery & business continuity | RTO/RPO, DR strategy (pilot light, warm/hot standby), DR testing | Reliability |
| 7 | Performance | Latency/throughput targets, cold starts, peak times, SLAs, how perf is measured | Performance efficiency |
| 8 | Scaling | Demand fluctuation, scale triggers, horizontal/vertical, burst traffic, per-component policies | Performance / Reliability |
| 9 | Cost optimization | Budget, spot/serverless, reservations (Savings Plans/RIs), tagging, governance | Cost optimization |
| 10 | Access, authz & authn | Who needs access, IdPs/SSO, least privilege, temp credentials, env separation, audit | Security |
| 11 | Connectivity | Internet/VPN/Direct Connect, private connectivity, hybrid, segmentation, peering/TGW | Reliability / Security |
| 12 | Name resolution | Internal/external DNS, custom domains, split-horizon, Route 53, health checks | Reliability |
| 13 | Compliance | GDPR/HIPAA/SOC 2, audit trails, data sovereignty, automated enforcement (Config, SCPs) | Security |
| 14 | Capacity management | Expected volumes, forecasting, quotas, growth projections, under-utilization | Cost / Performance |
| 15 | Compute needs | CPU/GPU/memory profile, containers vs serverless, OS/runtime, licensing | Performance / Cost |
| 16 | Data needs & databases | Data types, CAP trade-offs, relational/NoSQL, replication, analytics, migration | Reliability / Performance |
| 17 | Session & state management | Session persistence, sticky sessions, cross-region state, shared stores (Redis/DynamoDB) | Reliability |

## High-value questions worth memorizing

These come up constantly in real designs and on the exam:

- **RTO / RPO** — Recovery Time Objective (how fast you must recover) and Recovery Point
  Objective (how much data loss is acceptable). These two numbers drive the entire DR
  strategy choice (backup & restore → pilot light → warm standby → multi-site active).
- **Hot / warm / cold data** — access frequency drives storage class and cost decisions
  (e.g. S3 Standard vs Infrequent Access vs Glacier).
- **SLIs vs SLOs** — what you measure vs the target you commit to.
- **Horizontal vs vertical scaling** — add more instances vs make instances bigger.
- **Least privilege** — grant only the access required, enforced via roles/policies.

## My take / feedback

- This is essentially a **reusable intake template**. Worth keeping a copy in
  `templates/` if you start doing mock designs, so each exercise begins the same way.
- The strongest habit it builds: **let requirements drive services, not the reverse.**
  It's tempting (especially early on) to jump to "use Lambda + DynamoDB"; this forces
  you to justify choices against durability, latency, compliance, and cost first.
- Not every question applies to every workload. In practice you triage — start with
  business goals, constraints (compliance/cost/DR), then drill into the technical
  categories that matter for *this* workload.
- Natural next step: take one sample workload and actually answer these 17 areas, then
  sketch the architecture. That turns the checklist from passive reading into practice.
