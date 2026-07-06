---
title: "Project: PhotoShare — Instagram-style photo sharing app"
type: project
domain: architecting
date-started: 2026-07-04
services:
  - vpc
  - alb
  - ec2
  - asg
  - rds
  - s3
  - lambda
  - sqs
  - iam
  - kms
  - secrets-manager
  - cloudwatch
  - ecr
  - codebuild
  - nat-gateway
status: iac-rebuilt-and-tested
tags:
  - aws
  - project
---

# Project: PhotoShare — Instagram-style photo sharing app

> Related: [[projects/projects|projects index]] ·
> [architecture walkthrough](./photoshare-app/walkthrough.md) ·
> [IaC](./photoshare-app/iac/README.md) · [app](./photoshare-app/app/README.md) ·
> [lambda](./photoshare-app/lambda/README.md)
> Design source: KodeKloud project template (v1 console build); since rebuilt as
> IaC with a self-built app + frontend.
> Part of the [H2 2026 AWS OKR](../README.md) — counts toward KR1 (documented
> architecture), KR2 (working project), KR3 (Well-Architected), and KR4 (walkthrough).

> **Update 2026-07-05 — IaC rebuild deployed & tested.** The console build has
> been reproduced as **CloudFormation** (Phase 1 faithful → Phase 2 hardened +
> multi-AZ), the tutorial's prebuilt image replaced with a **self-built FastAPI
> app + Apple-style frontend** (built via **CodeBuild → ECR**, no local Docker),
> and the Phase 2 stack was **deployed and validated end-to-end on real AWS**.
> The earlier "Reliability not yet addressed" gap is now **closed** (ASG + RDS
> Multi-AZ, verified live). Details in the [walkthrough §7](./photoshare-app/walkthrough.md).
> Sections below describing the original console build are kept as the v1 record;
> deltas are noted inline.

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
>
> **✅ Resolved in the IaC Phase 2 rebuild:** the web tier now runs in the
> **private subnets** behind the ALB (Launch Template + ASG), with admin via
> Session Manager and outbound access via a NAT gateway. Only the ALB is
> internet-facing.

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

> **Confirmed / refined in the IaC rebuild** (the console TBDs are now resolved):
> - `iam_role_lambda` = `AWSLambdaBasicExecutionRole` (CloudWatch Logs) +
>   scoped `s3:GetObject` on the image bucket + `sqs:SendMessage` on the DLQ.
> - `iam_role_ec2` also got `AmazonSSMManagedInstanceCore` (Session Manager) and
>   `AmazonEC2ContainerRegistryReadOnly` (pull the app image from ECR), and the
>   broad Secrets-Manager managed policy was replaced with a **scoped inline
>   policy** limited to this project's secret (least privilege).

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
- **Reliability:** ✅ **addressed in IaC Phase 2 and verified live.** The web
  tier now runs as an **Auto Scaling Group across 2 AZs** behind the ALB (see
  [[learning-plan/04-networking/load-balancers|ALB + ASG pattern]]), and RDS is
  **Multi-AZ** (synchronous standby). During deployment the ASG's self-healing
  was observed for real (unhealthy instances auto-replaced). Remaining SPOF: a
  single NAT gateway (outbound egress only — accepted at ~99.9%).
- **Scalability:** Lambda handles image-processing burst load automatically
  (serverless); the web tier now scales via ASG **target-tracking on CPU (60%)**.
- **Cost:** main fixed costs are RDS Multi-AZ, the NAT gateway, and the ALB
  (~$0.16/hr all-in for the test); Lambda + S3 are pay-per-use. Single NAT
  chosen deliberately to control cost.

## Well-Architected review

| Pillar | Finding | Improvement made |
| --- | --- | --- |
| Operational Excellence | Console build wasn't reproducible | Rebuilt as **CloudFormation** (versioned IaC); app built via **CodeBuild → ECR**; pre-deploy `validate-template` + `cfn-lint` |
| Security | Good baseline: private DB, blocked S3 public access, no hardcoded creds | **db-sg scoped to web SG**; **EC2 moved to private subnets** (Session Manager admin); scoped inline Secrets policy (dropped broad managed policy) |
| Reliability | No ASG, no Multi-AZ — SPOF on EC2 and RDS | **ASG across 2 AZs + RDS Multi-AZ + DLQ**, deployed and verified live |
| Performance Efficiency | No auto-scaling | ASG **target-tracking on CPU**; serverless image processing |
| Cost Optimization | Not assessed | t3.micro + single NAT to control cost; pay-per-use Lambda/S3 (right-size after load testing) |
| Sustainability | — | Managed services + scale-to-zero Lambda |

## Build log / steps

Built end-to-end through the AWS console (no IaC yet):

1. **VPC & networking** — `photoshare-vpc` (`10.0.0.0/16`), 4 subnets across
   2 AZs (`10.0.1.0/24`–`10.0.4.0/24`), Internet Gateway, and route tables
   (public subnets routed to the IGW, private subnets isolated). See Subnet
   CIDR plan above.
2. **IAM roles** — `iam_role_ec2` (EC2 trust, `AmazonS3FullAccess` +
   `AWSSecretsManagerClientReadOnlyAccess`) and `iam_role_lambda` (Lambda
   trust; exact attached policies still **TBD/unconfirmed** — see the "can't
   find Lambda in CloudWatch" gotcha below, which depends on whether
   `AWSLambdaBasicExecutionRole` is actually attached).
3. **KMS** — used the AWS-managed `alias/aws/secretsmanager` key (no
   customer managed key needed for this pass).
4. **RDS** — MySQL instance in the private subnet (DB Subnet Group across
   both AZs), Public Access disabled, `db-sg` allowing port 3306 from
   `10.0.0.0/16` (known hardening gap — see tradeoffs below).
5. **Secrets Manager** — DB credentials stored and retrieved by the EC2 app
   at runtime via `iam_role_ec2`.
6. **S3** — image bucket created with Block All Public Access enabled.
7. **EC2** — web server launched in the public subnet, running the app via
   Docker Compose.
8. **Lambda** — image-metadata function deployed with **no VPC attachment**
   (relies on default internet access to reach S3 and the ALB — see Lambda
   subsection above).
9. **ALB** — `photoshare-alb-1992972335.us-east-1.elb.amazonaws.com`,
   internet-facing, routing to the EC2 target group.
10. **CloudWatch** — dashboard covering EC2 CPU and Lambda errors.

Console build completed 2026-07-04. Resilience hardening (ASG, RDS Multi-AZ)
not yet done — see Next steps below.

## Gotchas & troubleshooting

- **Target group stuck in `unused`:** caused by the EC2 instance sitting in
  an AZ (`us-east-1d`) the ALB had no subnet in. Fixed by launching the
  instance in one of the ALB's actual AZs (`us-east-1a`/`us-east-1b`) instead
  of adding a new ALB subnet.
- **Can't find Lambda in CloudWatch:** Lambda only creates its log group and
  starts emitting metrics after its **first invocation** — nothing shows up
  until the function is actually triggered (test event or real S3 upload).
  Also confirm `iam_role_lambda` has `AWSLambdaBasicExecutionRole` attached,
  or logs will silently never appear even after invocation.
- **`db-sg` inbound rule uses `10.0.0.0/16` (entire VPC) as the source**,
  not the EC2 security group specifically — broader than the "only EC2 can
  reach it" goal implies. Tutorial simplification (avoids a dependency-order
  problem, since `db-sg` may be created before the EC2 security group
  exists); flagged as a hardening item. **✅ Fixed in IaC Phase 2:** `db-sg`
  now sources the **web security group** directly (CloudFormation orders the
  dependency for us), so only the web tier can reach MySQL.
- **App crash-loop on first deploy — MySQL 8 auth plugin.** The self-built app
  couldn't authenticate to RDS: `'cryptography' package is required for
  sha256_password or caching_sha2_password auth methods`. MySQL 8 defaults to
  the **`caching_sha2_password`** plugin, which **PyMySQL needs the
  `cryptography` package** to handle — and it was missing from
  `requirements.txt`. Instances failed startup and the ASG kept recycling them.
  **Fix:** add `cryptography`, rebuild the image, roll the ASG (instance
  refresh). A local Docker smoke-test would have caught this instantly.

## Verifying the app — inspecting RDS data

RDS is private with no public access, so you can't connect from a laptop
directly — you must go **through the EC2 instance**, the only thing `db-sg`
allows in.

**Option A — simplest, from the EC2 instance directly:**

1. Connect to EC2 via **Session Manager** (console → EC2 → instance →
   Connect → Session Manager tab — no SSH, no public IP needed, per
   [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|the SSM note]]).
2. From that shell: `mysql -h <rds-endpoint> -u <username> -p <database-name>`
   — get the endpoint from RDS console → Connectivity & security, and
   credentials from Secrets Manager (`aws secretsmanager get-secret-value
   --secret-id <secret-name>`) if not the master ones.
3. Once connected: `SHOW TABLES;` then `SELECT * FROM <table_name>;`.
   (If the app runs in Docker, may need `docker exec -it <container> mysql
   ...` instead, depending on whether the client is on the host or in the
   container.)

**Option B — nicer, GUI client (MySQL Workbench, DBeaver, TablePlus) from a
laptop, tunneled through EC2 via SSM port forwarding** (same zero-inbound-ports
principle as Session Manager — no SSH, no opened ports):

```
aws ssm start-session \
  --target <ec2-instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<rds-endpoint>"],"portNumber":["3306"],"localPortNumber":["3306"]}'
```

Then point the GUI client at `localhost:3306` with the same DB credentials.

## IaC rebuild & live deploy (2026-07-05)

Reproduced the console build as code and deployed it for real. Full record in the
[walkthrough §7](./photoshare-app/walkthrough.md); summary:

1. **CloudFormation, two phases** — `iac/photoshare-phase1.yaml` (faithful
   rebuild, including the known gaps) → `iac/photoshare-phase2.yaml` (hardened:
   db-sg scoped, EC2 private + NAT, Launch Template + ASG across 2 AZs, RDS
   Multi-AZ, SQS DLQ).
2. **Self-built app** — FastAPI service + Apple-style frontend
   ([`app/`](./photoshare-app/app/README.md)) replacing the tutorial image;
   reverse-engineered image-processing Lambda ([`lambda/`](./photoshare-app/lambda/README.md)).
3. **Built without local Docker** — image built via **CodeBuild** (source → S3,
   privileged build) and pushed to **ECR**.
4. **Pre-deploy validation paid off** — `validate-template` caught a circular
   dependency; `cfn-lint` caught a missing RDS `UpdateReplacePolicy`. Both fixed
   before deploying.
5. **Deployed Phase 2 + passed live E2E** — upload → S3 → Lambda → ALB callback →
   RDS (`processed`, dimensions `240×160`), image served through the app, RDS
   confirmed private + Multi-AZ, DLQ empty. One real bug found & fixed (the
   `cryptography`/MySQL-8 auth issue — see Gotchas).

## Next steps

Core OKR work for this project is **done** (KR1 architecture, KR2 working +
failure handling, KR3 Well-Architected pass, KR4 walkthrough). Optional polish:

1. **Deploy the fuller Lambda by default** (currently the template ships the
   trimmed inline version; the dimension-parsing `handler.py` was applied via
   `update-function-code`). Package it in the template via S3 or a build step.
2. **Route 53 + ACM (HTTPS)** and an internal listener for the callback route.
3. **Scope `AmazonS3FullAccess`** down to the specific bucket/actions.
4. **Local Docker smoke-test tier** so app bugs (like the `cryptography` one)
   are caught before an AWS deploy.

## Cleanup

Torn down 2026-07-05 after the successful live test (verified nothing lingers):

- [x] Deleted the `photoshare-phase2` stack (RDS took a final snapshot on delete)
- [x] Deleted that final RDS snapshot too (throwaway test data)
- [x] Emptied + deleted the image bucket and the CodeBuild source bucket
- [x] Deleted the CodeBuild project, ECR repo, and CodeBuild IAM role
- [x] Deleted the leftover CloudWatch log groups (Lambda + CodeBuild)
- [x] Confirmed no unassociated Elastic IPs, buckets, or snapshots remain

## Walkthrough summary

PhotoShare separates public-facing compute (ALB + a self-built FastAPI web tier
on EC2) from private data (RDS MySQL, Multi-AZ, no public access) using VPC
subnetting; removes all static credentials via IAM roles + Secrets Manager + KMS;
and offloads image processing to an S3-triggered Lambda that calls back through
the ALB (keeping it out of the DB path). Rebuilt from the console as
**CloudFormation** (faithful → hardened + multi-AZ), the app image built in the
cloud via **CodeBuild → ECR**, and the whole stack **deployed and validated
end-to-end on real AWS**. Reliability (ASG across 2 AZs + RDS Multi-AZ) is in
place and was observed self-healing during the deploy.

## Takeaways

- **Real AWS validation catches what local parsing can't** — `validate-template`
  surfaced a circular dependency; `cfn-lint` a missing `UpdateReplacePolicy`.
- **A live deploy surfaces runtime bugs static checks miss** — the MySQL 8
  `caching_sha2_password` / `cryptography` crash-loop only appeared at runtime;
  it argues strongly for a local container smoke-test tier.
- **The ASG + ALB + Multi-AZ pattern self-heals** — watched unhealthy instances
  get replaced and a rolled image go healthy with no manual steps.
- **You can build container images without local Docker** — CodeBuild + ECR.
- **IaC makes hardening a reviewable diff** — Phase 1 → Phase 2 turned each known
  gap (db-sg, EC2 placement, reliability) into an explicit, documented change.
