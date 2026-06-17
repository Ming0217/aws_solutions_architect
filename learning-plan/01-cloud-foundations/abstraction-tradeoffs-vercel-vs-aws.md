---
title: Abstraction Trade-offs — Vercel vs AWS
type: note
domain: cloud-foundations
date: 2026-06-11
source: Own discussion + Amazon Web Services in Action (John's web shop example)
tags:
  - aws
  - cloud-foundations
  - abstraction
  - vercel
  - tradeoffs
---

# Abstraction Trade-offs — Vercel vs AWS

> Part of [[learning-plan/01-cloud-foundations/01-cloud-foundations|Cloud Foundations]].
> Builds on [[learning-plan/01-cloud-foundations/levels-of-abstraction|Levels of Abstraction in AWS]]
> and [[learning-plan/01-cloud-foundations/cloud-service-models|Cloud Service Models]].

## The question

Is Vercel "better" than AWS because it abstracts away more — push to GitHub, connect,
and you're almost done?

## The honest answer: it's a trade-off, not a ranking

**Where the abstraction argument is right:** for a frontend / full-stack JS app, Vercel
removes huge operational friction (builds, hosting, CDN, TLS, scaling, deploy previews).
For a small team or MVP, it's often genuinely the better choice. The abstraction ladder
on-prem → AWS → Vercel is a real progression.

**Where the comparison breaks down:**

1. **Different scopes.** Vercel is a narrow, opinionated platform for web frontends +
   serverless functions. AWS is general-purpose and spans *every* abstraction level and
   workload type (databases, data warehouses, ML, queues, batch, IoT...). It's not
   "Vercel is more abstracted than AWS" — it's "Vercel is a specialized high-abstraction
   slice; AWS is the whole spectrum."
2. **AWS also offers very high abstraction.** A fair comparison to Vercel isn't
   "EC2 + load balancers" — it's **Amplify Hosting**, **App Runner**, or
   **S3 + CloudFront + Lambda**. The difference: AWS *lets* you drop to a lower level
   when needed; Vercel makes that choice for you.
3. **Vercel runs on AWS.** It's a convenience layer on top of AWS infra. You pay for the
   convenience with **cost at scale**, **less control** (no tuning the internals), and
   **lock-in / quota limits**. The abstraction that saves work also removes escape hatches.

**Takeaway:** higher abstraction isn't universally better — it trades convenience for
control, flexibility, and cost. Vercel optimizes one end of the dial; AWS gives you the
whole dial. Best fit depends on the workload (many teams use both — e.g. Vercel front end
+ AWS/Supabase backend).

## Worked example: John's web shop moving up the ladder

John's cloud improvements are all about climbing the abstraction ladder *within AWS*,
piece by piece and on his terms:

| Improvement | What it does | Abstraction move |
| --- | --- | --- |
| Serve static content (logo, etc.) via a **CDN** | Offloads web servers, speeds delivery (AWS: CloudFront). Split static vs dynamic content. | ↑ higher (managed edge delivery) |
| Switch to **maintenance-free managed services** (database, object store, DNS) | Hands ops burden to AWS → lower operational cost, better quality | ↑ higher (managed services) |
| Run the app on **multiple smaller VMs behind a load balancer** | Same total resources split across VMs at no extra cost; if one fails the load balancer reroutes → better reliability | ↓ stays lower (keeps VM-level control) |

The crux: John **chooses the abstraction level per component**. He goes high where he
wants to shed ops work (CDN, managed DB/object store/DNS) and stays lower where he wants
control over reliability and layout (VMs + load balancer). Vercel would hide all of this
— convenient, but he couldn't make those calls himself.

## The principle

Match the abstraction level to what each part of the workload actually needs. The value
of a broad platform like AWS is the freedom to set that dial per component; the value of
a focused platform like Vercel is that it sets a good default dial for you.
