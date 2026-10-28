# PhotoShare — Architecture Deck Talking Script

> Three slides, ~6–8 minutes. Spoken prose below; `[cues]` are stage directions,
> not things to read aloud. Deck: `slides.html` (→ = next slide).

---

## Opening (before Slide 1) — ~20 sec

"PhotoShare is an Instagram-style photo-sharing app. The design goal is simple to
say and interesting to build: keep the public-facing parts clearly separated from
the data, and process uploads in the background so the app scales without me
managing servers. I built it as infrastructure-as-code in CloudFormation, deployed
it to real AWS in us-east-1, and validated it end to end. Let me walk the
architecture in three views."

`[advance to Slide 1]`

---

## Slide 1 — Main architecture — ~2.5 min

**Request path.** `[trace left→right as you talk]`
"A user hits the app over the internet. The only internet-facing component is the
**Application Load Balancer** — it lives in public subnets across two Availability
Zones. Everything behind it is private. The ALB forwards to the **web tier**, which
is an **Auto Scaling Group of EC2 instances running my FastAPI app in Docker**,
sitting in private subnets. The web tier talks to **RDS MySQL** for photo metadata."

**Security — the part I'm proudest of.** `[point to RDS]`
"The database is protected by three independent layers. One: it's in a private
subnet with no route to the internet. Two: RDS 'public access' is switched off —
a separate control. Three: the database security group only accepts traffic from
the **web tier's security group** — not an IP range — so even another instance
inside the VPC can't reach it. Only after all three pass does a connection even get
to MySQL's own authentication. And there are **no static credentials anywhere**:
the app fetches the DB password at runtime from **Secrets Manager**, decrypted by
**KMS**."

**Reliability.** `[point to the two AZs / standby]`
"For resilience, the web tier spans two AZs and self-heals — during my deploy I
actually watched the ASG replace an unhealthy instance automatically. RDS is
**Multi-AZ**, so there's a synchronous standby in the second AZ ready to fail over.
The one deliberate single point I accepted is a **single NAT Gateway** for outbound
egress — a cost tradeoff; it doesn't affect inbound users or database failover."

`[advance to Slide 2]`
"That covers the live request path. But photo *processing* doesn't happen inline —
it's offloaded. Here's how."

---

## Slide 2 — Image pipeline — ~2 min

**The flow.** `[trace S3 → Lambda → ALB → DLQ]`
"When a photo lands in **S3**, it fires an event that triggers a **Lambda**. The
Lambda reads just the image header, extracts the dimensions and format, and then —
this is the key design choice — it **calls back into the web app through the ALB**,
and the *app* writes the metadata to the database. The Lambda never touches the
database itself. If that callback keeps failing, the message lands in a
**dead-letter queue** instead of being lost."

**Why design it this way.** `[this is the 'I understand tradeoffs' moment]`
"Three reasons. First, it keeps the Lambda **out of the VPC** — it only needs S3
and outbound HTTP, so I avoid the NAT and cold-start overhead a VPC-attached Lambda
would need. Second, **least privilege**: the Lambda's role has no database access,
no credentials, no schema — if it were ever compromised, it still can't reach the
private database. Third, **one writer** — the app already owns the DB connection,
the credentials, and the validation, so I reuse that instead of duplicating it in
the function."

**The honest tradeoff.** `[don't skip this — it lands well]`
"Now, the weak spot: because the Lambda is outside the VPC, that callback goes to
the **public** ALB over plain HTTP, authenticated only by a shared secret header.
That's fine for this no-auth lab pass, but it's not production-grade. The hardening
path would be HTTPS on the callback, moving that internal route off the public
listener, or replacing the HTTP call entirely with a queue or API Gateway. Worth
noting: in another project I solved this exact 'external component needs an internal
service' problem with API Gateway and a VPC Link — same problem, a more secure
answer."

`[advance to Slide 3]`
"Last view — how it's built and operated."

---

## Slide 3 — Build & operations — ~1.5 min

`[point to each as you go]`
"The app image is built in the cloud with **CodeBuild** and pushed to **ECR** — I
never needed a local Docker daemon — and the EC2 instances pull that image on
launch. For administration, there's **no SSH and no open ports**: I use **Systems
Manager Session Manager** to get a shell on the private instances. And
**CloudWatch** collects logs, metrics, and alarms from both the web tier and the
Lambda, so I can see CPU, errors, and the DLQ depth."

---

## Closing — ~30 sec

"To tie it to the Well-Architected pillars: **security** through the private
database and no static credentials; **reliability** through the two-AZ ASG, RDS
Multi-AZ, and the dead-letter queue; **performance** through auto-scaling and
serverless processing; and **cost** control through small instances, a single NAT,
and pay-per-use Lambda and S3 — about four dollars for a demo day, torn down after.
The whole thing is reproducible CloudFormation, and deploying it for real is what
surfaced the bugs that static checks miss. Happy to dig into any piece."

---

## Q&A prep (likely questions)

- **Why EC2 for the web tier, not Lambda or Fargate?** It's a long-running web
  server; EC2 behind an ASG is the faithful, cost-predictable choice. The *bursty*
  image work is where I used serverless.
- **Why Multi-AZ RDS vs. read replicas?** Multi-AZ is for **availability** (failover
  standby), not read scaling. Read replicas would be the answer if reads were the
  bottleneck.
- **Why only one NAT Gateway?** Cost. A per-AZ NAT removes the egress single-point
  at ~2× NAT cost; acceptable here since it's outbound-only.
- **Why does the Lambda call back through the ALB instead of writing to RDS?**
  Least privilege + keeping it out of the VPC + a single DB writer. (See Slide 2.)
- **How did you build the image without Docker locally?** CodeBuild → ECR; I also
  have a Finch path for local builds. The one gotcha: build for `linux/amd64` since
  the EC2 hosts are x86_64.
- **Is it secure right now?** The app has no user auth this pass and the ALB is
  public — a knowing choice for the demo; I tear it down the same day. The data
  tier is fully private regardless.
