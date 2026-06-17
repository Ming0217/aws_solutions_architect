---
title: Stateless Compute + Shared State (WordPress on AWS)
type: note
domain: architecting
date: 2026-06-11
source: "Book: Amazon Web Services in Action (WordPress migration example)"
tags:
  - aws
  - architecting
  - high-availability
  - stateless
  - rds
  - efs
---

# Stateless Compute + Shared State (WordPress on AWS)

> Part of [[learning-plan/10-architecting/10-architecting|Architecting & Best Practices]].
> Related: [[learning-plan/03-storage/network-filesystem|Network Filesystem]]

## The question

In the WordPress-on-AWS example, why two storage solutions — **RDS for MySQL** *and*
**EFS** (network filesystem)? It looks redundant, but they store **different kinds of
data** for **different jobs**.

## Two stores, two jobs

| Store | Holds | Why it fits |
| --- | --- | --- |
| **RDS (MySQL)** | Structured/relational data: posts, pages, comments, users, settings | Queryable via SQL ("get post #42 and its comments") — what a relational DB is for |
| **EFS (files)** | The PHP app files, themes, plugins, and **user uploads** (e.g. article images) | Just files in folders — not database rows |

WordPress was built to use **both** a database and a local filesystem; the migration
keeps that split, mapping each to the right AWS service.

Why not one store?
- Storing images as blobs in MySQL is an anti-pattern — bloats the DB, slows queries,
  makes backups huge. DBs are tuned for structured queries, not serving big binaries.
- You can't put a relational DB "in a filesystem" usefully — you'd lose the querying
  that makes WordPress work.

Right tool for the job: **relational data → RDS, files → EFS.**

## The real lesson: keep state OFF the web servers

The setup has **two EC2 instances** behind a load balancer. Ask: where do uploaded images
go?

- If each instance used its **own local disk** (EBS), an image uploaded via instance A
  wouldn't exist on instance B → the next request (routed to B) shows a broken image. If
  an instance failed and was replaced, its uploads would be lost.
- **EFS fixes this**: a *shared* filesystem mounted by both instances, so any upload is
  instantly visible to all and survives any single instance failing.
- The database has the same need — both instances must read/write the same posts — which
  is why it's a shared **RDS** database, not MySQL installed on each VM.

## The pattern

**Stateless compute + shared state services.** Keep state off the individual web servers
so they become interchangeable; the load balancer can treat them as a pool and replace
failures freely. The actual state lives in shared, highly available services:

- Relational data → **RDS**
- Files → **EFS**

This is one of the most important HA patterns on AWS: stateless, replaceable compute in
front; durable, shared, highly available state behind.
