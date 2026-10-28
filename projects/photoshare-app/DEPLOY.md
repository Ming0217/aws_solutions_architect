---
title: "PhotoShare — Phase 2 deploy runbook"
type: runbook
domain: architecting
tags:
  - aws
  - photoshare
  - cloudformation
  - runbook
---

# PhotoShare — Phase 2 deploy runbook

Deploy the hardened **Phase 2** stack (`iac/photoshare-phase2.yaml`) to real AWS,
validate end-to-end, then tear it down the same day. This mirrors the live deploy
recorded in [`photoshare-app.md`](./photoshare-app.md).

> **Account / region:** deploys into whatever account your creds resolve to, in
> **us-east-1** (the template pins AZs `us-east-1a/b`). Resources are name-scoped
> by account id (e.g. bucket `photoshare-images-<account>`).

## ⚠️ Security posture for this demo (decided knowingly)

- The **ALB is internet-facing on port 80, open to `0.0.0.0/0`**, and the app has
  **no user auth this pass**. While the stack is up, anyone with the ALB DNS name
  can upload/list photos. **Decision for this demo: leave it public and rely on
  same-day teardown.** (To restrict instead, set the ALB SG ingress in
  `photoshare-phase2.yaml` from `CidrIp: 0.0.0.0/0` to `<your-ip>/32`.)
- **Set a real `InternalApiKey`** (defaults to `change-me`). It gates the Lambda →
  app callback `POST /internal/metadata`. The deploy command below generates a
  random one.
- **HTTP only** (no TLS) — acceptable for a short demo; traffic isn't encrypted in
  transit. ACM + a 443 listener is optional polish.
- Already compliant by design: **RDS is private** (SG allows `:3306` from the web
  SG only; no public access), the **web tier only accepts traffic from the ALB SG**,
  **S3 Block Public Access** is on, and the **DB password is auto-generated in
  Secrets Manager** (never in code).

## Prerequisites (one-time)

```bash
# Region must be set or the CLI errors with NoRegion:
aws configure set region us-east-1 --profile "$AWS_PROFILE"   # persist to your profile
# (or, per shell session:  export AWS_DEFAULT_REGION=us-east-1)

# Confirm who/where you are:
aws sts get-caller-identity

# Optional extra linter (validate-template below is the required check):
pip3 install cfn-lint      # or: brew install cfn-lint   — skip if fussy
```

## Step 1 — Validate the template

```bash
cd projects/photoshare-app/iac
aws cloudformation validate-template --template-body file://photoshare-phase2.yaml
cfn-lint photoshare-phase2.yaml      # optional
```

## Step 2 — Build & push the app image to ECR

The EC2 instances pull `AppImageUri` on launch. For a faithful demo of the
self-built FastAPI app:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1; REPO=photoshare-app
cd ../app
aws ecr create-repository --repository-name $REPO 2>/dev/null || true
aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
docker build -t $REPO .
docker tag $REPO:latest $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest
```

- **No local Docker?** Build via **CodeBuild** (privileged) pointing at `app/` with
  `app/buildspec.yml`, env vars `ACCOUNT_ID`, `AWS_DEFAULT_REGION`,
  `REPO_URI=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/photoshare-app`.
- **Quickest / least faithful:** skip this step and deploy with the template default
  `AppImageUri=kodekloud/photosharing-app` (public image). Works, but it's the tutorial
  image, not your UI, and may not honor the `/internal/metadata` contract.

## Step 3 — Deploy Phase 2

```bash
cd ../iac
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws cloudformation deploy \
  --stack-name photoshare-phase2 \
  --template-file photoshare-phase2.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    AppImageUri=$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/photoshare-app:latest \
    InternalApiKey=$(openssl rand -hex 16)
```

RDS Multi-AZ + the ASG take several minutes (RDS is the long pole).

## Step 4 — Outputs & verify

```bash
aws cloudformation describe-stacks --stack-name photoshare-phase2 \
  --query "Stacks[0].Outputs" --output table

ALB=$(aws cloudformation describe-stacks --stack-name photoshare-phase2 \
  --query "Stacks[0].Outputs[?OutputKey=='AlbDnsName'].OutputValue" --output text)
curl -s -o /dev/null -w "%{http_code}\n" "http://$ALB/health"   # expect 200
```

Then open `http://$ALB/` in a browser, upload a photo, and confirm the flow:
S3 object → Lambda → `/internal/metadata` callback → DB row with status `processed`;
DLQ stays empty. First upload may lag while the ASG/RDS warm up. (The MySQL-8
`cryptography` crash from the first build is already fixed in the image.)

## Step 5 — Cost & teardown (same day)

Always-on cost ≈ **$0.14/hr all-in** (NAT + RDS Multi-AZ + ALB + 2× t3.micro) ≈
**$4 for a demo day**. Tear down when done:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
# Empty the image bucket first — stack delete fails on a non-empty bucket:
aws s3 rm "s3://photoshare-images-$ACCOUNT" --recursive
aws cloudformation delete-stack --stack-name photoshare-phase2
aws cloudformation wait stack-delete-complete --stack-name photoshare-phase2
```

Then finish the clean-up sweep (see `photoshare-app.md` → Cleanup):

- delete the **final RDS snapshot** if one was taken on delete,
- delete the **ECR repo** (`photoshare-app`) if you don't need the image,
- delete leftover **Lambda / CodeBuild CloudWatch log groups**,
- confirm no stray buckets / Elastic IPs / snapshots remain.
