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
