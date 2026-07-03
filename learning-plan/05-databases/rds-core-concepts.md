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

## Backups & Snapshots

- **Automatic backups** (if enabled) are **deleted when you delete the
  instance** — by default. They have a **retention period** (1–35 days) and
  include continuous transaction logs, which enables **point-in-time recovery
  (PITR)**: you can restore to *any second* within that window, not just a
  fixed moment. That continuous-log capability is the real value-add over
  manual snapshots.
- **Manual snapshots persist even after the DB is deleted** — indefinitely,
  until you delete them yourself. But they're **not** PITR — a snapshot only
  captures that one instant in time.
- **Two escape hatches at deletion time**, so losing automatic backups isn't
  unconditional: you can check **"Create final snapshot"** (one last manual-
  style snapshot before deleting) and/or **"Retain automated backups"** (keeps
  the automated backups around for their retention period even after the
  instance is gone).
- Both automated backups and manual snapshots restore by creating a **brand-new
  DB instance** — you can never restore "in place" onto the existing one.

> **Why this matters:** this is the crux of disaster recovery and data
> protection for RDS — knowing whether you're relying on a self-deleting
> default (automatic backups) or something that persists on its own (manual
> snapshots) determines whether your data actually survives an accidental
> instance deletion.

## Exam-relevant notes

- RDS is managed — no OS/SSH access, only engine-level connections + the RDS
  API.
- Master password is a **database-engine credential**, not an IAM concept.
- Losing the master password ≠ always having to delete the DB — that's a
  lab-sandbox limitation, not a real-account requirement.
- **Multi-AZ standby is not readable**; **Read Replicas are readable** — this
  distinction shows up constantly in exam scenario questions ("how do I scale
  reads?" → Read Replica, not Multi-AZ).
- **Automatic backups** enable point-in-time recovery but are deleted with the
  instance by default; **manual snapshots** persist indefinitely but are a
  fixed point in time, not PITR. Restoring either always creates a **new**
  DB instance.

## Questions / things to revisit

-
