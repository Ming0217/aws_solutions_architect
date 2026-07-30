# Clear Thinking — Infrastructure as Code

IaC for the [Clear Thinking app](../../clear-thinking-app.md).
Tool: **AWS CDK (TypeScript)** — chosen for one language across infra + app,
minimal boilerplate, and **one-command teardown** (see
[[learning-plan/08-automation-iac/cli-vs-cloudformation-vs-cdk|the IaC note]]).
This is a deliberate contrast with PhotoShare's hand-written CloudFormation, to
cover both CDK and raw CFN.

## Current state — infra-shell skeleton

`lib/clear-thinking-stack.ts` provisions the stateful + edge layer and
**synthesizes today**:

- **DynamoDB** single table (`pk`/`sk`), pay-per-request, **PITR on**, TTL attr.
- **Cognito** user pool + web client + hosted-UI domain, **invite-only**.
- **S3** (private, block-all-public) + **CloudFront** (Origin Access Control).
- CfnOutputs for the table, user pool, client, bucket, and distribution.

Left as TODO comments (added next): CRUD Lambda + HTTP API + JWT authorizer, the
AI streaming Lambda (Function URL) + Bedrock, Google federation + PreSignUp
allowlist trigger, and explicit Lambda log groups.

## Prerequisites

- Node.js 20+, and AWS credentials configured for account `us-east-1`.
- CDK bootstrap once per account/region (creates the shared `CDKToolkit` stack):
  ```bash
  npm install
  npx cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
  ```

## Deploy / verify / tear down

> Fully serverless + scale-to-zero: cost at rest is ~$0. Still, **tear down the
> same day** you test and confirm nothing lingers.

```bash
npm install
npm run build          # tsc
npx cdk synth          # confirm it synthesizes
npx cdk deploy         # deploy the stack (prints the CfnOutputs)

# ... test ...

npx cdk destroy        # tear it ALL down in one command
```

### Why teardown is clean

CDK retains stateful resources by default; this stack overrides that so
`cdk destroy` really removes them:

- **S3 site bucket** — `removalPolicy: DESTROY` + `autoDeleteObjects: true`
  (empties the bucket first so delete can't fail on non-empty).
- **DynamoDB + Cognito** — explicit `removalPolicy: DESTROY`.
- **Lambda log groups** (once compute is added) — created explicitly with
  retention + `DESTROY` so no orphaned log groups remain.

### Post-`destroy` verify checklist

- [ ] `aws cloudformation describe-stacks --stack-name ClearThinkingStack` →
      stack gone (`does not exist`).
- [ ] No leftover S3 bucket (`aws s3 ls | grep clearthinking`).
- [ ] No leftover DynamoDB table (`aws dynamodb list-tables`).
- [ ] No Cognito user pool (`aws cognito-idp list-user-pools --max-results 20`).
- [ ] No orphaned CloudWatch log groups
      (`aws logs describe-log-groups --log-group-name-prefix /aws/lambda/ClearThinking`).

### Known post-deploy step (Cognito self-sign-up)

On first deploy, CloudFormation may create the Cognito user pool with
`AllowAdminCreateUserOnly: true` even though the template sets it `false` — a
known CFN/Cognito quirk. That disables self-sign-up (the Hosted UI shows no
"Sign up" link). If so, correct the **live** pool once (re-supplying the trigger
+ settings so nothing resets):

```bash
POOL=<UserPoolId from the deploy outputs>
PRESIGNUP_ARN=$(aws cognito-idp describe-user-pool --user-pool-id $POOL \
  --query 'UserPool.LambdaConfig.PreSignUp' --output text)
aws cognito-idp update-user-pool --user-pool-id $POOL \
  --admin-create-user-config AllowAdminCreateUserOnly=false \
  --lambda-config PreSignUp=$PRESIGNUP_ARN \
  --auto-verified-attributes email
```

A redeploy alone won't fix it (no template diff). Phase 2 will add a small
custom resource so this self-corrects. Full story in the
[walkthrough §7](../walkthrough.md).

### What intentionally / necessarily lingers

- **Customer-managed KMS key** (Phase 2 only): AWS enforces a **7–30 day
  scheduled deletion** window — can't be removed instantly. Negligible cost.
- **CDK bootstrap stack** (`CDKToolkit` + its assets bucket): one-time,
  per-account/region, shared across all CDK projects — leave it. Effectively free.
- **Bedrock model access**: account-level enablement, not a stack resource —
  nothing to tear down.

## Two-phase plan (mirrors PhotoShare)

| Phase | Goal |
| --- | --- |
| **Phase 1** | Faithful serverless build: auth-first Cognito, CRUD API, DynamoDB, the 4 AI assists via Bedrock streaming, cost guardrails |
| **Phase 2** | Harden: Bedrock Guardrails (prompt-injection defense), WAF rate limiting, customer-managed KMS, IAM scoped to the model ARN, AWS Budgets, CloudWatch dashboard/alarms, X-Ray |
