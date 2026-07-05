# PhotoShare — Infrastructure as Code

IaC rebuild of the console-built [PhotoShare app](../../photoshare-app.md).
Tool: **AWS CloudFormation (YAML)** — chosen over CDK/Terraform because the goal
is to internalize the AWS resource model, and raw CFN maps 1:1 to the resources
and forces explicit dependency reasoning (see
[[learning-plan/08-automation-iac/cli-vs-cloudformation-vs-cdk|the IaC note]]).

## Two-phase plan

Rebuild **faithfully first**, then harden — so each change is a reviewable diff
that documents a tradeoff (feeds KR3 Well-Architected + KR4 walkthrough).

| Phase | File | Goal |
| --- | --- | --- |
| **Phase 1** | `photoshare-phase1.yaml` | Reproduce the console design *exactly*, including known gaps |
| **Phase 2** | `photoshare-phase2.yaml` | Harden + add resilience (multi-AZ) |

> Both templates authored; YAML structure validated. **Neither is deploy-tested yet**
> — run `validate-template` + `cfn-lint` and deploy to a throwaway stack first.
> Phase 2 introduces a **NAT Gateway** (needed once the web tier is private) — this
> adds hourly cost, so tear down promptly.

### Phase 2 changes (each becomes a documented diff)

1. **Tighten `db-sg`** — source `WebSecurityGroup` instead of the whole VPC CIDR.
2. **Move EC2 to private subnets** — admin via Session Manager (no public IP);
   only the ALB stays internet-facing.
3. **Launch Template + Auto Scaling Group** across both AZs (replaces the single
   EC2; ASG auto-registers targets with the ALB — see the ALB+ASG pattern).
4. **RDS Multi-AZ** — `MultiAZ: true` (standby in AZ2, the subnet is already there).
5. *(optional)* HTTPS listener + ACM cert + Route 53 — polish, not required by KRs.

## Deploy / verify / tear down

> RDS + ALB bill hourly. Deploy, verify, then **tear down the same day**.

```bash
# 0. Static checks first (this template was authored, not yet deployed — validate!)
aws cloudformation validate-template --template-body file://photoshare-phase1.yaml
cfn-lint photoshare-phase1.yaml     # pip install cfn-lint

# 1. Deploy (CAPABILITY_NAMED_IAM because we name the IAM roles)
aws cloudformation deploy \
  --stack-name photoshare-phase1 \
  --template-file photoshare-phase1.yaml \
  --capabilities CAPABILITY_NAMED_IAM

# 2. Read outputs (ALB DNS, RDS endpoint, bucket, secret ARN)
aws cloudformation describe-stacks --stack-name photoshare-phase1 \
  --query "Stacks[0].Outputs"

# 3. Preview a Phase 2 change BEFORE applying (the "read the change set" habit)
aws cloudformation deploy --stack-name photoshare-phase1 \
  --template-file photoshare-phase2.yaml --capabilities CAPABILITY_NAMED_IAM \
  --no-execute-changeset          # prints the change set ARN; inspect, then execute

# 4. Tear down
aws cloudformation delete-stack --stack-name photoshare-phase1
```

## Known limitations of this template (be honest in the walkthrough)

- **Not yet deployed/validated** from the authoring environment — treat as a
  first draft; expect to fix a few property names on first `deploy`.
- `UserData` and the Lambda handler are **stubs** — the app bootstrap and image
  processing logic still need to be filled in.
- `HealthCheckPath: /` is a placeholder — point it at a real health endpoint.
- Secrets Manager read is scoped via an inline policy (safer than the broad
  managed policy the console build used) — a small, deliberate improvement.
