---
title: IAM Users, Groups, Roles & Policies
type: note
domain: security-iam
date: 2026-06-17
source: "Book: Amazon Web Services in Action (Figure 5.6) + own notes"
tags:
  - aws
  - security
  - iam
  - users
  - groups
  - roles
  - policies
---

# IAM Users, Groups, Roles & Policies

> Part of [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]].
> Related: [[learning-plan/06-security-iam/shared-responsibility-model|Shared Responsibility Model]]
> · [[learning-plan/01-cloud-foundations/aws-is-services-over-hardware-via-api|The API is the only door in]]

The four IAM concepts click once you split them along **two separate questions**:

1. **WHO are you?** (identity / authentication) → **users, groups, roles**
2. **WHAT may you do?** (permissions / authorization) → **policies**

> Big idea: identity and permissions are **decoupled**. The *same* policy block can attach
> to a user, a group, or a role (see Figure 5.6 — every Policy box looks identical).

## The simple version

- **User** — an individual person with their own permanent credentials, so nobody
  has to share a password.
- **Group** — a bucket of users. Attach a policy once to the "Finance" group
  instead of to 50 people one by one.
- **Role** — a **temporary hat** anyone (or anything) can wear. A user can assume
  a role for temporary powers; an AWS service (e.g. EC2) can assume one to reach
  another service (e.g. S3). Safer, because there's no permanent password to leak.
- **Policy** — the actual **rulebook**: a JSON document saying "Allow S3 access" or
  "Deny billing access." On its own it does nothing — it only takes effect once
  attached to a User, Group, or Role.

## The "WHO" trio

All three are identities that can call the AWS API. What separates them is **what kind of
credentials they use** and **what they represent.**

### IAM User — permanent identity, long-term credentials

- Represents a specific **person** or a workload running **outside** AWS.
- Has **long-lived credentials**: password (console) and/or access keys (API/CLI).
- Example: you logging into the console; an on-prem server uploading to S3.
- Defining trait: **static, long-term credentials** — convenient but can leak.

### IAM Group — a bucket of users (admin convenience)

- **Not** something you authenticate as — nothing logs in "as a group."
- Attach a policy once to the group; every member **inherits** it.
- Example: a `Developers` group; add a new hire → they instantly get the permissions.
- Defining trait: **carries no credentials of its own.** Exists only to apply one policy
  to many users.

### IAM Role — temporary identity, assumed on demand

- Represents an **AWS resource/service** (book's EC2 example) or a temporary identity that
  people/services **assume**.
- **No permanent credentials.** On assume, AWS issues **temporary credentials** that
  expire (minutes–hours).
- Example: a role **attached** to an EC2 instance → code on it gets temp credentials to
  call the API, with no access keys stored on the box.
- Defining trait: **temporary credentials** → the preferred, more secure pattern (nothing
  static to leak).

## User vs Role — the distinction people actually struggle with

| | IAM User | IAM Role |
| --- | --- | --- |
| Represents | A person or external (non-AWS) workload | An AWS resource/service, or an assumed identity |
| Credentials | **Long-term** (password / access keys) | **Temporary** (issued on assume, auto-expire) |
| How it's used | You authenticate *as* it | It's **assumed** or **attached** to a resource |
| Security posture | Static keys can leak | No static secret — preferred |
| Book's framing | Authenticate people/workloads *outside* AWS | Authenticate AWS resources (e.g. EC2) |

> **Rule of thumb:** inside AWS → **role**. Outside AWS / a human → **user**. Modern best
> practice pushes even humans toward roles (federation/SSO) to avoid long-term keys.

## The "WHAT" — IAM Identity Policy

- A **JSON document** listing permissions: which **actions** (e.g. `s3:GetObject`) on which
  **resources** are **Allowed** or **Denied**.
- Grants **nothing on its own** — only takes effect once **attached** to a user, group, or
  role.
- Called an *identity* policy because it attaches to an identity. (A *resource* policy
  attaches to the resource instead — e.g. an S3 bucket policy — that's the next layer.)

## Reading Figure 5.6

```
                         AWS API
                        ▲       ▲
         can call ──────┘       └────── can call
   User ──member of──► Group        Role
    │  +Policy          +Policy      +Policy
    │                                 ▲
 (long-term keys)               attached to
                                  EC2 Instance
                              (gets temp credentials)
```

- **User / Group / Role** = identities (the WHO).
- **Group** = give many users the same policy; not something you authenticate as.
- **Policy** = the permissions (the WHAT), attached to any of them.
- **Role** = how AWS resources (and federated humans) get *temporary* permissions.

All arrows point at the **AWS API** because IAM is the **lock on the only door into AWS**
(see [[learning-plan/01-cloud-foundations/aws-is-services-over-hardware-via-api|the API is the only door in]])
— it decides which identity may call which API action.

## Exam-relevant notes

- "EC2 needs to access S3" → attach an **IAM role** to the instance (never hardcode keys).
- "Give 20 developers the same permissions" → put them in a **group**, attach one policy.
- "Authenticate an on-prem app / a human" → **user** (or better, federation → role).
- Policies grant nothing until **attached**; default is implicit **deny**, and an explicit
  **Deny** always wins.
- **Identity policy** attaches to user/group/role; **resource policy** (e.g. S3 bucket
  policy) attaches to the resource.
