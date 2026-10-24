---
title: IAM Federation (external identities → temporary AWS access)
type: note
domain: security-iam
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - security
  - iam
  - federation
  - sts
  - sso
  - saml
  - oidc
  - cognito
---

# IAM Federation (external identities → temporary AWS access)

> Part of [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]].
> Related: [[learning-plan/06-security-iam/iam-users-groups-roles-policies|IAM Users, Groups, Roles & Policies]]
> · [[learning-plan/06-security-iam/oauth2-oidc-authentication-authorization|OAuth2 / OIDC — AuthN vs AuthZ]]

**Federation lets identities that live _outside_ IAM sign in and get AWS
permissions — without an IAM user for each person.** You trust an external
identity provider (IdP) to say *who* someone is; IAM still decides *what* they
can do, via a role.

> One-liner: **authentication happens elsewhere; authorization stays in IAM
> roles.** The external IdP vouches for the identity; the IAM role carries the
> permissions; STS hands out **temporary** credentials to bridge the two.

This is the [[learning-plan/06-security-iam/iam-users-groups-roles-policies|"role
as a temporary hat"]] idea pointed outward: instead of an AWS user or service
assuming the role, an **outside** identity does.

## Mental model: "Someone else checks the ID; IAM hands out a day-pass"

1. The user proves who they are to the **IdP** (corporate directory, Google,
   a mobile login, etc.) — AWS never sees their password.
2. The IdP returns a signed **token / assertion** proving the identity.
3. **AWS STS** swaps that token for **temporary credentials** tied to a specific
   IAM **role**.
4. The user acts with that role's permissions until the credentials **expire**
   (minutes to hours) — then they re-authenticate.

No long-lived access keys, no per-person IAM user to create or clean up.

```
[External IdP]  authenticates user → signed token
      │
      ▼
[AWS STS]  AssumeRoleWithSAML / AssumeRoleWithWebIdentity
      │   (token is valid + role trusts this IdP?)
      ▼
Temporary credentials for an IAM Role  → user calls AWS, time-limited
```

## The two kinds to know

### 1. SAML 2.0 federation — workforce / enterprise SSO
For employees logging in with corporate credentials.

- Register the IdP (Active Directory via ADFS, Okta, Ping, Entra ID…) as a
  **SAML identity provider** in IAM.
- Employees sign in once with their company login and assume role(s) in AWS.
- STS call under the hood: **`AssumeRoleWithSAML`**.
- The modern front door for this is **IAM Identity Center** (formerly AWS SSO):
  it manages the federation *and* maps groups → roles across **many accounts**
  in an AWS Organization, so you don't wire SAML per account by hand.

### 2. Web identity / OIDC federation — app users & workloads
For application end-users or machines authenticating through an OIDC provider.

- Providers: **Amazon Cognito**, Login with Google / Facebook / Apple, or any
  OIDC IdP. (See [[learning-plan/06-security-iam/oauth2-oidc-authentication-authorization|the OAuth2/OIDC note]]
  for how the tokens themselves work.)
- STS call under the hood: **`AssumeRoleWithWebIdentity`**.
- Mobile/web apps usually front this with a **Cognito identity pool** to hand end
  users scoped, temporary AWS access (e.g. upload only to *their* S3 prefix).
- Same mechanism powers **keyless workload auth**: **IRSA** on EKS and
  **GitHub Actions → AWS** both use OIDC federation so there are no stored keys.

## The key mechanism: trust policy + `sts:AssumeRole*`

What makes a role *federatable* is its **trust policy** (the "who may wear this
hat?" document, separate from the permissions policy). Federation = a role whose
trust policy names an **external IdP** as the trusted principal, rather than an
AWS account/user/service.

- **Permissions policy** → what the role *can do* (unchanged from any role).
- **Trust policy** → *who may assume it* → here, the SAML/OIDC provider.

That single distinction is what separates a federated identity from a plain IAM
user: the role trusts an outside authenticator instead of holding its own
permanent credentials.

## Why it matters (the SA angle)

- **No credential sprawl** — one identity source; nothing long-lived to leak.
- **Centralized lifecycle** — person leaves → disabled in the IdP → AWS access
  gone immediately (no orphaned IAM users).
- **Temporary by default** — credentials expire, shrinking the blast radius.
- **Scales across accounts** — Identity Center maps groups to roles org-wide.

## IAM user vs federated identity

| | IAM user | Federated identity |
| --- | --- | --- |
| Identity lives in | IAM | External IdP (AD, Okta, Google, Cognito…) |
| Credentials | Long-lived keys / password | **Temporary** (STS), auto-expiring |
| Scales to many people | Poorly (one per person) | Well (one IdP, many users) |
| Offboarding | Delete in IAM | Disable in the IdP |
| Granting access | Attach policy to user/group | Assume a **role** the IdP is trusted for |

## Exam-relevant notes

- "Let **corporate / Active Directory** users into AWS" → **SAML federation**,
  usually via **IAM Identity Center**. STS: `AssumeRoleWithSAML`.
- "Let **mobile/web app users** (Google/Facebook/Cognito) get AWS access" →
  **web identity / OIDC federation**. STS: `AssumeRoleWithWebIdentity`.
- "Avoid storing **long-lived credentials** / avoid an IAM user per person" →
  federation (temporary STS credentials).
- "Cross-account or org-wide SSO to many AWS accounts" → **IAM Identity Center**.
- Federation always resolves to **assuming a role** — look for the role's
  **trust policy** naming the IdP.

## Tie-in: how the video-streaming-app would use it
The [[projects/video-streaming-app/DESIGN.md|video-streaming-app]] is "no auth this
pass." If auth were added, the natural fit is **Cognito (OIDC web-identity
federation)**: users sign in through a Cognito user pool, a Cognito identity pool
federates them into a scoped IAM role, and uploads/playback get tied to the
signed-in identity — replacing the current public, unauthenticated surface.
