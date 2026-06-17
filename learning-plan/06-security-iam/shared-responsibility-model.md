---
title: AWS Shared Responsibility Model
type: note
domain: security-iam
date: 2026-06-11
source: Skill Builder course slide (AWS Shared Responsibility Model)
tags:
  - aws
  - security
  - shared-responsibility
  - compliance
  - cloud-foundations
---

# AWS Shared Responsibility Model

> Part of [[learning-plan/06-security-iam/06-security-iam|Security, Identity & IAM]].
> Related: [[learning-plan/01-cloud-foundations/01-cloud-foundations|Cloud Foundations]]

Security and compliance are a **shared responsibility** between AWS and the customer.
The dividing line is simple to remember:

- **AWS → security _OF_ the cloud**
- **Customer → security _IN_ the cloud**

## AWS: security OF the cloud

AWS is responsible for protecting the infrastructure that runs all the services:

- **Software** powering the managed services
- **Compute, Storage, Database, Networking** services
- **Hardware and the AWS Global Infrastructure**, including **Regions**,
  **Availability Zones**, and **Edge locations**

In short: the physical facilities, hardware, and the foundational service software.

## Customer: security IN the cloud

The customer is responsible for what they put in and configure on top of AWS:

- **Customer data**
- **Platform, applications, and identity & access management (IAM)**
- **Operating systems, network, and firewall configuration**
- Data protection:
  - **Client-side data encryption and data integrity authentication**
  - **Server-side encryption** (file system and data)
  - **Networking traffic protection** (encryption in transit, etc.)

In short: your data, your access controls, your OS/app configuration, and how you
encrypt and protect traffic.

## Why it matters

- **The boundary shifts with the service model.** The more managed the service, the
  more AWS handles. With EC2 (IaaS) you patch the OS; with a managed service like
  Lambda or S3, AWS handles more of the stack and your responsibility narrows toward
  data and access configuration.
- **Misconfiguration is the customer's responsibility.** Classic example: a publicly
  exposed S3 bucket is a *customer*-side mistake, not an AWS failure — access control
  is "in the cloud."
- **It frames every security conversation.** Knowing which side owns a control tells
  you where to apply IAM policies, encryption, and patching.

## Quick recall

| Question | Answer |
| --- | --- |
| Who secures the data centers and hardware? | AWS |
| Who patches the guest OS on an EC2 instance? | Customer |
| Who manages IAM users, roles, and policies? | Customer |
| Who secures the global infrastructure (Regions/AZs)? | AWS |
| Who configures encryption of customer data? | Customer |
