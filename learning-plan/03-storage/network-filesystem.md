---
title: Network Filesystem
type: note
domain: storage
date: 2026-06-11
source: Own notes
tags:
  - aws
  - storage
  - efs
  - fsx
  - nfs
---

# Network Filesystem

> Part of [[learning-plan/03-storage/03-storage|Storage]].

A network filesystem lets **multiple computers read and write the same files over a
network**, as if those files were on their own local disk — but they actually live on a
separate server (or managed service).

## The core idea

Normally a disk is attached to one machine, and only that machine uses it. A network
filesystem breaks that 1:1 link: the files sit on a central server, and many client
machines **mount** it over the network. Once mounted it behaves like a normal folder
(`cd` in, open/save files) — except the bytes travel over the network to the shared
server. Many clients can access the same files at the same time.

## Block vs object vs file storage

| Type | AWS example | What it is | Shared? |
| --- | --- | --- | --- |
| Block | EBS | Raw virtual disk attached to one VM; you format/mount it | No (one VM) |
| Object | S3 | Whole objects via REST API; no filesystem semantics | Via API |
| File / network filesystem | EFS | Real filesystem (directories + files) over the network | Yes (many machines) |

## Common protocols

- **NFS** (Network File System) — classic in the Linux/Unix world.
- **SMB/CIFS** — common in Windows environments.

## Why / where you'd use one

When several servers need to **share the same files**. Classic case: a fleet of web
servers behind a load balancer that must all serve the same uploaded images/content —
put the files on a shared network filesystem so every server sees the same data, with no
copies to sync.

## On AWS

- **Amazon EFS** — managed NFS filesystem for Linux; elastic (auto grows/shrinks),
  mountable by many EC2 instances, Lambda, and containers across Availability Zones.
- **Amazon FSx** — managed file systems for specific needs, e.g. FSx for Windows File
  Server (SMB) and FSx for Lustre (high-performance computing).

The appeal: higher abstraction (managed, no file server to run) **plus** shared access —
which is why the requirements checklist asks whether you need object, block, or file
storage, "or a combination."
