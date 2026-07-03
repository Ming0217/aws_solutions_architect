---
title: KMS (Key Management Service)
type: note
domain: security-iam
date: 2026-07-03
source: Skill Builder course + own notes
tags:
  - aws
  - security
  - kms
  - encryption
---

# KMS (Key Management Service)

> Part of [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]].
> Related: [[learning-plan/06-security-iam/iam-users-groups-roles-policies|IAM Users, Groups, Roles & Policies]]

## The simple version

Think of KMS as a **virtual vault**. It manages the **keys** used to lock
(encrypt) and unlock (decrypt) your data — it does not store the data itself.

One nuance worth holding on to: KMS doesn't just hand you the master key to use
elsewhere. The encrypt/decrypt operation for the master key happens **inside**
KMS — the master key's raw bytes never leave the vault.

## Customer Master Key (CMK) / KMS key

- The "master key" that lives in the vault. You never see its raw bytes; you can
  only ask KMS to *use* it (encrypt, decrypt, generate a data key).
- Has its own **key policy** — a resource-based policy on the key itself,
  controlling who can use/manage it. Same shape as the trust-policy idea from
  [[learning-plan/06-security-iam/iam-users-groups-roles-policies|the IAM note]]
  — permissions live on the resource, not just the identity.

## Envelope encryption — how KMS actually encrypts your data

The vault doesn't touch your (potentially huge) data directly — that would be
slow and would mean sending everything through KMS. Instead:

1. You ask KMS to generate a **data key**.
2. KMS returns **two copies**: a **plaintext** copy (used once, locally, to
   encrypt your actual data) and a copy **encrypted by the master key**.
3. You encrypt your data with the plaintext data key, then **discard** the
   plaintext copy — you only store the encrypted data key alongside your
   encrypted data.
4. To decrypt later, you send the encrypted data key back to KMS; KMS unlocks it
   with the master key (which never left the vault) and hands you back the
   plaintext data key, which you use to decrypt your data.

```
KMS (vault)
  │
  ├─ generates data key ─► plaintext copy   (encrypt data locally, then discard)
  │                        encrypted copy   (store next to the encrypted data)
  │
  └─ later: encrypted copy sent back ─► KMS decrypts with master key ─► plaintext data key
```

**Why bother with two keys instead of one?** Performance and blast radius — the
master key never leaves the vault and never touches your bulk data; KMS only
ever handles the small data key.

## Exam-relevant notes

- KMS manages **keys**, not your data — encryption/decryption of your actual
  data happens outside KMS, using the data key.
- **Envelope encryption**: plaintext data key used once then discarded;
  encrypted data key stored with the ciphertext; master key never leaves KMS.
- **Key policies** gate who can use/manage a KMS key — separate from, but
  parallel to, IAM identity policies.

## Questions / things to revisit

-
