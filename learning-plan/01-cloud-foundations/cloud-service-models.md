---
title: Cloud Service Models (IaaS, PaaS, SaaS)
type: note
domain: cloud-foundations
date: 2026-06-11
source: "Book: Amazon Web Services in Action (+ own notes)"
tags:
  - aws
  - cloud-foundations
  - service-models
  - iaas
  - paas
  - saas
---

# Cloud Service Models (IaaS, PaaS, SaaS)

> Part of [[learning-plan/01-cloud-foundations/01-cloud-foundations|Cloud Foundations]].
> Related: [[learning-plan/06-security-iam/shared-responsibility-model|Shared Responsibility Model]]

## The three classic models

From *Amazon Web Services in Action*:

- **IaaS (Infrastructure as a Service)** — fundamental resources like computing, storage,
  and networking, typically via virtual machines. Examples: **Amazon EC2**, Google
  Compute Engine, Microsoft Azure Virtual Machines.
- **PaaS (Platform as a Service)** — platforms to deploy custom applications to the cloud.
  Examples: **AWS Elastic Beanstalk**, Google App Engine, Heroku.
- **SaaS (Software as a Service)** — combines infrastructure and software running in the
  cloud, such as office applications. Examples: **Amazon WorkSpaces**, Google Workspace
  (formerly "Google Apps for Work"), Microsoft 365.

## The mental model: a spectrum of control

The models are a spectrum of *how much you manage vs how much the provider manages*.
Moving IaaS → PaaS → SaaS, you hand off more responsibility (and give up more control):

| Model | You manage | Provider manages | Example |
| --- | --- | --- | --- |
| IaaS | OS, runtime, app, data | Hardware, virtualization, networking | EC2 |
| PaaS | App, data | OS, patching, scaling, platform | Elastic Beanstalk |
| SaaS | Just your usage/config & data | Everything else | Microsoft 365 |

This maps directly onto the **shared responsibility model**: the more managed the
service, the smaller the customer's slice of responsibility.

## Refinements / things the book predates

- **Amazon WorkSpaces** is more precisely **DaaS (Desktop-as-a-Service)** — managed
  virtual desktops. Fine to bucket under SaaS in an intro, but it's sometimes called out
  separately. A purer SaaS example is Amazon WorkMail.
- **"Google Apps for Work"** is the old name — now **Google Workspace**.
- A fourth common model has since become mainstream: **FaaS / serverless**
  (e.g. **AWS Lambda**). You deploy individual functions; the provider handles
  everything down to the runtime and scales to zero when idle. It sits between PaaS and
  SaaS on the "how much you manage" spectrum.

## Worked example: where does Vercel fit?

**Vercel is a textbook PaaS** — you push code (or connect a Git repo) and it handles the
build, deployment, hosting, scaling, CDN, and TLS. You manage your app and data; never
the servers, OS, or patching.

- It's a **specialized PaaS**, opinionated toward frontend / full-stack JavaScript (it's
  the company behind Next.js). Marketing calls it a "frontend cloud," but the model is
  PaaS.
- Its backend pieces — **serverless functions and edge functions** — are the **FaaS**
  model. So Vercel is PaaS for app deployment + FaaS for backend logic.
- It **runs on IaaS underneath** (AWS). This shows the layered nature of the models: a
  PaaS/SaaS provider is usually someone else's customer at the IaaS layer.
- **Closest AWS analogy:** AWS Amplify Hosting (PaaS for frontend/full-stack) on top of
  Lambda-style functions.

## Worked example: where does Supabase fit?

**Supabase is best classified as BaaS (Backend-as-a-Service)** — a specialized flavor of
PaaS focused on the backend. Where Vercel hosts *your app code*, Supabase gives you
ready-made *backend building blocks* you wire into your app without running servers:

- Hosted **Postgres database**, **Auth** (with row-level security), **Storage**,
  **Realtime** subscriptions, and auto-generated **APIs** over your tables.
- **Edge Functions** for custom server-side logic — again the **FaaS** model.
- **Runs on IaaS underneath** (AWS), same layered pattern as Vercel.

Easy way to remember: **Vercel hosts your frontend/app (PaaS); Supabase is your
backend-in-a-box (BaaS).** They're often used together (Next.js on Vercel + data/auth on
Supabase). Supabase pitches itself as an open-source **Firebase** alternative, and
Firebase is the other classic BaaS example.

> **Caveat:** BaaS isn't one of the book's three models — it's a newer, more specialized
> category under the PaaS umbrella. The strict IaaS/PaaS/SaaS taxonomy would just call it
> PaaS.

## Takeaway

The book's classification is correct — it just predates a couple of naming changes and
the rise of serverless. For architecting decisions, think in terms of the control/effort
trade-off: pick the most managed model that still gives you the control the workload
actually needs.
