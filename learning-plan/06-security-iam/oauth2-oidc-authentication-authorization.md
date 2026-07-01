---
title: OAuth 2.0 & OpenID Connect — Authentication vs Authorization
type: note
domain: security-iam
date: 2026-06-17
source: "YouTube: OAuth 2.0 & OpenID Connect explainer (https://www.youtube.com/watch?v=bhvJ1z-ye6E) + own notes"
tags:
  - aws
  - security
  - oauth2
  - oidc
  - jwt
  - authentication
  - authorization
  - cognito
---

# OAuth 2.0 & OpenID Connect — Authentication vs Authorization

> Part of [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]].
> Related: [[learning-plan/06-security-iam/iam-users-groups-roles-policies|IAM Users, Groups, Roles & Policies]]
> Source video: [OAuth 2.0 & OpenID Connect explainer](https://www.youtube.com/watch?v=bhvJ1z-ye6E)

## The core distinction (get this first)

| Term | Question it answers | One word |
| --- | --- | --- |
| **Authentication (AuthN)** | *Who are you?* — validating **identity** | login |
| **Authorization (AuthZ)** | *What are you allowed to do?* — validating/granting **access** | permission |

This is the same WHO-vs-WHAT split as
[[learning-plan/06-security-iam/iam-users-groups-roles-policies|IAM identities vs policies]].
Key framing from the video: **OAuth 2.0 is fundamentally about authorization** (granting
access), and the whole protocol is about **establishing trust** between parties so a user
never hands their password to a third-party app.

> **Access token** = a portable representation of *authorization* (not identity).

## The four key roles (vocabulary)

OAuth 2.0 has four players — worth naming because the flows reference them:

- **Resource owner** — the **user** who owns the data.
- **Client** — the **application** that wants access on the user's behalf.
- **Authorization server** — issues tokens after verifying identity + consent.
- **Resource server** — the API holding the protected data; it accepts the token.

## Why not just hand the app the token? (the two benefits)

The video calls out two benefits — note these specifically describe the **Authorization
Code** flow, not OAuth 2.0 in general:

1. **User (resource owner) credentials are never shared with the application** — the user
   logs in directly at the authorization server; the app never sees the password.
2. **Tokens are never exposed to the browser** — the access token is exchanged
   server-to-server, not handed through the browser.

## Authorization Code grant (the most common flow)

The "authorization code" is a short-lived intermediate step. Why the extra hop instead of
returning the access token directly to the browser?

> Because returning the token through the browser is **unsafe** — it could land in browser
> history, logs, or cache. So the browser only ever carries a throwaway **code**, which
> the app's backend then swaps for the real access token over a secure server-to-server
> call.

```
1. User → app: "log me in"
2. App → browser → Authorization Server (user logs in there directly)
3. Auth Server → browser → app: short-lived AUTHORIZATION CODE (safe to pass via browser)
4. App backend → Auth Server: code + client secret  →  ACCESS TOKEN  (server-to-server)
5. App → Resource Server: request + access token  →  data
```

### How does the auth server trust the app? (pre-registration)

Before any of this runs, there's a **one-time registration**: you register your
application with the authorization server and receive a **client secret**. Only a
registered app holding that secret can exchange a code for a token. This pre-step is what
**establishes trust** between the app server and the authorization server — it happens
*before* the flow above ever starts.

## Client Credentials grant

- **Use case:** **no human/user involved** — one application talking to another
  (machine-to-machine, service-to-service).
- The client authenticates as *itself* (using its credentials) and gets a token directly.
  No resource owner, no browser redirect.

## OpenID Connect (OIDC) — adding *identity* on top

OAuth 2.0 alone only does authorization. **OIDC is a thin identity layer on top of OAuth
2.0** that lets a client **verify who the user is** and get basic profile info, in a
standard REST-like way.

- The key addition is the **ID token** — a security token containing **claims** about the
  user's authentication (and optionally profile data).
- The ID token is a **JWT (JSON Web Token)**.

> **Mental model:** OAuth 2.0 = authorization (access). OIDC = OAuth 2.0 **+ authentication
> (identity)**. Access token = what you can *do*; ID token = who you *are*.

## Why a JWT can be trusted

- JWTs are **cryptographically / digitally signed** by the authorization server.
- Only the authorization server holds the **private key** used to sign them, so the
  signature can't be forged. Anyone can verify it with the public key.
- Tokens are **immutable** — you can't edit one; you can only issue a new one. (Tamper with
  it and the signature no longer validates.)
- Inspect/decode them at [jwt.io](https://www.jwt.io/).

> Caveat (my addition): a JWT is signed, **not encrypted** by default — its payload is just
> base64, readable by anyone. So never put secrets in a JWT, and always verify the
> signature *and* expiry server-side.

## Bearer token

- **Bearer tokens** are the predominant access-token type with OAuth 2.0.
- "Bearer" = *whoever holds it can use it* (like cash). The resource server doesn't check
  who you are beyond possession of the token.
- Implication: bearer tokens **must** travel over HTTPS and be short-lived — if stolen,
  they're directly usable. This is why short expiry + **refresh tokens** matter.

## Why two tokens? (access + refresh)

A single token can't satisfy two goals that pull in opposite directions:

- **Security** → if a token leaks, the damage window should be tiny → **short-lived**.
- **Usability** → don't make the user log in every few minutes → **long-lived**.

One long-lived token = great UX, but a leak grants weeks of access and stateless JWTs are
hard to revoke. One short-lived token = safe, but the user re-logs in constantly. Neither
works. So OAuth splits the *jobs*:

| | Access token | Refresh token |
| --- | --- | --- |
| Purpose | Prove authorization on each API call | Get a *new* access token without re-login |
| Lifetime | **Short** (minutes–~1h) | **Long** (days–months) |
| Sent to | The **resource server**, every request | Only the **authorization server**, occasionally |
| Exposure | High (travels constantly) | Low (sits in secure storage) |
| If it leaks | Small blast radius (expires fast) | Bigger, but **revocable** + rarely transmitted |

**The trick = exposure vs. blast radius.** The access token is exposed *constantly*, so
make it short-lived (a leak is worthless minutes later). The refresh token is exposed
*rarely* (only to the auth server, only when refreshing), so it's safe to make it
long-lived.

```
Login once → access token (5 min) + refresh token (30 days)
Every API call:  app → resource server, with access token
After ~5 min:    access token expires
Silent refresh:  app → AUTH server, with refresh token → new access token (no re-login)
```

**Revocation is the payoff:** refreshing requires a round-trip to the auth server, which
is a natural control point. Refresh tokens are **stateful** and can be revoked (logout,
password change, stolen device); access dies within one short access-token lifetime. So
access tokens stay **fast + stateless** (no DB lookup per call) while the refresh step
keeps you **in control**.

> Recurring security pattern: a frequently-used, widely-exposed credential should be
> **short-lived**; a rarely-used, tightly-held one can be long-lived. Same idea as
> [[learning-plan/06-security-iam/iam-users-groups-roles-policies|IAM roles handing out temporary credentials]]
> and [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|EC2 Instance Connect's 60-second SSH keys]].

## Single-token credentials (e.g. GitHub PAT) vs OAuth delegation

Some platforms offer a **single long-lived token** with no refresh token — e.g. a GitHub
**Personal Access Token (PAT)**. A PAT is closer to a **self-issued API key / an AWS
long-term access key** than to an OAuth token.

**Important correction to a common misconception:** the distinction is **not** "only OAuth
can delegate to a third party." You *can* paste a PAT into a third-party app (an AI
assistant, say) and it will act on your behalf. The real difference is the **security
properties of the delegation**, not whether it's technically possible.

> A PAT *can* be used for third-party delegation — it's just the **anti-pattern** OAuth
> exists to replace. OAuth doesn't make delegation *possible*; it makes it *safe*.

Same goal (let an AI assistant read your repos), two mechanisms:

| Property | PAT (single token) | OAuth (access + refresh) |
| --- | --- | --- |
| Credential handed to the app? | **Yes** — you give it the token | No — user logs in at the auth server |
| Per-app distinct credential? | No — one token, reused anywhere | Yes — one grant per app |
| Revoke one app without affecting others? | No | Yes |
| Scopes chosen by | You, manually, once | App requests + user consents per grant |
| Audit attribution | Looks like *you* | Attributable to the app |
| Lifetime | Long-lived, static | Short access token + refresh |

**Note that no row is "can a third party use it"** — both can. OAuth makes the delegation
**scoped, per-app, individually revocable, credential-free, and auditable**; a PAT is a raw
"here's a copy of my keys" handoff.

**Why single-token is still acceptable for PATs:** they're used by *scripts/CI* (no human
to re-login → refresh solves a non-problem) and stored once in a secret manager (low,
infrequent exposure). GitHub still applies the same instincts via **expiration dates**,
**fine-grained scopes** (blast-radius control = OAuth scopes), and **easy revocation** in
settings. For apps acting on your behalf, GitHub steers you to **OAuth / GitHub Apps**
(short-lived installation tokens) rather than PATs — i.e. reinventing the access-token
pattern.

> Takeaway: prefer **short-lived, auto-rotated credentials** (OAuth tokens, IAM roles) over
> **long-lived static ones** (PATs, access keys) — the static credential is the thing that
> leaks and lingers.

## How this connects to AWS

- **Amazon Cognito** is AWS's managed identity service and speaks **OAuth 2.0 + OIDC**. A
  Cognito **user pool** acts as the authorization server / IdP (issues JWT ID + access
  tokens); it also supports federation with Google, Apple, SAML, etc.
- **"Sign in with Google/Facebook"** is exactly this flow — the app never sees your
  password, only tokens.
- **IAM roles + web identity federation:** an OIDC ID token can be exchanged (via
  `AssumeRoleWithWebIdentity`) for **temporary AWS credentials** — tying straight back to
  [[learning-plan/06-security-iam/iam-users-groups-roles-policies|roles = temporary credentials]].
- **API Gateway** can validate JWTs from Cognito/an OIDC provider as a native authorizer.

## Quick recall

| Question | Answer |
| --- | --- |
| AuthN vs AuthZ? | Identity (who) vs access (what) |
| OAuth 2.0 is mainly about…? | **Authorization** |
| What adds identity on top of OAuth 2.0? | **OpenID Connect** (via the **ID token**) |
| What format is the ID token? | **JWT** |
| Why trust a JWT? | Signed with the auth server's **private key**; immutable |
| Flow when no human is involved? | **Client Credentials** |
| Why the intermediate auth *code*? | Avoid exposing the token via the browser |
| Why two tokens (access + refresh)? | Short access token = safe if leaked; refresh = good UX + revocable |
| GitHub PAT vs OAuth — the real difference? | Not *who can use it* — it's safety: scoped, per-app, revocable, credential-free |
| How is app↔auth-server trust set up? | **Pre-registration** → client secret |
| AWS service that does this? | **Amazon Cognito** (+ API Gateway, web identity federation) |

## My feedback on your notes

- Strong grasp of the *why* — you nailed the two best insights: the **authorization code
  exists to keep tokens out of the browser**, and **pre-registration is what establishes
  trust**. Those are the points most people miss.
- One precision fix: the "two benefits" you listed first under *OAuth2* are really benefits
  of the **Authorization Code flow** specifically (I moved them there).
- Worth internalizing the **access token vs ID token** split — it's the cleanest way to
  remember the OAuth-vs-OIDC difference, and it mirrors the AuthZ-vs-AuthN distinction.
- Two things I'd add for completeness: **refresh tokens** (how you get a new access token
  without re-login) and **scopes** (how an access token is limited to specific
  permissions) — both come up constantly in real OAuth work.
