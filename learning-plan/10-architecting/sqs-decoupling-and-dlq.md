---
title: SQS — Decoupling, Visibility Timeout & DLQ
type: note
domain: architecting
date: 2026-10-19
source: Skill Builder course + own notes
tags:
  - aws
  - sqs
  - messaging
  - decoupling
  - architecting
---

# SQS — Decoupling, Visibility Timeout & DLQ

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & Best Practices]]
> (the module lists "decoupling (SQS/SNS)" directly).
> Related: [[learning-plan/04-networking/load-balancers|Load balancers]]
> (the other "don't talk directly" pattern) ·
> [[learning-plan/01-cloud-foundations/elasticity-and-flexible-capacity|Elasticity]]

Amazon SQS (Simple Queue Service) is a **fully managed message queue** that sits
*between* components so they don't call each other directly. It's the canonical
**decoupling** primitive: a producer drops a message in the queue and moves on; a
consumer pulls it when it's ready. Neither has to be up, fast, or scaled at the
same time as the other.

## The problem it solves — synchronous calls couple failure and speed

If a web frontend calls a backend worker **directly** and waits for the result,
the two are coupled on **availability** (worker down → request fails) and on
**speed** (slow worker → user waits / request times out).

> **Scenario (financial report generator):** generating a multi-year PDF audit
> report is slow (heavy DB queries). If the user's page had to wait for the PDF
> to render, it would time out. Put an **SQS queue in the middle**: the web
> server enqueues a "generate report" message and *instantly* returns "Report
> generation started"; backend workers pull from the queue and render PDFs **at
> their own pace**. The request is accepted in milliseconds; the slow work
> happens asynchronously.

This is the same spirit as a load balancer ("don't let clients hit servers
directly") but for **async work over time** rather than spreading live requests —
see [[learning-plan/04-networking/load-balancers|the ALB note]].

## Core mechanics

### Producers & consumers

- **Producer** — whatever puts a message *in* (the web server enqueuing a report
  request). `SendMessage`.
- **Consumer** — whatever pulls a message *out* and processes it (the backend
  render worker). `ReceiveMessage` → do work → `DeleteMessage`.

The two sides know nothing about each other — only the queue. Either can scale,
deploy, or fail independently. You can run **many consumers** pulling from one
queue to process in parallel (horizontal scale on the work, driven by queue
depth).

### Visibility timeout — stops two workers doing the same job

> **Explain-it-simply (the chore jar).** Picture a jar of chore cards and 10 kids
> who all reach in for chores. The risk: two kids grab the *same* chore and both
> rake the same leaves — wasted work.
>
> The **visibility timeout** is the jar's magic rule: the instant one kid pulls a
> card, the jar makes that chore **invisible** to the other 9 — like the card
> turns into a ghost only the holder can see. So nobody can grab a chore someone
> else already took. Collision avoided.
>
> But there's a **timer**: "I'll hide this for 10 minutes — enough to rake the
> leaves." Two outcomes:
> - Kid **finishes** → comes back, tears up the card (`DeleteMessage`) → gone
>   forever.
> - Kid **wanders off** and never finishes → timer runs out → the card
>   **reappears**, and another kid can do it. Nothing lost because one kid flaked.
>
> **Why the timer length matters:** if raking really takes 15 min but the jar
> only hides it for 10, the card reappears while the first kid is *still* raking →
> a second kid grabs the same leaves. So hide it **longer than the chore actually
> takes**.
>
> **The rare leftover case:** a kid finishes at minute 9 but trips before tearing
> up the card; at minute 10 the jar brings it back and someone re-rakes
> already-raked leaves. Fix: smart kids **check first** ("already raked? skip") —
> that's **idempotency**. Two rules together: the timer stops everyday
> collisions, checking-first catches the rare weird ones.

When a consumer receives a message, SQS doesn't delete it — it makes it
**invisible** to other consumers for a configurable **visibility timeout**. While
hidden, no other worker can pick up that same message, so you don't get duplicate
processing.

- Consumer finishes → calls **`DeleteMessage`** → message is gone for good.
- Consumer crashes / never deletes → when the visibility timeout **expires**, the
  message **reappears** in the queue and another consumer can take it. (This is
  the built-in retry: failure just means the message comes back.)

> **The tuning tradeoff:** set the timeout **longer than your worst-case
> processing time**. Too short → the message reappears while the first worker is
> *still* working on it → two workers process it (duplicate work). Too long → if
> a worker dies, the message sits invisible and unprocessed for a long time
> before retry. Match it to how long the job actually takes.

> **Q: 10 workers all poll the same queue — what stops two of them generating
> the exact same report at once?** The **visibility timeout**: the instant one
> worker receives the message, SQS hides it from the other 9 for the timeout
> duration, so only one worker ever sees a given message at a time. This is the
> primary mechanism against duplicate work across a fleet of consumers.
>
> **But it's not an absolute guarantee** — and this is the layering to keep
> straight:
> - **Visibility timeout** handles the *normal* case (concurrent pollers don't
>   collide).
> - **Idempotency** is the backstop for the edge cases it *can't* cover —
>   specifically when processing outruns the timeout (message reappears mid-work)
>   or a worker finishes but crashes before `DeleteMessage`. Because Standard SQS
>   is **at-least-once**, a duplicate delivery is always *possible*, so a correct
>   consumer must also be safe to run twice (e.g. check the job id: "already
>   generated this report? skip").
>
> Short version: visibility timeout prevents *most* duplicates; idempotency makes
> the *remaining* ones harmless. You want both.

#### Addressing a queue — Queue URL vs ARN

Creating a queue gives you a **Queue URL** like:

```
https://sqs.us-east-1.amazonaws.com/<account-id>/ReportGenerationQueue
         └──┬──┘ └───┬───┘           └────┬─────┘ └────────┬─────────┘
          service  region            account ID        queue name
```

- **`sqs.<region>.amazonaws.com`** — the regional service endpoint. Queues are
  **regional**, and you interact with them purely over this HTTPS API (the "API
  is the only door in" again).
- **`<account-id>`** — the queue is namespaced under your account, which is why
  queue names only need to be unique **within your account + region** — unlike S3
  bucket names, which are globally unique.
- **`ReportGenerationQueue`** — the name you chose.

Two identifiers for the same queue, used in **different places**:

| Identifier | Form | Used by |
| --- | --- | --- |
| **Queue URL** | `https://sqs.<region>.amazonaws.com/<account-id>/<name>` | The **API/SDK/CLI** — every `SendMessage`/`ReceiveMessage`/`DeleteMessage` call targets the queue by URL |
| **Queue ARN** | `arn:aws:sqs:<region>:<account-id>:<name>` | **IAM policies** and the **DLQ redrive policy** — anywhere AWS references the queue as a resource |

```bash
# produce (by Queue URL)
aws sqs send-message \
  --queue-url https://sqs.<region>.amazonaws.com/<account-id>/ReportGenerationQueue \
  --message-body '{"reportId":"123","range":"2020-2026"}'

# consume → process → delete by the receipt handle returned on receive
aws sqs receive-message --queue-url <queue-url>
aws sqs delete-message  --queue-url <queue-url> --receipt-handle <handle>
```

> **Don't confuse the `receipt-handle` with the message id.** The receipt handle
> is issued fresh on *each receive* and is what you pass to `DeleteMessage` — it's
> how SQS knows *which in-flight delivery* you're acknowledging, not just which
> message.

> **Important consequence — SQS Standard is "at-least-once."** Because a message
> reappears on failure/timeout, the *same* message can be delivered **more than
> once** (e.g. worker finished but crashed before `DeleteMessage`). So consumers
> should be **idempotent** — processing the same message twice must not corrupt
> state (e.g. use the message/job id to detect "already done"). This is the
> single most common SQS gotcha.

### Dead Letter Queue (DLQ) — isolate the poison message

What if a message can **never** succeed? (A message like this — one that fails
every time it's processed — is commonly called a **poison pill** / poison
message.) A badly formatted date range crashes the
PDF generator every time. Without protection, the flow loops forever: receive →
crash → visibility timeout expires → reappear → receive → crash… blocking the
queue and burning compute.

A **Dead Letter Queue** breaks that loop. It's just a *second ordinary queue* you
attach to the main one via a **redrive policy** with a **`maxReceiveCount`**:

- Each time a message is received without being deleted, SQS increments its
  receive count.
- When receive count exceeds **`maxReceiveCount`** (e.g. 3), SQS stops retrying
  and **moves the message to the DLQ** instead of returning it to the main queue.
- The main queue keeps flowing (poison message is out of the way); the DLQ holds
  the failures for **inspection, alerting, or manual replay** later.

> **Mental model:** the DLQ is the "failed jobs" tray. `maxReceiveCount` is "how
> many times we'll let this thing fail before we give up and set it aside."
> Monitor DLQ depth — a non-empty DLQ means something is systematically failing
> and needs a human (or a fix + redrive).

> **Gotcha — the redrive policy lives on the MAIN queue, not the DLQ.** A DLQ is
> just an **ordinary standard queue** with zero special configuration; nothing
> about it is inherently "a DLQ." What *makes* it one is the **main queue**
> pointing at it. So the wiring is:
> 1. Create a plain standard queue to serve as the DLQ (e.g. `ReportDLQ`).
> 2. Then **edit the main queue** (`ReportGenerationQueue`) → Dead-letter queue
>    section → enable, select the DLQ, set **Maximum receives** (= `maxReceiveCount`,
>    e.g. 5).
>
> In the console you configure it under the *main* queue's settings and verify it
> under the *main* queue's "Dead-letter queue" tab — you never touch `ReportDLQ`
> itself. (Common confusion: looking at the DLQ expecting to find the redrive
> config there.) The same queue could even be the DLQ for several main queues —
> it's the redrive policies on *those* queues that do all the work.

## Queue access policy — letting another AWS service send (resource policy + the `SourceArn` guard)

When the **producer is another AWS service** (e.g. S3 sending an event on every
upload), you don't attach an IAM role to S3 — S3 has no role of yours to attach.
Instead you authorize it on the **queue itself** with a **resource-based policy**
(the SQS *access policy*). This is the identity-vs-resource-policy distinction
from
[[learning-plan/06-security-iam/iam-users-groups-roles-policies|the IAM note]]:
an **identity** policy attaches to a user/role ("what I may do"); a **resource**
policy attaches to the resource ("who may act on me").

Canonical "S3 → SQS on upload" queue policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "s3.amazonaws.com" },
    "Action": "sqs:SendMessage",
    "Resource": "arn:aws:sqs:us-east-1:123456789012:VideoQueue",
    "Condition": {
      "ArnLike": { "aws:SourceArn": "arn:aws:s3:::lab-video-input-<id>" }
    }
  }]
}
```

Line by line:

- **`Principal: { "Service": "s3.amazonaws.com" }`** — *who* may act: the S3
  service. Only a **resource** policy can grant a permission *to another AWS
  service* like this.
- **`Action: "sqs:SendMessage"`** — *what*: send messages, nothing else.
- **`Resource: ...:VideoQueue`** — *on which* queue (its **ARN** — copy it from
  the queue's default policy; the **URL** is a *different* identifier your app
  code uses — see [URL vs ARN](#addressing-a-queue--queue-url-vs-arn)).
- **`Condition.aws:SourceArn`** — **the critical line**: restrict the grant so
  **only events from *your specific bucket*** can trigger a send.

### Why the `SourceArn` condition matters — the confused deputy problem

Without the condition, the policy effectively says *"**any** S3 bucket may send
to this queue."* S3 ARNs don't contain an account id (`arn:aws:s3:::bucket-name`
is global), so someone **in another account** could point *their* bucket at your
queue and flood it — using the S3 service as a **confused deputy**: a trusted
intermediary tricked into acting on an attacker's behalf.

The **`aws:SourceArn`** condition pins the grant to *your* bucket's ARN only, so
S3 is only authorized when the triggering event genuinely comes from your
resource. (`aws:SourceAccount` is the sibling guard when you want to pin by
account.) **This is the standard pattern for any service-to-service trigger**
(S3→SQS, S3→SNS, SNS→SQS, EventBridge→…), not a one-off — worth recognizing by
name.

### Two sides must both be wired

S3→SQS needs **both** halves, or nothing flows:

1. **The queue's resource policy** (above) — "S3 is *allowed* to send to me."
2. **The S3 event notification** on the bucket — "S3, *please* send to this queue
   on object-create." (S3 console → bucket → Properties → Event notifications.)

Miss either and uploads produce no messages. (The resource policy is permission;
the event notification is the actual trigger config.)

> **Q: How does the queue know a new video needs processing?** It doesn't — the
> queue is **passive**. **S3 pushes an event to SQS on object creation** (the
> `VideoUploadEvent` notification), which places the job message in the queue.
> SQS never watches S3 or "detects" anything; the direction is **S3 → SQS
> (push)**. (Separately, the *worker* then **polls** SQS to pull that message —
> don't conflate the two: S3 pushes *in*, the consumer polls *out*.)

> **Gotcha — the first message is an `s3:TestEvent`, not a real event.** The
> instant you attach an S3 event notification to a queue, **S3 sends a one-time
> test message** to verify it can deliver:
> ```json
> { "Service": "Amazon S3", "Event": "s3:TestEvent", "Bucket": "...", ... }
> ```
> It has **no `Records` array** — so a consumer that blindly does
> `body['Records'][0]['s3']['object']['key']` will **`KeyError`/crash on its very
> first receive**. Handle it explicitly: if `body.get('Event') == 's3:TestEvent'`,
> just `DeleteMessage` and skip. (Real S3 object-create events *do* carry
> `Records` with the object key — which, note, is **URL-encoded**, so decode it
> with `urllib.parse.unquote_plus` before using it as an S3 key.)

## Standard vs FIFO (quick note)

| | **Standard** (this course) | **FIFO** |
| --- | --- | --- |
| Throughput | Nearly unlimited | Limited (but high) |
| Ordering | Best-effort, **not** guaranteed | **Strict order** preserved |
| Delivery | **At-least-once** (possible duplicates) | **Exactly-once** processing |

Use **Standard** for maximum throughput when occasional reordering/duplication is
tolerable (and consumers are idempotent). Use **FIFO** when order or
no-duplicates genuinely matters (e.g. financial transaction sequencing). This
course/project uses **Standard**.

## Where this shows up in projects

- **[[projects/video-streaming-app|Video Streaming Platform]]** — SQS is the
  **backbone of the event-driven pipeline**. An upload to the ingest S3 bucket
  produces a **transcode job** message; the **EC2 FFmpeg worker** consumes it,
  transcodes to HLS, and deletes the message. The **visibility timeout** must
  exceed transcoding time (long for video!) so a job isn't double-processed, and
  a **DLQ** catches un-transcodable files (corrupt/unsupported video) after N
  failures so one bad upload never jams the whole pipeline. This is exactly why
  upload, processing, and delivery scale and fail independently.
- **[[projects/photoshare-app|PhotoShare]]** — also uses an SQS DLQ in its
  hardened (Phase 2) build for failure handling.

## Exam-relevant notes

- SQS = managed queue for **decoupling** producers from consumers; async buffer
  between components so they scale/fail independently.
- **Visibility timeout** hides an in-flight message so it isn't processed twice;
  set it **> worst-case processing time**; message reappears if not deleted
  (built-in retry).
- **Standard = at-least-once** → design **idempotent** consumers. FIFO =
  exactly-once + strict ordering, lower throughput.
- **DLQ** via redrive policy + **`maxReceiveCount`** isolates poison messages
  after N failed receives, keeping the main queue flowing. Monitor its depth.
- Delete a message (`DeleteMessage`) only **after** successful processing — not on
  receive.
