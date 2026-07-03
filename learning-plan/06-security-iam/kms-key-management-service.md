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

> **Terminology note:** AWS retired "Customer Master Key (CMK)" as the generic
> term — it's now just a **"KMS key."** "Customer managed key" below means
> something more specific: *who created it*, not just "the master key."

## Who owns the key: AWS owned vs AWS managed vs customer managed

Three flavors of KMS key, by who's in control:

- **AWS owned key** — used internally by an AWS service to protect your data;
  you never see it, no key policy, no control at all.
- **AWS managed key** — created automatically the first time you enable
  encryption for a service (e.g. the `aws/s3` key). Visible in your account,
  but you can't edit its key policy or delete it; AWS rotates it for you.
- **Customer managed key** — a key **you** explicitly create and fully control:
  you write the key policy, choose rotation settings, and can delete it. This is
  the one you'll actually build in the lab.

## Symmetric key

- The standard key type for most encryption use cases (S3, EBS, RDS encryption
  all default to this).
- **The same key locks and unlocks the data** — encrypt and decrypt use the
  identical key material. (KMS also supports asymmetric keys — separate
  public/private key pairs — but that's the exception, not the default.)

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

## Worked example: SSE-KMS on an S3 bucket

Server-side encryption with KMS keys (**SSE-KMS**) is envelope encryption
applied automatically by S3 — the practical version of the sequence above.

- **On upload:** S3 calls your KMS key and asks it to generate a data key. S3
  uses the plaintext copy to encrypt the object, discards it, and stores the
  encrypted copy alongside the object.
- **On read:** S3 sends the object's encrypted data key back to KMS to decrypt,
  then uses the returned plaintext data key to decrypt the object before
  returning it to the requester.

**"An additional layer of control over who can decrypt" — what that buys you.**
Compare it to the default, **SSE-S3** (Amazon-owned key, invisible to you):
there, `s3:GetObject` permission alone is enough to read the object — one gate.
With SSE-KMS there are **two gates**, and both must pass:

1. **S3 permission** — `s3:GetObject` on the bucket/object (IAM/bucket policy).
2. **KMS permission** — `kms:Decrypt` on *your specific key*, granted via its
   **key policy**.

So even if someone's IAM policy grants full S3 access, if your key's policy
doesn't also let them call `kms:Decrypt`, they can fetch the (still-encrypted)
bytes but never turn them back into plaintext. Decryption rights are enforced
separately from — and in addition to — bucket/object access rights.

Bonus: every `kms:Decrypt` call is logged in CloudTrail, giving an audit trail
of who actually *read* the data, not just who had bucket access.

## Key Policy — the "permission slip" attached directly to the key

- A resource-based policy that lives **on the key itself**, separate from any
  IAM identity policy. It's what actually decides who can use/manage the key —
  same idea as the trust-policy pattern in
  [[learning-plan/06-security-iam/iam-users-groups-roles-policies|the IAM note]].

> **Lab note:** in a restricted lab environment you often can't write a custom
> key policy. You're stuck with the **Default Policy**, which just says "the
> Root Account is trusted." That single line is what hands control back to
> regular IAM — because the root account trusts itself, it can then delegate
> key permissions via ordinary IAM roles/users/policies, instead of needing
> custom statements baked into the key policy directly.

## Key Rotation

- A security feature that automatically swaps the underlying cryptographic
  material (the "math" behind the key) on a schedule — **every 365 days** for
  automatic rotation of a customer managed key — **without changing the Key ID**.
- Nothing that references the key (aliases, IAM policies, resource configs) has
  to change, since the ID stays stable — only the material behind it rotates.

### How rotation actually works (without breaking old ciphertext)

If the material changes, how can data encrypted last year still be decrypted
this year? KMS never discards old key material — it just stops using it for
*new* encryptions.

- The **Key ID** is a permanent label — the vault's address. It never changes.
- Behind that one Key ID, KMS keeps a **history of backing keys** (the actual
  cryptographic material). On rotation, KMS generates a **new backing key** and
  marks it "current" for all future `Encrypt` calls. **Old backing keys are kept
  forever**, as long as the KMS key itself exists.
- Ciphertext produced by `Encrypt` is **self-describing** — it embeds metadata
  saying *which* backing key produced it. So `Decrypt` never needs a version
  argument: you hand back the ciphertext, and KMS reads that metadata to reach
  for the matching backing key automatically.

**Extending the vault analogy:** the vault's address (Key ID) never moves, but
every year the lock cylinder inside gets swapped for a new one. New items get
locked with this year's cylinder; old cylinders are kept in a back room rather
than thrown away, so anything locked with a previous cylinder can still be
opened — you never have to say *which* cylinder to use, since each locked item
"remembers" which one locked it.

**Why this improves security:** if one year's backing key material were ever
compromised, the blast radius is limited to whatever was encrypted during that
one year window — not everything ever encrypted under that Key ID, since each
year's data was actually locked with different underlying material, not the
same key reused forever.

## Lab: building this hands-on

1. Create a **Customer Managed Key**.
2. Enable **automatic key rotation**.
3. Use the key to **encrypt an S3 bucket**.

## Exam-relevant notes

- KMS manages **keys**, not your data — encryption/decryption of your actual
  data happens outside KMS, using the data key.
- **Envelope encryption**: plaintext data key used once then discarded;
  encrypted data key stored with the ciphertext; master key never leaves KMS.
- **Key policies** gate who can use/manage a KMS key — separate from, but
  parallel to, IAM identity policies.
- **AWS owned** (invisible, no control) vs **AWS managed** (visible, AWS
  controls it) vs **customer managed** (you control the policy, rotation,
  deletion) — know which one a scenario is describing.
- **Symmetric** keys use one key for both encrypt and decrypt — the default for
  most AWS service encryption.
- **Key rotation**: automatic rotation is yearly (365 days) and never changes
  the Key ID — nothing referencing the key needs to be updated.

## Questions / things to revisit

-
