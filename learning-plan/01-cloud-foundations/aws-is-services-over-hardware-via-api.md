---
title: AWS = Software Services Over Hardware, Reachable Only Through One API
type: note
domain: cloud-foundations
date: 2026-06-17
source: "Book: Amazon Web Services in Action (Figure 4.1) + own notes"
tags:
  - aws
  - cloud-foundations
  - api
  - abstraction
  - architecture
---

# AWS = Software Services Over Hardware, Reachable Only Through One API

> Part of [[learning-plan/01-cloud-foundations/01-cloud-foundations|Cloud Foundations]].
> Related: [[learning-plan/06-security-iam/shared-responsibility-model|Shared Responsibility Model]]
> · [[learning-plan/08-automation-iac/cli-vs-cloudformation-vs-cdk|CLI vs CloudFormation vs CDK]]
> · [[notes/2026-06-11-api-vs-cli-vs-mcp|Direct API vs CLI vs MCP]]

This is the unifying diagram behind several other notes (Figure 4.1: "The AWS cloud is
composed of hardware and software services accessible via an API"). It packs **two**
layered ideas.

## Idea 1: services are software abstractions over physical hardware

Reading the cloud bottom-to-top:

- **Bottom — raw hardware:** physical Compute, Network, and Storage in AWS data centers.
- **Middle — a Software/Hardware boundary:** the software that slices that physical gear
  into rentable units.
- **Top — the services:** Compute (VMs), App (queues, search), Enterprise (directory,
  mail), Deployment (access, monitoring), Storage (object store, archiving), Database
  (relational, NoSQL), Networking (DNS, virtual network).

So a "service" like EC2 or S3 is a friendly **software abstraction sitting on top of
physical machines**. This is exactly where the
[[learning-plan/06-security-iam/shared-responsibility-model|shared responsibility]] line
sits: AWS owns everything **below** the boundary (security *of* the cloud), you own what
you configure **above** it (security *in* the cloud).

## Idea 2: the only door in is the API

The key insight from the figure's geometry: the administrator never touches the services
directly. The "manage services" arrow goes **through the API wedge** — the *only* opening
in the cloud. There is no back door that bypasses it.

```
Console (click) ─┐
CLI (terminal)  ─┤
SDK (code)      ─┼──► AWS API ──► Services ──► Software/Hardware
CloudFormation  ─┤
MCP server      ─┘
```

Everything else I've studied is just a different **handle on that one door**. The
console, CLI, SDKs, CloudFormation/CDK, and even an MCP server are all front-ends that
funnel down to the **same API** (see
[[learning-plan/08-automation-iac/cli-vs-cloudformation-vs-cdk|CLI vs CloudFormation vs CDK]]).
That's why "the raw HTTP API is painful" matters: that API isn't *a* way to manage AWS,
it's *the* way — every tool is a convenience layer over it.

## The combined takeaway

1. **AWS services are software abstractions over physical hardware** — which sets up the
   shared-responsibility boundary and the
   [[learning-plan/01-cloud-foundations/levels-of-abstraction|levels of abstraction]].
2. **Every interaction with those services goes through one API** — every tool is just a
   different ergonomics layer on that single entry point.

## Why an architect cares

- **Everything is automatable.** Because the only entry point is an API, anything you can
  do by clicking, you can script, template, or hand to an agent. This is the foundation
  of Infrastructure as Code.
- **Security focuses on the API.** Access control (IAM) governs who can call which API
  actions — so locking down the API *is* locking down AWS.
