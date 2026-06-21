---
title: CLI vs CloudFormation vs CDK
type: note
domain: automation-iac
date: 2026-06-11
tags:
  - aws
  - iac
  - cli
  - cloudformation
  - cdk
---

# CLI vs CloudFormation vs CDK

> Part of [[learning-plan/08-automation-iac/08-automation-iac|Automation & IaC]].
> Related: [[notes/2026-06-11-api-vs-cli-vs-mcp|Direct API vs CLI vs MCP]]

## Why these tools exist (the raw API is painful)

Underneath everything is the **AWS HTTP API**. You *can* call it directly, but it's very
low-level and forces you to repeat the same plumbing on every request:

- **Authentication** — sign each request with your credentials (AWS SigV4).
- **(De)serialization** — hand-build the request body and parse the raw response.
- Plus retries, error handling, pagination, endpoint URLs, etc.

The CLI, SDKs, and CloudFormation all exist to **hide that repetitive work**. They differ
only in *how you express intent* and *how much they track for you* — but they all bottom
out in the same HTTP API:

- **CLI** — do it from a terminal.
- **SDK** — do it from your programming language (see [[notes/2026-06-11-what-sdks-really-are|what SDKs really are]]).
- **CloudFormation** — describe the desired end state in a template; it figures out the
  API calls.

## The shared foundation

All three are just different front-ends over the same AWS service APIs (same idea as
[[notes/2026-06-11-what-sdks-really-are|what SDKs really are]]). The real question is
*how* you express what you want, and *whether the tool tracks it as a managed unit*.

## Comparison

| | AWS CLI | CloudFormation | CDK |
| --- | --- | --- | --- |
| Interface | Terminal commands | Template files (JSON/YAML) | Code (TypeScript, Python, Java, Go, C#) |
| Paradigm | **Imperative** ("do this now") | **Declarative** ("here's the desired end state") | **Imperative code → declarative template** |
| State tracking | None — fire and forget | Yes — manages resources as a **stack** | Yes — synthesizes to CloudFormation, deploys as a stack |
| Best for | Quick tasks, scripting, ad-hoc queries | Repeatable, version-controlled infra | Same as CFN, but with loops/logic/reuse |

## Key relationships

- **CLI vs the other two = imperative vs IaC.** `aws s3 mb s3://my-bucket` happens
  immediately, but nothing remembers those commands belong together. CloudFormation and
  CDK define infrastructure as a managed unit that can be created, updated, and deleted
  as a whole, with rollback and drift detection.
- **CDK sits on top of CloudFormation.** CDK doesn't provision resources directly. You
  write code, run `cdk synth`, and it *generates a CloudFormation template*, which
  CloudFormation then deploys. CDK is a higher-level, programmable way to produce CFN.
- **They overlap in practice.** You can use the CLI to deploy a CloudFormation template
  (`aws cloudformation deploy`), so the CLI is also a way to *drive* IaC, not just an
  alternative to it.

```
CDK code ──(cdk synth)──> CloudFormation template ──> CloudFormation ──> AWS resources
AWS CLI  ─────────────────────────────────────────────────────────────> AWS resources
```

## Exam rule of thumb

- Imperative one-off or scripting → **CLI**
- Declarative templates → **CloudFormation**
- Real programming language with loops, conditionals, and reusable components that
  compiles down to CloudFormation → **CDK**

## Why CloudFormation over scripts (declarative + the honest caveats)

**The core idea — declarative.** You *describe how the infrastructure should look*, not
the actions or the sequence to build it. You say "I want a load balancer, two instances,
and a database"; CloudFormation works out the *how* and *in what order*.

**The genuine wins (from the book):**

- **Consistent** — one clear language for infrastructure instead of every person scripting
  it differently (a real onboarding hurdle).
- **Handles dependencies** — builds a dependency graph and orders create/delete for you.
  This is the killer feature; hand-written scripts drop you into "dependency hell" (e.g.
  registering a web server with a load balancer that doesn't exist yet).
- **Reproducible** — spin up identical test and prod environments from the same template.
- **Testable** — create infra from a template, run tests, tear it down.
- **Updatable** — it diffs the template and applies only what changed.
- **Minimizes human error** — no tired operator fat-fingering the console at 3 a.m.
- **Documentation as code** — the JSON/YAML template lives in Git; the template *is* the
  spec.
- **Free** — no charge for the CloudFormation service itself.

**The honest caveats (true but rosier than reality):**

1. **"Free" = the *service* is free, the *resources* are not.** CloudFormation doesn't
   charge, but every EC2/NAT/RDS resource it creates costs the usual amount. "Free" is
   only the orchestration layer.
2. **"Updatable... smoothly" undersells the risk.** Some property changes trigger a
   **resource replacement** (destroy + recreate), not an in-place edit — e.g. certain RDS
   changes can replace the database. Always read the **change set** before applying to
   prod.
3. **"Clear language" but verbose.** Raw JSON/YAML gets long and repetitive at scale —
   which is exactly why **CDK** exists (write code, synth a template).
4. **"Most powerful" = most powerful *AWS-native* tool.** Many teams pick **Terraform**
   for multi-cloud or its ecosystem. Not a contradiction (this is an AWS book), just a
   scope note.

**Net:** the durable takeaway is the **declarative + dependency-handling + reproducible**
trio — that's genuinely why IaC beats scripts. Just mentally tag *free* (service only),
*updatable* (mind replacements), and *most powerful* (AWS-native) so the enthusiasm
doesn't hide the sharp edges.
