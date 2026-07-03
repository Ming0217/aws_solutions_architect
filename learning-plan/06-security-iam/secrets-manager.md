---
title: AWS Secrets Manager
type: note
domain: security-iam
date: 2026-07-03
source: Skill Builder course + own notes
tags:
  - aws
  - security
  - secrets-manager
  - kms
---

# AWS Secrets Manager

> Part of [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]].
> Related: [[learning-plan/06-security-iam/kms-key-management-service|KMS (Key Management Service)]]
> · [[learning-plan/06-security-iam/iam-users-groups-roles-policies|IAM Users, Groups, Roles & Policies]]

## The simple version

A service that acts as a **secure vault**. It replaces hardcoded passwords in
your scripts with a secure API call.

## The Problem

Storing passwords in plain text (like `DB_PASSWORD="password123"`) is a major
security risk. If you share your code, you share your secrets.

## The Solution

Your code (or CLI) says "Hey AWS, give me the secret named `lab-db-secret`",
and AWS returns the password **only if the request has permission**.

## How it chains together with IAM and KMS

Under the hood, every secret is **encrypted at rest with a KMS key** (the
AWS-managed `aws/secretsmanager` key by default, or a customer managed key like
the one from [[learning-plan/06-security-iam/kms-key-management-service|the KMS note]]).
Retrieving a secret is really:

```
IAM authorizes the API call ─► Secrets Manager fetches the encrypted blob
                             ─► KMS decrypts it ─► plaintext returned to caller
```

Same two-gate pattern as SSE-KMS: `secretsmanager:GetSecretValue` **and**
`kms:Decrypt` both have to be allowed — access control (IAM) and encryption
(KMS) are separate layers working together, not one substituting for the other.

## Key Benefits

- **Secrets are encrypted at rest using KMS.**
- **Access is controlled via IAM policies.**
- **Automatic rotation can be configured.**
- **Audit trail via CloudTrail.**

## Automatic rotation — the headline feature vs. "just storing" secrets

For supported databases (RDS, Aurora, DocumentDB, Redshift), Secrets Manager
can run a **Lambda function on a schedule** that rotates the actual database
password *and* updates the stored secret atomically. Your app never needs to
change — it always fetches the *current* value via API rather than having a
password baked into config/code.

## Secrets Manager vs SSM Parameter Store

The natural point of comparison — both store config/secrets, both can encrypt
via KMS (Parameter Store's `SecureString` type):

| | Secrets Manager | SSM Parameter Store |
| --- | --- | --- |
| Automatic rotation | Yes, built-in (Lambda-based) | No |
| Cost | Per-secret + per-API-call | Free tier available, cheaper |
| Typical use | DB credentials needing rotation | General encrypted config values |

> **Rule of thumb:** "need automatic rotation" → Secrets Manager. "just need
> encrypted config, cost-sensitive" → Parameter Store.

## Exam-relevant notes

- Secrets Manager never gives out the secret unless the caller's IAM identity
  has `secretsmanager:GetSecretValue` permission — same "grants nothing until
  attached" rule as any other IAM policy.
- Encryption at rest is via KMS by default — nothing extra to configure unless
  you want a customer managed key instead of the AWS-managed one.
- Rotation is what differentiates it from Parameter Store — pick Secrets
  Manager specifically when a scenario mentions rotating DB credentials.
- Every retrieval is logged in CloudTrail — same audit-trail benefit as KMS
  `Decrypt` calls.

## Questions / things to revisit

-
