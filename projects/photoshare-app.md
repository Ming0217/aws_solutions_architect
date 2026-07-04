---
title: "Project: PhotoShare — Instagram-style photo sharing app"
type: project
domain: architecting
date-started: 2026-07-04
services:
  - vpc
  - alb
  - ec2
  - rds
  - s3
  - lambda
  - iam
  - kms
  - secrets-manager
  - cloudwatch
status: in-progress
tags:
  - aws
  - project
---

# Project: PhotoShare — Instagram-style photo sharing app

> Related: [[projects/projects|projects index]]
> Design source: KodeKloud project template.
> Part of the [H2 2026 AWS OKR](../README.md) — counts toward both KR1 (documented
> architecture) and KR2 (working project).

## Use case / goal

A resilient web application (inspired by Instagram) that separates public-facing
components from sensitive data using network isolation, and automates background
work so it scales without manual intervention.

## Architecture

```
                         ┌── IAM
        user             │
         │               │
         ▼               │
   ┌─────────────────────┼───────────────────────────┐
   │ VPC                 │                           │
   │  ┌─ Public subnet ──┼───────────┐                │
   │  │   ALB ───────────┴──► EC2 (Docker) ──► CloudWatch
   │  │                          │                    │
   │  └──────────────────────────┼────────────────────┘
   │                              ▼
   │  ┌─ Private subnet ──────────────────┐
   │  │   RDS (MySQL, no public access)   │
   │  └────────────────────────────────────┘
   │
   │  S3 (images, block all public access) ──► Lambda (on upload) ──► CloudWatch
   │  KMS ──encrypts──► Secrets Manager (DB credentials)
   └────────────────────────────────────────────────────────────────┘
```

### VPC — "Front Door" vs "Vault"

Every app needs a secure home. The **VPC is the property line** for PhotoShare.
Inside it, two distinct zones:

- **Public subnet — the "Front Door."** The ALB and web server (EC2) live here.
- **Private subnet — the "Vault."** The database is hidden here, strictly
  isolated from the internet.

This separation means users can reach the app interface, but nothing can
directly touch the data store — see
[[learning-plan/04-networking/vpc-subnets|the VPC subnets note]] for the
general mechanics (route tables, IGW, subnet associations) behind this split.

> **Nuance on the EC2 placement:** the usual justification for putting the web
> server in the public subnet is "so we can SSH into it for configuration." But
> per [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|the Session Manager
> note]], SSM Session Manager can administer an instance with **zero inbound
> ports**, even one with no public IP at all. So the public subnet is really
> only required for the **ALB's** internet-facing side — worth deciding
> deliberately whether the EC2 web server should sit in the public subnet (as
> designed) or move to the private subnet behind the ALB, using Session Manager
> for admin access instead of SSH. Currently following the KodeKloud design
> (EC2 in public subnet); revisit this as a hardening step.

### Subnet CIDR plan

VPC: `10.0.0.0/16`. Subnets are `/24`, so per the "frozen bits" mental model
in [[learning-plan/04-networking/ip-addresses-and-cidr|the CIDR note]]: the
gap between `/16` and `/24` is exactly one octet (8 bits), which means **the
third octet is the only digit free to choose** per subnet — everything else is
fixed by the VPC's `/16` and the subnet's own `/24` size. AWS only requires
each subnet to fit inside `10.0.0.0/16` and not overlap another subnet;
which third-octet value maps to which subnet is pure convention, not an AWS
rule.

Full layout (all 4 confirmed from the console — third octet indexes in
creation order: main public, main private, placeholder public, placeholder
private):

| CIDR | Zone | AZ | Role |
| --- | --- | --- | --- |
| `10.0.1.0/24` | Public Subnet 1 | us-east-1a | Main — ALB + EC2 web server |
| `10.0.2.0/24` | Private Subnet 1 | us-east-1a | Main — RDS |
| `10.0.3.0/24` | Public Subnet 2 | us-east-1b | Placeholder — required for ALB creation |
| `10.0.4.0/24` | Private Subnet 2 | us-east-1b | Placeholder — required for DB Subnet Group |

**Why the 2nd-AZ subnets exist already, before any resilience feature is
turned on** — this isn't scaling yet, it's an AWS platform requirement:

- **ALB requires ≥2 Availability Zones at creation.** AWS won't let you create
  an ALB with only one subnet/AZ — its own nodes are provisioned cross-AZ for
  the load balancer's own availability, regardless of how many/few backend
  targets exist.
- **RDS requires a DB Subnet Group spanning ≥2 AZs**, even for a single-AZ
  database deployment. This reserves room for a standby (if Multi-AZ is
  enabled later) or for maintenance failover, without needing to re-architect
  the network afterward.

So `Public Subnet 2` / `Private Subnet 2` hold **no live resources yet** — no
second EC2, no DB standby. They exist purely to satisfy ALB/DB-Subnet-Group
validation. They become "real" exactly when an ASG places a second EC2 in
`10.0.3.0/24`, or RDS Multi-AZ places a standby in `10.0.4.0/24` — see the
Reliability tradeoff below, which is about turning those features *on*, not
about creating new subnets (the network is already in place for it).

### IAM Roles

Two workers need AWS access: the **Web Server (EC2)** and the **Image
Processing Function (Lambda)**. Instead of hardcoding API keys, each gets its
own IAM role — temporary ID badges granting only the permissions each worker
needs. See [[learning-plan/06-security-iam/iam-users-groups-roles-policies|the
IAM note]] for the general "how a role gets associated" mechanics.

| Role | Trusted service (trust policy) | How it's attached | Attached policies |
| --- | --- | --- | --- |
| `iam_role_ec2` | `ec2.amazonaws.com` | Wrapped in an **instance profile**, attached to the EC2 instance | `AmazonS3FullAccess`, `AWSSecretsManagerClientReadOnlyAccess` |
| `iam_role_lambda` | `lambda.amazonaws.com` | Set directly as the function's **execution role** — no instance-profile-equivalent needed | TBD |

**Why EC2 needs those two specific policies — two unrelated jobs:**

- **`AmazonS3FullAccess`** — the web server uploads/serves photos to the S3
  bucket. Nothing to do with the database.
- **`AWSSecretsManagerClientReadOnlyAccess`** — lets EC2 call
  `secretsmanager:GetSecretValue` to fetch the DB password at runtime instead
  of hardcoding it. See [[learning-plan/06-security-iam/secrets-manager|the
  Secrets Manager note]] for the full IAM→Secrets-Manager→KMS chain.

> **Important nuance:** this Secrets Manager permission does **not** grant
> access to RDS itself — it only grants access to *read the secret*. Actual
> database access is a separate layer: **network** access is controlled by
> the private subnet + security group (only the EC2 security group allowed in
> on the DB port), and **authentication** to MySQL uses the master
> username/password itself (a database-native credential, per
> [[learning-plan/05-databases/rds-core-concepts|the RDS note]]) — not IAM at
> all. Without the Secrets Manager permission, EC2 could still be
> network-reachable to RDS but would never learn the password to log in — so
> the app effectively couldn't connect.

> **Naming constraint:** role names must start with `iam` and contain `role`
> (satisfied by both names above). This is a **lab guardrail, not an AWS
> requirement** — restricted labs commonly enforce this via an IAM policy
> condition on the student's own permissions (e.g. `iam:CreateRole` allowed
> only when the role name matches a `StringLike` pattern like `iam_role_*`).
> Same mechanism as the KMS lab's "Default Policy trusts the Root Account"
> restriction: the lab scopes down what *you* can create, not what AWS itself
> demands.

### KMS

Using the **AWS-managed key**, alias `alias/aws/secretsmanager`
(Key ARN: `arn:aws:kms:us-east-1:058264141167:key/54168bcb-db5a-4c36-b718-6eb3bbcfc03c`),
to encrypt the database credentials stored
in Secrets Manager. Data appears as scrambled gibberish even if the encrypted
value is accessed directly, without the key. See
[[learning-plan/06-security-iam/kms-key-management-service|the KMS note]].

> **Why `iam_role_ec2` doesn't need an explicit `kms:Decrypt` permission:**
> reading a KMS-encrypted secret always requires two authorization checks —
> `secretsmanager:GetSecretValue` **and** `kms:Decrypt` — but *where* the
> second check lives depends on who owns the key:
>
> - **AWS-managed key (this project's setup):** the key's own key policy
>   already grants decrypt access to **any principal in the account**, as long
>   as they call through the Secrets Manager service (a `kms:ViaService`
>   condition on the key's resource policy). So `iam_role_ec2` only needs
>   `AmazonS3FullAccess` + `AWSSecretsManagerClientReadOnlyAccess` — no
>   separate KMS permission — and it still works. This is expected, not a gap.
> - **Customer managed key (the one built in the earlier KMS lab):** would
>   require explicitly granting `kms:Decrypt` to `iam_role_ec2`, either in the
>   role's IAM policy or by naming the role directly in the key's policy.
>
> Both checks always happen — only the *location* of the second one changes
> depending on key ownership.

### RDS

Every photo needs data attached to it — who uploaded it, when, and its title.
Amazon RDS runs a managed **MySQL** database for this, placed in the
**Private Subnet** so it's invisible to the public internet, and only the
Web Server (EC2) can talk to it. See
[[learning-plan/05-databases/rds-core-concepts|the RDS note]] for the general
DB-instance/engine/Multi-AZ mechanics.

**How "only EC2 can talk to it" is actually enforced — three independent
layers, each blocking a different attack path:**

1. **No route to an Internet Gateway** (private subnet) — nothing on the
   internet can even attempt a connection.
2. **RDS "Public Access" disabled** — a second, RDS-specific switch, separate
   from subnet routing.
3. **Security group referencing the EC2 security group as the source** (not a
   CIDR range) — even *inside* the VPC, only instances wearing the web
   server's security group can reach the DB port. This is stronger than "same
   subnet," since subnet membership alone doesn't imply permission — another
   instance in the same private subnet with a different security group would
   still be blocked.

Only after all three checks pass does a connection even get the chance to
authenticate with the MySQL master username/password (a database-native
credential, separate from all of the above).

### Lambda — networking decision (no VPC)

Triggers automatically on S3 upload to process image metadata in the
background. **Advanced Settings → Enable VPC: left unchecked.**

- **Why this works:** Lambda's default (no-VPC) networking already has **full
  internet access built in**, managed by AWS — it's not attached to
  PhotoShare's VPC at all, so it's never subject to that VPC's routing rules
  (no IGW, no NAT, no private-subnet restrictions apply to it). If it *were*
  placed inside the private subnet instead, it would be bound by that
  subnet's route table — and since there's no NAT Gateway there, it would
  lose all internet access entirely.
- **Why it needs to reach S3:** to read the uploaded image / write processed
  metadata back.
- **Why it needs to reach the ALB** (`photoshare-alb-1992972335.us-east-1.elb.amazonaws.com`):
  the ALB has private IPs inside the VPC too, but since Lambda isn't attached
  to the VPC, its only path to it is via its public, internet-facing DNS
  name. This strongly implies the design is: **Lambda processes metadata, then
  calls back into the web app's own API (through the ALB)**, letting the
  *web app* write the metadata into RDS — rather than giving Lambda direct
  database access. That keeps `iam_role_lambda`'s permissions minimal (S3 +
  outbound HTTP only, no Secrets Manager/RDS access needed) — least privilege
  by architecture, not just by policy.

> **Contrast — the trade-off this avoids:** if Lambda needed to write
> directly to RDS instead, it would have to be attached to the VPC to reach
> the private subnet — and then it would need its own internet story: either
> a **NAT Gateway** (general internet-bound traffic, e.g. reaching S3's public
> endpoint) or an **S3 VPC Endpoint** (lets VPC-attached resources reach S3
> without any internet route at all). "Lambda in a VPC needs its own
> connectivity plan" is a common gotcha this design sidesteps entirely.

### Other components

- **Secrets Manager** — DB password stored securely, retrieved at runtime;
  never in source code. See
  [[learning-plan/06-security-iam/secrets-manager|Secrets Manager note]].
- **S3** — image bucket with "Block All Public Access" enabled; photos served
  through the app, never directly from the bucket.
- **EC2** — web server running Docker; the app's compute core.
- **ALB** — secure entry point (`photoshare-alb-1992972335.us-east-1.elb.amazonaws.com`),
  routes internet traffic to EC2, shields infrastructure from direct exposure.
  See [[learning-plan/04-networking/load-balancers|Load balancers note]].
- **CloudWatch** — dashboard for CPU usage and Lambda errors, with alerts.

## Design decisions & tradeoffs

- **Security:** private RDS with no public access, Secrets Manager + KMS for
  credentials, S3 public access fully blocked, IAM roles instead of hardcoded
  keys — no static credentials anywhere in the stack.
- **Reliability:** *not yet addressed* — the network is already provisioned
  across 2 AZs (subnets in us-east-1a and us-east-1b, see Subnet CIDR plan
  above), but nothing actually uses the second AZ yet: single EC2 instance
  behind the ALB, no Auto Scaling Group, no Multi-AZ RDS. This is the known
  gap against the OKR's KR2 "failure handling" requirement. Planned next step:
  add an ASG (see [[learning-plan/04-networking/load-balancers|ALB + ASG
  pattern]]) and enable RDS Multi-AZ — turning on features the network
  already has room for, not re-architecting subnets.
- **Scalability:** Lambda handles image-processing burst load automatically
  (serverless, scales with S3 upload events); EC2/ALB scaling not yet in place
  (depends on the ASG addition above).
- **Cost:** *to be assessed* — single EC2 instance + RDS instance are the main
  fixed costs; Lambda and S3 are pay-per-use.

## Well-Architected review

| Pillar | Finding | Improvement made |
| --- | --- | --- |
| Operational Excellence | | |
| Security | Good baseline: private DB, blocked S3 public access, no hardcoded creds | |
| Reliability | No ASG, no Multi-AZ — single point of failure on EC2 and RDS | Planned: add ASG + Multi-AZ |
| Performance Efficiency | | |
| Cost Optimization | | |
| Sustainability | | |

## Build log / steps

1.

## Gotchas & troubleshooting

-

## Cleanup

- [ ] Tore down resources to avoid charges

## Walkthrough summary

*Draft — fill in once the build is functional.*

PhotoShare separates public-facing compute (ALB + EC2) from private data (RDS)
using VPC subnetting, removes all static credentials via IAM roles + Secrets
Manager + KMS, and offloads image processing to Lambda triggered by S3 events.
Known gap: no resilience story yet for EC2/RDS failure (single instance, no
Multi-AZ) — to be addressed before considering this complete against the OKR.

## Takeaways

-
