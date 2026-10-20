---
title: S3 Core Concepts
type: note
domain: storage
date: 2026-10-19
source: Skill Builder course + own notes
tags:
  - aws
  - s3
  - storage
  - object-storage
---

# S3 Core Concepts

> Part of [[learning-plan/03-storage/03-storage|Storage]].
> Related: [[learning-plan/03-storage/network-filesystem|Network Filesystem]]
> (block vs object vs file) ·
> [[learning-plan/01-cloud-foundations/aws-is-services-over-hardware-via-api|The API is the only door in]]

Amazon S3 (Simple Storage Service) is AWS's effectively unlimited **object
storage** in the cloud. The mental shortcut is "a hard drive in the cloud," but
the important word is **object** — it does *not* work like your laptop's
filesystem, and that difference drives a lot of behaviour.

## The vocabulary

| Term | What it is | Analogy |
| --- | --- | --- |
| **Bucket** | The top-level container for objects | A drive / root folder (e.g. `C:`) |
| **Object** | The actual file stored (photo, log, video) + its metadata | The file itself |
| **Key** | The object's full name within the bucket (e.g. `photos/dog.jpg`) | The file's path |
| **Value** | The object's bytes (the content) | The file contents |

An object is really a **key → value** pair plus metadata. S3 is best thought of
as a giant key-value store for files, not a folder tree.

## Object storage ≠ a filesystem (the part that actually matters)

S3 stores objects in a **flat namespace**. Within a bucket there is **no real
hierarchy of folders** — every object just has a key, and the key happens to
contain slashes.

- `photos/dog.jpg` is **not** a file named `dog.jpg` inside a folder `photos/`.
  It is a single object whose *key is the whole string* `photos/dog.jpg`.
- The console *shows* `photos/` as if it were a folder — that's a **UI
  convenience**. It's grouping keys by common prefix, not navigating directories.
- So "folders" in S3 are really just **key prefixes**. There's no `mkdir`; a
  "folder" exists only because some object's key starts with that prefix.

> **Why this matters in practice:** listing is prefix-based, not
> directory-based (`aws s3 ls s3://bucket/photos/` filters keys by the
> `photos/` prefix). There's no "rename a folder" operation — renaming means
> copying every object to new keys and deleting the old ones. This flat model is
> exactly what lets S3 scale to effectively unlimited objects without a
> filesystem's directory bookkeeping.

See [[learning-plan/03-storage/network-filesystem|the block/object/file note]]
for how this contrasts with EBS (block) and EFS (a real network filesystem with
genuine directories).

## Global namespace — why bucket names are so picky

Every **bucket name must be globally unique across all AWS accounts in the
world** — not just unique within your account. You can't create a bucket named
`test` or `images` because someone, somewhere, already has it.

- **Why:** a bucket is addressable by a global DNS-style name
  (`<bucket>.s3.amazonaws.com`), so the name has to be unique across the whole
  service for that addressing to work.
- **Practical habit:** namespace your buckets with something you own —
  `mycompany-videos-raw-us-east-1`, a project prefix, or an account-id suffix —
  to avoid collisions and make ownership obvious.
- Object **keys**, by contrast, only need to be unique **within their bucket**.
  The global-uniqueness rule is a bucket-name thing only.

## Storage classes — tiers for hot vs. cold data

S3 isn't one-price-fits-all. **Storage classes** trade retrieval
speed/availability against storage cost, so you pay to match how often data is
actually accessed:

| Class | For | Cost tradeoff |
| --- | --- | --- |
| **S3 Standard** | Hot data accessed often | Highest storage cost, instant access |
| **S3 Standard-IA** (Infrequent Access) | Accessed rarely but needs to be instant when it is | Cheaper storage, **per-GB retrieval fee** |
| **S3 One Zone-IA** | Infrequent + re-creatable (stored in a single AZ) | Cheaper still, but no multi-AZ durability |
| **S3 Glacier Instant Retrieval** | Archive, but occasionally need it instantly | Cheap storage, instant retrieval |
| **S3 Glacier Flexible / Deep Archive** | Cold archives, rarely/never touched | Cheapest storage, retrieval takes minutes–hours |
| **S3 Intelligent-Tiering** | Unknown/changing access patterns | Auto-moves objects between tiers; small monitoring fee |

The two forces being balanced: **storage price per GB** (goes down as you get
colder) vs. **retrieval cost + latency** (goes up as you get colder). "Glacier is
cheap" is only true if you rarely read it — retrieval fees and delay are the
catch.

> **Lifecycle policies** automate this: e.g. keep objects in Standard for 30
> days, transition to Standard-IA, then to Glacier after 90, then expire
> (delete) after a year — so cost tracks the data's age without manual work.
> (Noted here as the natural next layer; detail it when the course covers it.)

## Durability vs. availability (quick distinction)

- **Durability** = will my data survive? S3 Standard is designed for
  *eleven nines* (99.999999999%) — it redundantly stores objects across multiple
  devices and AZs, so loss is extraordinarily unlikely.
- **Availability** = can I reach it right now? Slightly lower (e.g. ~99.9–99.99%
  depending on class). One-Zone-IA trades availability/AZ-redundancy for price.

Different questions — a class can be extremely durable while being less
available (Glacier: your data is safe, but you can't read it *instantly*).

## Where this shows up in projects

- **[[projects/video-streaming-app|Video Streaming Platform]]** — raw uploads
  land in an **ingest bucket**; transcoded HLS segments go to a **processed
  bucket**. Storage-class choice differs per bucket: raw source might move to
  IA/Glacier after processing (rarely re-read), while the HLS output served to
  viewers stays in Standard (hot).
- **[[projects/photoshare-app|PhotoShare]]** — image bucket with **Block All
  Public Access** on; objects served through the app, never directly from the
  bucket. (Access control / public-access blocking is its own topic — see that
  project for the pattern.)

## Exam-relevant notes

- S3 is **object storage**, flat namespace; "folders" are just **key prefixes**,
  not real directories.
- **Bucket names are globally unique**; object keys are unique only within a
  bucket.
- Match **storage class to access pattern**: Standard (hot) → IA (infrequent) →
  Glacier (archive); Intelligent-Tiering when the pattern is unknown.
- **Durability ≠ availability** — eleven nines of durability is about not losing
  data, not about instant reachability.
- Automate class transitions with **lifecycle policies**.
