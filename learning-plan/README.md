---
title: Learning Plan — Progress Tracker
type: moc
tags:
  - aws
  - tracker
---

# Learning Plan — Progress Tracker

Notes are grouped by topic domain rather than by course, so they stay useful even
if the plan changes. Update the course list below with the actual modules from
[the Skill Builder plan](https://skillbuilder.aws/learning-plan/EB6SVX4CTK/aws-solutions-architect-learning-plan-includes-labs/SAJSTUCC44)
as you go.

## Topic domains

| # | Domain | Notes | Status |
| --- | --- | --- | --- |
| 01 | Cloud foundations & the Well-Architected Framework | [[learning-plan/01-cloud-foundations/README\|open]] | ⬜ Not started |
| 02 | Compute (EC2, Lambda, Auto Scaling) | [[learning-plan/02-compute/README\|open]] | ⬜ Not started |
| 03 | Storage (S3, EBS, EFS) | [[learning-plan/03-storage/README\|open]] | ⬜ Not started |
| 04 | Networking & content delivery (VPC, Route 53, CloudFront) | [[learning-plan/04-networking/README\|open]] | ⬜ Not started |
| 05 | Databases (RDS, Aurora, DynamoDB) | [[learning-plan/05-databases/README\|open]] | ⬜ Not started |
| 06 | Security, identity & IAM | [[learning-plan/06-security-iam/README\|open]] | ⬜ Not started |
| 07 | Monitoring & observability (CloudWatch, X-Ray) | [[learning-plan/07-monitoring/README\|open]] | ⬜ Not started |
| 08 | Automation & IaC (CloudFormation, CDK) | [[learning-plan/08-automation-iac/README\|open]] | ⬜ Not started |
| 09 | Containers (ECS, EKS, Fargate) | [[learning-plan/09-containers/README\|open]] | ⬜ Not started |
| 10 | Architecting & best practices | [[learning-plan/10-architecting/README\|open]] | ⬜ Not started |

Status legend: ⬜ Not started · 🟡 In progress · ✅ Done

## Course checklist

Fill this in with the actual courses from the plan as you encounter them.

- [ ] _Course name_ — link / notes
- [ ] _Course name_ — link / notes

## Dataview: all in-progress modules

> [!tip] Requires the Dataview community plugin.

```dataview
TABLE status, domain, date-started AS "Started"
FROM "learning-plan"
WHERE status = "in-progress"
SORT date-started DESC
```
