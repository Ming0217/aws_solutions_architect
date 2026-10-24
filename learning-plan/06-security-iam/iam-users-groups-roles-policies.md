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

## How a role actually gets associated with a user/group/service

A role isn't "attached" the way a policy is — it's **assumed**. Two things have to
line up for that to work:

1. **The role's trust policy** — a resource-based policy *on the role itself*
   listing which principals may call `sts:AssumeRole` on it (a user ARN, another
   AWS account, or an AWS service like `ec2.amazonaws.com`).
2. **The assumer's own permission** — unless it's an AWS service, the assuming
   user/role also needs an identity policy granting `sts:AssumeRole` on that
   specific role's ARN. Both sides must agree: trust policy says "you may,"
   identity policy says "I'm allowed to try."

How this plays out per identity type:

- **User → Role:** add the user's ARN to the role's trust policy, and grant the
  user (or a group they're in) `sts:AssumeRole` on that role. The user then runs
  `aws sts assume-role` or clicks "Switch Role" in the console to get temporary
  credentials.
- **Group → Role:** never attach a role to a group directly — groups can't
  authenticate or assume anything (no credentials of their own). Instead, attach
  a policy to the group granting members `sts:AssumeRole` rights; each member
  still individually assumes the role when needed.
- **AWS service → Role:** the service is the trusted principal in the trust
  policy (e.g. `ec2.amazonaws.com`), so there's no separate "permission to
  assume" step on the service side.
  - **But the operator wiring it up needs `iam:PassRole`.** The permission
    didn't vanish — it moved. A service isn't an IAM identity in your account, so
    there's nothing to hold an `sts:AssumeRole` identity policy; the gate instead
    falls on *you*. To hand a role to a service (attach the instance profile to
    EC2, set a Lambda execution role), your **own** identity needs `iam:PassRole`
    on that role's ARN. It's the "you can't delegate a role more privileged than
    you're allowed to pass" guardrail — the real control point on the service
    side, and a common exam/security gotcha (often paired with a `iam:PassedToService`
    condition to restrict *which* service a role may be passed to).
  - **EC2** is special: you can't attach a role to an instance directly — AWS
    wraps it in an **instance profile** (a thin container around the role), and
    you attach *that* to the instance at launch or later via Actions → Security
    → Modify IAM role.
  - **Lambda, ECS tasks, etc.** don't need an instance profile — you just pick
    the execution role directly in that service's config.

> Short version: roles are assumed, not attached — except for EC2, where the
> console UI makes it *look* like attaching, but under the hood it's an instance
> profile wrapping the same assume-role mechanism.

## Trust type: "AWS account / This account" (a human assuming a role)

The trust types above were a **service** principal (`ec2.amazonaws.com`). The
other common one is picking **Trusted entity type → AWS account → This account**
when creating a role. This is the "a human (or another role) temporarily puts on
a more-privileged hat" pattern — distinct from service roles.

What it produces is a trust policy whose principal is the **account root**:

```json
{
  "Effect": "Allow",
  "Principal": { "AWS": "arn:aws:iam::<account-id>:root" },
  "Action": "sts:AssumeRole"
}
```

> **`root` here does NOT mean "only the root user" or "everyone automatically."**
> It means "the account is the trust boundary" — i.e. *IAM identities in this
> account are eligible to assume me, provided they also hold `sts:AssumeRole`
> permission for this role.* Both sides must still agree (trust policy says "this
> account may," the user's identity policy says "I'm allowed to try"). Delegating
> trust to the account root is what lets you manage who-can-assume with ordinary
> IAM identity policies instead of editing the trust policy per user.

### Using it from the console — Switch Role (and reading the result)

A user clicks account name (top-right) → **Switch role** → enters account ID +
role name → the console swaps their session for the role's temporary credentials.

**What "it worked" actually looks like:** switch into a role that has *only*
`AmazonS3ReadOnlyAccess` attached, then open the **Roles** page, and you'll get
an access-denied like this (this is **success**, not a bug):

```
User:   arn:aws:sts::<account-id>:assumed-role/finance-manager/<original-user>
Action: iam:ListRoles
Context: no identity-based policy allows the action
```

Two things to read off this, both confirming the mechanics from the sections
above:

1. **The ARN is an `sts::...:assumed-role/...` ARN, not an `iam::...:user/...`
   ARN.** That's the proof you're now running on **STS-issued temporary
   credentials** tied to the role — not your long-term user. The trailing segment
   (`<original-user>`) is the **role session name**, which is how CloudTrail
   traces *which* identity assumed the role.
2. **Everything outside the attached policy is denied.** The page calls
   `iam:ListRoles` to render the list; the hat only grants S3 read-only, so it's
   denied and the page shows "Roles (0)". That denial *is* least privilege
   working — while wearing the role you can do S3-read and nothing else, with your
   normal permissions set aside until you **Switch back**.

> **Positive confirmation:** to see the role *permitting* rather than just
> denying, go to **S3** while switched in — listing/reading buckets works, while a
> write/delete is denied (it's read-*only*), and IAM stays denied. read ✅ /
> write ❌ / everything-else ❌ is the cleanest one-screen demonstration of a
> scoped role.

### Using it from the CLI (the way you'll actually build)

Console Switch Role is fine for a human clicking around; the CLI is how you use
this in practice. The raw mechanism is `sts assume-role`:

```bash
aws sts assume-role \
  --role-arn arn:aws:iam::<account-id>:role/finance-manager \
  --role-session-name finance-session
```

This returns a JSON blob with **temporary** credentials under `Credentials`:

```json
{
  "Credentials": {
    "AccessKeyId": "ASIA...",          // note the ASIA prefix (temp), vs AKIA (long-term user key)
    "SecretAccessKey": "...",
    "SessionToken": "...",             // temp creds ONLY work with this token attached
    "Expiration": "2026-10-19T12:34:56Z"
  },
  "AssumedRoleUser": {
    "Arn": "arn:aws:sts::<account-id>:assumed-role/finance-manager/finance-session"
  }
}
```

Key details:

- **`ASIA...` vs `AKIA...`** — temporary keys start with `ASIA`; long-term user
  keys start with `AKIA`. Quick way to tell at a glance which kind you're holding.
- **The `SessionToken` is mandatory.** Temporary credentials fail with an auth
  error unless the session token travels with them — it's the third piece, not
  optional.
- **`--role-session-name`** is free-form but shows up in CloudTrail and in the
  `assumed-role` ARN, so name it meaningfully (who/why).
- **`Expiration`** — default session is 1 hour; extend with
  `--duration-seconds` up to the role's **max session duration** (default max 1h,
  raisable to 12h on the role).

**Three ways to actually *use* the returned credentials:**

**(a) Export them as env vars** — quick, manual, good for a one-off:

```bash
export AWS_ACCESS_KEY_ID=ASIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...        # don't forget this one
aws s3 ls                           # now runs AS the role
# ...when done, `unset` them or open a fresh shell to drop the hat
```

> This is exactly the "manually copying temp credentials out of the SDK" pattern
> the expiry section below warns about — *this copy will genuinely expire* in ~1h
> and start failing, because it's disconnected from auto-refresh. Fine for a short
> manual task; **not** how long-running code should get credentials.

**(b) Named profile in `~/.aws/config` — the clean, recommended way.** Let the
CLI assume the role for you and auto-refresh; you never touch the raw keys:

```ini
# ~/.aws/config
[profile finance]
role_arn       = arn:aws:iam::<account-id>:role/finance-manager
source_profile = default          # the long-term identity allowed to assume it
# region       = us-east-1
```

```bash
aws s3 ls --profile finance        # CLI assumes finance-manager under the hood
export AWS_PROFILE=finance         # ...or set it for the whole shell session
```

The CLI calls `assume-role` for you, caches the temp creds, and refreshes them
when they expire — no manual token juggling, no stale-credential failures.

**(c) In code (SDK)** — don't call `assume-role` and paste keys around; configure
the SDK's credential provider to assume the role (e.g. boto3's
`profile_name="finance"`, or an `STSAssumeRoleProvider`). Same auto-refresh
benefit as (b). Let the provider chain manage credentials live rather than caching
them yourself.

**The assumer still needs permission.** `source_profile`/your calling identity
must have an identity policy allowing `sts:AssumeRole` on that role ARN, or you
get `AccessDenied` on the assume call itself (the trust policy alone isn't
enough — both sides agree, per the section above):

```json
{
  "Effect": "Allow",
  "Action": "sts:AssumeRole",
  "Resource": "arn:aws:iam::<account-id>:role/finance-manager"
}
```

> **Which trust type to reach for:** human/CLI elevation into a job-function role
> → **AWS account** trust + `sts:AssumeRole` (this section). A workload *inside*
> AWS (EC2/Lambda) → **service** trust + attach/instance-profile (PhotoShare's
> `iam_role_ec2`). Both issue the same kind of `assumed-role` temporary
> credentials — only *who's trusted to assume* differs.

## What happens when a role's temporary credentials expire?

If a role is just a temporary hat, does the app "crash" once the timer runs
out and the service can't authenticate anymore? No — **the hat gets swapped
before it runs out, not just removed.** AWS refreshes the credentials
automatically, ahead of expiry, so under normal operation this is a non-event:

- **EC2:** the instance's metadata service continuously serves fresh temporary
  credentials for the attached role. The AWS SDK's credential provider knows
  the expiry time and fetches a new set in the background well before the old
  ones run out — as long as the instance is running and the instance profile
  stays attached, this refresh cycle just keeps going invisibly.
- **Lambda (and similar managed compute like ECS tasks):** AWS injects
  temporary credentials into each execution environment and manages renewal
  itself, including across warm-start reuse. Nothing in your code has to
  "renew" anything.

**What actually breaks things** isn't expiry — it's someone **detaching the
role**, **deleting it**, or **revoking/narrowing its permissions** while the
app is running. The next API call then fails with `AccessDenied`/`403`,
because the underlying authorization was pulled out from under a running
service — not because credentials "timed out." Whether that "crashes" the app
depends on error handling: a well-written service catches that and
retries/alerts rather than dying outright.

> **Real pitfall to avoid:** if code manually copies temporary credentials out
> of the SDK (e.g. into env vars or a config file) instead of letting the
> SDK's credential provider chain manage them, *that copy* will genuinely
> expire and start failing — because it's been disconnected from the
> auto-refresh mechanism. Always let the SDK fetch credentials live rather
> than caching them yourself.

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
