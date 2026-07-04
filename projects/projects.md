---
title: Projects
type: moc
tags:
  - aws
  - project
---

# Projects

Working AWS-based projects that demonstrate production-relevant patterns
(IAM, VPC/networking, databases, compute, observability, failure handling) —
part of the [H2 2026 AWS OKR](../README.md).

Use [[templates/project-note|the project template]] for new entries.

## Index

- [[projects/photoshare-app|PhotoShare — Instagram-style photo sharing app]]

## Dataview: all projects

> [!tip] Requires the Dataview community plugin.

```dataview
TABLE status, services, date-started
FROM "projects"
WHERE type = "project"
SORT date-started DESC
```
