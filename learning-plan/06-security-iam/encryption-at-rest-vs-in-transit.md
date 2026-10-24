---
title: Encryption at Rest vs In Transit (and In Use)
type: note
domain: security-iam
date: 2026-10-23
source: "Own notes + Kiro explanation; expands the KMS note's at-rest/in-transit section"
tags:
  - aws
  - security
  - encryption
  - tls
  - kms
  - at-rest
  - in-transit
  - data-protection
---

# Encryption at Rest vs In Transit (and In Use)

> Part of [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]].
> Related: [[learning-plan/06-security-iam/kms-key-management-service|KMS — Key Management Service]]
> · [[learning-plan/06-security-iam/shared-responsibility-model|Shared Responsibility Model]]
> · [[learning-plan/06-security-iam/secrets-manager|Secrets Manager]]

Data exists in three **states**, and you protect each one differently. Two states
dominate exam questions and real designs — **at rest** and **in transit** — with
**in use** as the newer third.

> One-liner: **at rest = bytes sitting still on disk; in transit = bytes moving
> over the network.** Different threats, different mechanisms, and a secure system
> needs **both** — one says nothing about the other.

## The two main states

### Data at rest — stored bytes
Data persisted somewhere: an S3 object, an EBS volume, an RDS/DynamoDB table, a
snapshot, a backup, a log file.

- **Threat:** someone reaching the stored bytes directly — a stolen or improperly
  decommissioned disk, an unauthorized snapshot, raw access to the storage medium.
- **Mechanism:** **encryption at rest** — the data is encrypted *before* it's
  written to disk and decrypted *after* it's read back, so what physically sits on
  the medium is ciphertext. On AWS this is almost always backed by
  [[learning-plan/06-security-iam/kms-key-management-service|KMS]] keys.

### Data in transit — moving bytes
Data travelling over a network: client → server, browser → S3, or service →
service inside AWS.

- **Threat:** interception or tampering **on the wire** — eavesdropping,
  man-in-the-middle, replay.
- **Mechanism:** **encryption in transit** — almost always **TLS/HTTPS** (an
  entirely separate mechanism from at-rest). Certificates on AWS typically come
  from **ACM (AWS Certificate Manager)**.

### (Third state) Data in use — bytes in memory
Data loaded into RAM/CPU while being processed. Protected by **confidential
computing** — e.g. **AWS Nitro Enclaves** — which isolates in-memory data even
from the host. Niche; know it exists.

## They defend different threats (why you need both)

Encrypting at rest says **nothing** about how data travels; TLS says **nothing**
about how it's stored. They are independent walls against independent attacks.

| | At rest | In transit |
| --- | --- | --- |
| Where the data is | Stored on disk / bucket / DB / snapshot | Moving over a network |
| Threat defended | Stolen disk, rogue snapshot, raw storage access | Eavesdropping, MITM on the wire |
| Mechanism | Encryption at rest (KMS-backed) | TLS / HTTPS |
| Who holds keys | KMS (SSE-S3, SSE-KMS, EBS/RDS encryption) | ACM certs / the TLS endpoint |
| Fails to protect | Traffic on the wire | Bytes once written to disk |

> A stolen disk is useless against at-rest encryption but learns everything if you
> only had TLS. A wiretap is useless against TLS but learns everything if you only
> encrypted at rest. Hence: **both.**

## AWS service examples

**At rest**
- **S3** — always encrypts by default with **SSE-S3** (Amazon-owned key). Enabling
  **SSE-KMS** doesn't turn encryption *on*; it swaps the default key for your KMS
  key, which adds a separate `kms:Decrypt` permission gate (see the
  [[learning-plan/06-security-iam/kms-key-management-service|KMS note]]).
- **EBS** volumes and **snapshots** — KMS-backed volume encryption.
- **RDS / DynamoDB** — encryption at rest via KMS (toggle/managed key).
- **Secrets Manager** — secrets encrypted at rest with KMS
  ([[learning-plan/06-security-iam/secrets-manager|note]]).

**In transit**
- **HTTPS/TLS** to S3, API Gateway, ALB, CloudFront — ACM issues/renews the certs.
- **Service-to-service** calls inside AWS run over TLS.
- **VPN / TLS tunnels** for hybrid connectivity.

## In the shared-responsibility model
Both at-rest and in-transit encryption are **"security _in_ the cloud"** — the
**customer's** responsibility to configure (AWS gives you KMS, ACM, TLS endpoints;
you choose to enable and enforce them). See
[[learning-plan/06-security-iam/shared-responsibility-model|the shared
responsibility note]], which lists "server-side encryption" and "networking
traffic protection (encryption in transit)" on the customer side.

## Tie-in: the video-streaming-app
A single project touches both:
- **At rest** — the private Output bucket (S3, encrypted by default); the CloudFront
  signing key held in **Secrets Manager** (KMS-encrypted at rest).
- **In transit** — playback and API are **HTTPS-only**; the design deliberately
  keeps the CloudFront→origin hop on TLS (the API Gateway `execute-api` cert) so the
  signed-cookie `Set-Cookie` is **never plaintext on the wire** — a textbook
  in-transit decision. See [[projects/video-streaming-app/walkthrough.md|the walkthrough]].

## Exam-relevant notes

- "Protect data **on disk / in the bucket / in snapshots**" → **encryption at
  rest** (KMS: SSE-KMS, EBS/RDS encryption).
- "Protect data **moving between client and service / over the network**" →
  **encryption in transit** → **TLS/HTTPS** (certs via **ACM**).
- "Enforce HTTPS" → S3 bucket policy `aws:SecureTransport`, or a CloudFront/ALB
  viewer policy redirecting to HTTPS.
- S3 is encrypted **at rest by default** (SSE-S3) — the question is usually *which
  key*, not *whether* it's encrypted.
- At rest and in transit are **independent** — a correct answer almost always needs
  **both**, never one as a substitute for the other.
