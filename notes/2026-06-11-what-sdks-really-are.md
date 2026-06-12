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
