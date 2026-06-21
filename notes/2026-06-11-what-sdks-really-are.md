---
title: What SDKs really are
type: note
date: 2026-06-11
tags:
  - aws
  - sdk
  - api
  - fundamentals
---

# What SDKs really are

## What I learned

An SDK (Software Development Kit) is a **thin abstraction layer over an API**. Instead
of making raw API calls (building HTTP requests, handling auth, parsing responses,
retrying on failure), a developer pulls in the SDK as a code library and calls its
functions to express business logic.

The API is still doing the work underneath — the SDK just wraps it in idiomatic,
language-native methods. Many companies ship an SDK alongside their API, and many
developers prefer the SDK because it hides the inherent complexity of handling and
making web requests.

```
Your code  ──>  SDK methods  ──>  (HTTP requests/auth/retries)  ──>  API  ──>  Service
```

## Why it matters / context

- **AWS connection:** This is exactly what the AWS SDKs (boto3 for Python, the
  JavaScript SDK, etc.) are — wrappers over the underlying AWS service APIs. When
  you call `s3.put_object(...)` in boto3, the SDK is signing and sending an HTTPS
  request to the S3 API for you.
- As a solutions architect, the takeaway is *the SDK and the API expose the same
  capabilities* — the SDK is a convenience layer, not a separate service. Anything
  the SDK does, you could do with raw API calls; the SDK just handles request
  signing, retries/backoff, pagination, and serialization so you don't have to.

## CLI vs a program (SDK) — same API, different driver's seat

> Related: [[learning-plan/08-automation-iac/cli-vs-cloudformation-vs-cdk|CLI vs CloudFormation vs CDK]]

Key thing that trips people up: **a CLI tool is itself a regular program** (the AWS CLI
is written in Python). So the difference isn't "program vs not-a-program" — it's **who
writes the logic and how you express intent.**

- **CLI** — someone already wrote the program. You *run* it by typing a command + flags:
  ```bash
  aws ec2 start-instances --instance-ids i-1234567890
  ```
  You provide the command and arguments; the tool provides all the logic, auth, and
  output formatting. Your vocabulary is whatever commands/flags the author exposed.

- **Program (via SDK)** — you *write* the logic yourself, importing the SDK (e.g. boto3):
  ```python
  import boto3
  ec2 = boto3.client("ec2")
  for r in ec2.describe_instances()["Reservations"]:
      for i in r["Instances"]:
          if i["State"]["Name"] == "running":
              print(i["InstanceId"])
  ```
  You own the control flow (loops, conditionals, error handling, combining calls); the
  SDK provides the low-level API plumbing.

| | CLI | Program (SDK) |
| --- | --- | --- |
| What it is | A finished program you *run* | Code you *write* |
| Express intent via | Command + flags | Logic in a language |
| Control flow (loops, if/else) | Limited (shell scripting glue) | Full language power |
| Best for | Quick one-off tasks, manual ops | Complex logic, apps, reusable automation |
| Who wrote the logic | The tool's author | You |

**Analogy:** the CLI is a microwave with labeled buttons (fast, but only the buttons you're
given); a program/SDK is raw ingredients + a stove (more work, but you can cook anything).

**The bridge:** because a CLI is just a program, you *can* string commands together in a
**shell script** with bash loops/conditionals. Once that logic gets complex, you're
writing a program the hard way — the signal to switch to an SDK. Either way, both bottom
out in the **same AWS API** (see [[learning-plan/01-cloud-foundations/aws-is-services-over-hardware-via-api|the API is the only door in]]).

## Nuances / things to revisit

- **"Thin" varies.** Some SDKs are near pass-throughs; others add real value beyond
  wrapping requests — automatic retries with backoff, request signing (SigV4 for AWS),
  pagination helpers, waiters, credential resolution, and type safety. The "thin
  abstraction" intuition is right, but expect some SDKs to do more than forward calls.
- **Same capabilities, not always same timing.** SDKs can lag the API. A brand-new
  service feature may be callable via the raw API before it lands in every language's
  SDK. Rare, but it's why the API — not the SDK — is the source of truth.
- **Why an architect cares.** The distinction drives design choices: e.g. a Lambda
  using boto3 vs. a tiny edge component making a raw signed request to avoid bundling
  the whole SDK. Since they're equivalent under the hood, you can choose based on
  cold-start size, dependencies, and language support.

## Source

AWS Solutions Architect Learning Plan (Skill Builder).
