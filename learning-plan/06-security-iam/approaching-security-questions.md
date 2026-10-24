---
title: Approaching Security Questions — a mental model (+ KMS/CloudHSM, keys, rotation)
type: note
domain: security-iam
date: 2026-10-23
source: "Own notes + Kiro explanation"
tags:
  - aws
  - security
  - mental-model
  - kms
  - cloudhsm
  - encryption
  - keys
  - rotation
  - exam
---

# Approaching Security Questions — a mental model

> Part of [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]].
> Related: [[learning-plan/06-security-iam/kms-key-management-service|KMS]]
> · [[learning-plan/06-security-iam/encryption-at-rest-vs-in-transit|Encryption at Rest vs In Transit]]
> · [[learning-plan/06-security-iam/shared-responsibility-model|Shared Responsibility Model]]
> · [[learning-plan/06-security-iam/iam-users-groups-roles-policies|IAM Users, Groups, Roles & Policies]]

Most AWS security questions resolve if you locate them on **three axes**, then
apply a short **principles checklist**. The fact that a cluster of questions
(symmetric vs asymmetric, KMS vs CloudHSM, cross-region keys, key types,
rotation) all hang together is itself the hint — they're all points on the same
map.

## The three axes

**Axis 1 — What _state_ is the data in?** → picks the mechanism family.
- At rest → encryption at rest (KMS-backed). In transit → TLS/HTTPS (ACM). In use
  → enclaves (Nitro). See [[learning-plan/06-security-iam/encryption-at-rest-vs-in-transit|the at-rest/in-transit note]].

**Axis 2 — What _security property_ is being asked for?** → name it explicitly.
- **Confidentiality** (encryption), **Integrity** (hash/MAC/sign), **Authentication**
  (who are you), **Authorization** (what may you do → IAM), **Auditability /
  non-repudiation** (CloudTrail, signatures), **Availability** (DDoS, multi-AZ).
- Trap: many "security" questions are really **authorization** questions in an
  encryption costume.

**Axis 3 — Who holds the keys / who do you trust?** → the control axis, the heart
of KMS vs CloudHSM.
- AWS owned (invisible) → AWS managed (AWS operates, you see it) → customer managed
  (you control policy/rotation) → sole-custody single-tenant (CloudHSM, AWS can't
  touch it). **More control = more operational burden.**

## The principles checklist (answers most "why/which")

- **Least privilege**
- **Defense in depth** — layers, never one *instead of* another
- **Two-sided gates / separation of duties** — e.g. the KMS `kms:Decrypt` gate
  *plus* IAM; `iam:PassRole` as the operator gate for service roles
- **Shared responsibility** — security *OF* vs *IN* the cloud
- **Managed ↔ control tradeoff** — convenience/integration vs sole control/compliance
- **Temporary over long-lived** — STS, rotation
- **Blast radius / scope** — regional boundaries, key scoping

**For "Service A vs Service B" questions:** compare on the *same fixed dimensions*
(tenancy, who controls keys, compliance level, integration, ops overhead, cost),
then ask **"when am I forced into the harder one?"** and **"can they combine?"**

---

# Worked examples (the cluster of questions)

## Symmetric vs asymmetric (Axis 2)

| | Symmetric | Asymmetric |
|---|---|---|
| Keys | One shared key (AES-256) | Public + private pair (RSA, ECC) |
| Speed | Fast → **bulk data** | Slow → small payloads |
| Use | Encrypt/decrypt data at rest | Encrypt when the other side **can't share a secret**, or **sign/verify** |
| On AWS | KMS default | KMS asymmetric keys; **public key downloadable** |

Hook: **symmetric = secrecy at scale; asymmetric = hand something to an untrusted
party (a public key) or prove origin (signing).** The video-streaming-app uses
asymmetric for CloudFront signed cookies — sign with the private key, CloudFront
verifies with the public key.

## KMS vs CloudHSM (Axis 3 — the control axis)

| Dimension | KMS | CloudHSM |
|---|---|---|
| Tenancy | **Multi-tenant**, managed | **Single-tenant**, dedicated to you |
| Who controls keys | AWS operates; you manage policy | **You** — AWS has no access |
| Compliance | FIPS 140-2 Level 3 HSMs | FIPS 140-2 Level 3, **sole custody** |
| Integration | Native with ~every AWS service | You wire it up (PKCS#11 / JCE / CNG) |
| Ops / cost | Low, serverless | High, you run the cluster |

- **Why KMS instead of CloudHSM (default):** managed, integrated, cheaper, no sole
  custody needed. Pick KMS unless something *forces* you off it.
- **What forces CloudHSM:** regulatory need for **single-tenant / sole control**, or
  crypto ops KMS doesn't offer (SSL offload, Oracle TDE, your own PKCS#11 app).
- **Using them together — the key fact:** a **KMS custom key store** backed by a
  CloudHSM cluster. You keep KMS's API + service integration, but the key material
  lives in *your* dedicated HSM. Integration *and* sole custody.

## Managing keys across regions (Axis 3 + blast-radius)

- **KMS keys are regional** — a key in one region can't be used in another by
  default (a deliberate scope boundary).
- **Multi-Region Keys (MRK):** a **primary** + **replicas** in other regions sharing
  the same key material and key ID. Encrypt in one region, **decrypt in another** —
  the answer for DR, cross-region backups/snapshots, global DynamoDB. Material stays
  in sync; policies/grants are managed **per region**.
- Alternatives: re-encrypt per region, or move only data keys (envelope encryption).

Hook: "**decrypt the same ciphertext in another region**" → **Multi-Region Keys**.

## Key types and capabilities (Axis 3)

| Type | Who controls | Policy / rotation control | Visibility |
|---|---|---|---|
| **AWS owned** | AWS, cross-account | None | Invisible (e.g. SSE-S3 default) |
| **AWS managed** (`aws/s3`…) | AWS, in your account | None; auto-rotates | Visible, can't edit/delete |
| **Customer managed (CMK)** | **You** | Full — policy, rotation, enable/disable/delete | Full |

By crypto function:
- **Symmetric CMK** — encrypt/decrypt + generate data keys; material never leaves KMS.
- **Asymmetric CMK** — RSA/ECC; **encrypt/decrypt _or_ sign/verify**; public key
  downloadable; **cannot auto-rotate**.
- **HMAC keys** — generate/verify MACs (integrity).
- **Data keys** — generated for envelope encryption, used *outside* KMS, not stored by KMS.

## Rotation cadence (the detail questions love)

| Key | Automatic rotation? | Cadence |
|---|---|---|
| **AWS managed** | Yes, automatic | ~**every 1 year** (not configurable) |
| **Customer managed, symmetric** | Optional | Default **365 days**, configurable (min ~90 days); old material kept for decrypt |
| **Asymmetric CMK** | **No** | **Manual only** (public key is distributed externally) |
| **Imported material (BYOK)** | No | **Manual only** |
| **CloudHSM** | No KMS-style auto | **You manage it entirely** |

Hook: "**can't auto-rotate**" → asymmetric or imported-material keys; "**rotates
automatically, I don't configure it**" → AWS managed.

---

## The approach in one sentence

Place the question on the three axes — **state → property → who holds the keys** —
then let the principles (especially **managed-vs-control** and **defense-in-depth**)
and keyword-matching do the rest.
