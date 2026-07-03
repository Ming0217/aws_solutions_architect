---
title: RDS Core Concepts
type: note
domain: databases
date: 2026-07-03
source: Skill Builder course + own notes
tags:
  - aws
  - rds
  - databases
---

# RDS Core Concepts

> Part of [[learning-plan/05-databases/05-databases|Databases]].

## The simple version

- **DB Instance** — the actual virtual environment (server) where your database
  software runs.
- **Engine** — the flavor of database software you're using (MySQL, PostgreSQL,
  MariaDB, Oracle, SQL Server, or AWS's own Aurora).
- **Master Username/Password** — the "root" admin credentials for the database
  itself.
- **Multi-AZ** — a feature that puts a standby copy of your DB in a different
  physical location (Availability Zone).

## DB Instance — managed, not administered

- Unlike EC2, you don't SSH in or manage the OS. RDS is **managed** — you only
  interact with the database engine itself (via normal DB connections/clients)
  and with the RDS API for admin tasks like resizing or taking snapshots.

## Master Username/Password — native to the engine, not IAM

- This credential authenticates you **into the database engine itself** (like a
  MySQL root login) — completely separate from IAM. It's not something an IAM
  policy can grant or restrict; IAM only controls who can call the **RDS API**
  (create/modify/delete the instance, etc.), not who can log into the database
  with these credentials.

> **Lab note:** losing the master password in a **locked-down lab sandbox**
> often does mean deleting the DB and starting over, because the lab account
> usually lacks `rds:ModifyDBInstance` permission. In a normal account with that
> permission, you can just reset the master password via the console/CLI —
> no need to delete anything. Don't carry the "just delete it" takeaway into
> the exam.

## Multi-AZ vs Read Replica — the distinction people conflate

Both involve a second copy of your database, but for opposite reasons:

| | Multi-AZ (standby) | Read Replica |
| --- | --- | --- |
| Purpose | High availability / automatic failover | Scaling read traffic |
| Readable? | **No** — sits idle until failover | **Yes** — serves read queries |
| Replication | Synchronous | Asynchronous |
| Becomes primary? | Yes, automatically on failure | Only if manually promoted |

> **Rule of thumb:** Multi-AZ = insurance policy (never touched unless disaster
> strikes). Read Replica = extra capacity (actively used every day).

## Exam-relevant notes

- RDS is managed — no OS/SSH access, only engine-level connections + the RDS
  API.
- Master password is a **database-engine credential**, not an IAM concept.
- Losing the master password ≠ always having to delete the DB — that's a
  lab-sandbox limitation, not a real-account requirement.
- **Multi-AZ standby is not readable**; **Read Replicas are readable** — this
  distinction shows up constantly in exam scenario questions ("how do I scale
  reads?" → Read Replica, not Multi-AZ).

## Questions / things to revisit

-
