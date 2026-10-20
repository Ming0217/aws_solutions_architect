---
title: EC2 Key Pairs — SSH access (generate vs import)
type: note
domain: compute
date: 2026-10-19
source: Skill Builder course + own notes
tags:
  - aws
  - compute
  - ec2
  - ssh
  - key-pairs
  - security
---

# EC2 Key Pairs — SSH access (generate vs import)

> Part of [[learning-plan/02-compute/02-compute|Compute]].
> Related: [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|Connecting to EC2 —
> Session Manager & EC2 Instance Connect]] (the *no-SSH* alternative this repo
> prefers) · [[learning-plan/04-networking/security-groups-vs-private-network|Security
> Groups]] (SSH needs inbound port 22)

A **key pair** is how you connect to an EC2 instance over **SSH** without a
password. It's **public-key cryptography**: a matched pair of keys where the
**public** key is handed to AWS and placed on the instance, and the **private**
key stays with you and proves your identity when you connect.

> **Read this alongside the [[learning-plan/02-compute/connecting-to-ec2-ssm-eic|
> Session Manager note]].** SSH key pairs are the *traditional* way in — but they
> require an **inbound port 22** rule (attack surface) and a private key to
> safeguard. **Session Manager replaces SSH entirely** (IAM-authenticated,
> outbound-only, zero inbound ports) and is the hardened default this repo favors
> (see PhotoShare's Phase 2). Use key pairs when you specifically need SSH; reach
> for Session Manager when you don't.

## How a key pair actually works

- A key pair = **public key** + **private key**, mathematically linked.
- AWS stores the **public** key and **injects it into the instance's
  `~/.ssh/authorized_keys`** at launch (via cloud-init, into the AMI's default
  user — `ec2-user`, `ubuntu`, etc.).
- On connect, your SSH client presents the **private** key; the instance checks it
  against the stored public key. Match → you're in. **No password involved.**
- **AWS never has your private key** (in the import flow below) — it only ever
  holds the public half. The private key is the secret; guard it accordingly.

## Two ways to get a key pair

### 1. AWS-generated (the common console path)

AWS creates the pair for you and lets you **download the private key** (`.pem`).
Convenient, but: the private key was generated on AWS's side and travels to you on
download — a slightly weaker trust posture, and if you lose the `.pem` you can't
re-download it.

### 2. Import (what this course does — the stronger pattern)

You generate the pair **locally** and push only the **public** key to AWS. The
**private key never leaves your machine** — AWS only ever sees the public half.

```bash
# Step 1 — generate the pair locally
ssh-keygen -t rsa -b 2048 -f ~/.ssh/streaming-key -N ""

# Step 2 — import ONLY the public key (.pub) to AWS
aws ec2 import-key-pair \
  --region us-east-1 \
  --key-name streaming-key \
  --public-key-material fileb://~/.ssh/streaming-key.pub

# Step 3 — verify: EC2 console → Key Pairs → "streaming-key" is listed
#   (or: aws ec2 describe-key-pairs --key-names streaming-key)
```

**Decoding `ssh-keygen -t rsa -b 2048 -f ~/.ssh/streaming-key -N ""`:**

| Flag | Meaning |
| --- | --- |
| `-t rsa` | Key type = RSA (ed25519 is a modern alternative) |
| `-b 2048` | Key size = 2048 bits |
| `-f ~/.ssh/streaming-key` | Output path → private key `streaming-key` **+** public key `streaming-key.pub` |
| `-N ""` | **Empty passphrase.** Fine for a throwaway lab; a real key should have a passphrase |

**Two things people trip on:**

- **`fileb://` vs `file://`** — `import-key-pair` wants `fileb://` (reads the file
  as **binary**). Using `file://` (text) is a common failure here.
- **Import the `.pub`, never the private key.** `--public-key-material` takes the
  **public** half (`streaming-key.pub`). The private key (`streaming-key`, no
  extension) stays local and is never uploaded.

## Connecting with the key

```bash
ssh -i ~/.ssh/streaming-key ec2-user@<public-ip-or-dns>
#        └── private key        └── AMI default user (ec2-user on Amazon Linux,
#                                   ubuntu on Ubuntu, etc.)
```

Requires an **inbound SSH rule (port 22)** on the instance's security group — and
a public IP / route to reach it. (This is the attack-surface cost the Session
Manager note argues against; scope the rule to **My IP**, never `0.0.0.0/0`, if
you must open it.)

## Security notes (private-key hygiene)

- **Permissions:** SSH refuses to use a private key that's too open. `chmod 400
  ~/.ssh/streaming-key` (owner read-only) or you'll get an
  "UNPROTECTED PRIVATE KEY FILE" error.
- **Never commit or share the private key** — not to git, not in chat, not in an
  AMI/snapshot. Treat it like a password. (Public key is safe to share.)
- **Use a passphrase** on real keys (not `-N ""`) so a stolen key file alone isn't
  enough; pair with `ssh-agent` so you don't retype it.
- **Rotate / scope:** one key per purpose; delete the AWS key pair + local files
  when done. Losing an AWS-generated `.pem` is unrecoverable — imported keys you
  can at least re-import.

## Where this shows up in projects

- **[[projects/video-streaming-app|Video Streaming Platform]]** — `streaming-key`
  imported for SSH admin access to the streaming EC2 instance during the lab
  build. **Hardening note:** the preferred path is **Session Manager (no inbound
  22)** — same tradeoff flagged and resolved in PhotoShare's Phase 2; the key-pair
  SSH route is the lab's simpler v1.

## Exam-relevant notes

- Key pair = public/private; AWS stores the **public** key + injects it into the
  instance's `authorized_keys`; **you keep the private** key.
- **Import** flow (`ssh-keygen` locally → `import-key-pair` with the `.pub`) keeps
  the private key off AWS entirely — stronger than AWS-generating + downloading.
- `import-key-pair` needs `fileb://` (binary), and takes the **public** key.
- Lose an AWS-generated `.pem` → **unrecoverable** (make a new pair).
- SSH needs **inbound port 22** on the security group; **Session Manager** avoids
  inbound SSH entirely (preferred for hardening).
