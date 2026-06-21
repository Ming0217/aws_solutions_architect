---
title: Connecting to EC2 — Session Manager & EC2 Instance Connect
type: note
domain: compute
date: 2026-06-17
source: Amazon Web Services in Action (book) + own notes
tags:
  - aws
  - compute
  - ec2
  - ssm
  - session-manager
  - ec2-instance-connect
  - security
  - ssh
---

# Connecting to EC2 — Session Manager & EC2 Instance Connect

> Part of [[learning-plan/02-compute/02-compute|Compute]].
> Related: [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]],
> [[learning-plan/06-security-iam/shared-responsibility-model|Shared Responsibility Model]]

The book claims two advantages for connecting to EC2 via **Systems Manager Session
Manager** and **EC2 Instance Connect**:

1. No need to configure key pairs upfront — use **temporary** keys instead.
2. No need to allow inbound SSH/RDP — which **limits the attack surface**.

Both are true as a general statement, but the two services achieve them by different
mechanisms, so the details matter.

## Session Manager (part of AWS Systems Manager)

The stronger case for both advantages.

- **How it works:** an **SSM Agent** on the instance makes an **outbound** HTTPS
  connection (port 443) to the Systems Manager service. You connect through that
  established channel.
- **No inbound ports — fully true.** No port 22 (SSH) or 3389 (RDP) opened at all; the
  security group can have **zero inbound rules**. Biggest attack-surface win.
- **No key pairs — true, but it's IAM, not "temporary keys."** Session Manager
  authenticates with **IAM** (your identity/permissions), not SSH keys at all.
- **Bonus:** session logging/auditing to S3 or CloudWatch Logs.

**Requirements:** SSM Agent installed (preinstalled on Amazon Linux + recent
Ubuntu/Windows AMIs), an **IAM instance profile** with SSM permissions, and network
**egress** to the SSM endpoints (NAT gateway, or VPC endpoints for a fully private setup).

## EC2 Instance Connect

This is where "temporary key pairs" fits best.

- **How it works:** at connect time it pushes a **one-time SSH public key** into the
  instance metadata, valid ~60 seconds. The instance lets that key authenticate, then
  it's gone — no long-lived `.pem` file to manage.
- **The inbound-SSH nuance:** plain EC2 Instance Connect still uses **SSH over port 22**.
  Connecting over the public internet still needs an **inbound rule** allowing SSH (from
  the EC2 Instance Connect service IP range). The "no inbound connectivity" benefit only
  fully holds when you use an **EC2 Instance Connect Endpoint** (2023 feature), which
  tunnels the connection so you can reach a **private** instance with no public IP and no
  open inbound SSH.

## Bottom line

| Claim | Session Manager | EC2 Instance Connect |
| --- | --- | --- |
| No upfront key pairs / temporary creds | True (IAM-based, no keys) | True (60-second temporary SSH key) |
| No inbound SSH/RDP needed | Always true (outbound only) | True only with an EIC Endpoint; plain EIC still needs inbound SSH |

**Takeaway:** Session Manager *replaces* SSH entirely with an IAM-authenticated outbound
tunnel; EC2 Instance Connect is still SSH under the hood but with short-lived keys (and
only avoids inbound rules when paired with its endpoint).

## Exam-relevant notes

- "Connect to a **private** instance with **no inbound ports** and **no bastion host**"
  → **Session Manager**.
- "Short-lived SSH access without managing key pairs" → **EC2 Instance Connect**.
- Session Manager needs the **SSM Agent** + **IAM instance profile** + **outbound 443**.
- A **bastion/jump host** is the older pattern these two services largely replace.
