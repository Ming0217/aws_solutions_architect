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

### Other components

- **IAM Roles** — `iam_role_ec2` and `iam_role_lambda` act as temporary
  security badges (assumed roles, no hardcoded API keys). See
  [[learning-plan/06-security-iam/iam-users-groups-roles-policies|IAM note]].
- **KMS** — AWS-managed key encrypts secrets; data appears as scrambled
  gibberish even if accessed directly. See
  [[learning-plan/06-security-iam/kms-key-management-service|KMS note]].
- **RDS** — MySQL in the private subnet, Public Access disabled; only EC2 can
  reach it. See [[learning-plan/05-databases/rds-core-concepts|RDS note]].
- **Secrets Manager** — DB password stored securely, retrieved at runtime;
  never in source code. See
  [[learning-plan/06-security-iam/secrets-manager|Secrets Manager note]].
- **S3** — image bucket with "Block All Public Access" enabled; photos served
  through the app, never directly from the bucket.
- **EC2** — web server running Docker; the app's compute core.
- **Lambda** — triggers automatically on S3 upload to process image metadata
  in the background.
- **ALB** — secure entry point, routes internet traffic to EC2, shields
  infrastructure from direct exposure. See
  [[learning-plan/04-networking/load-balancers|Load balancers note]].
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
