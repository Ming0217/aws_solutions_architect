---
title: Random Learnings
type: moc
tags:
  - aws
---

# Random Learnings

Ad-hoc things I picked up that don't belong to a specific module. Newest first.

Use [[templates/quick-note|the quick-note template]] for new entries.
Name files like `YYYY-MM-DD-short-title.md`.

## Dataview: all notes

> [!tip] Requires the Dataview community plugin.

```dataview
TABLE date, tags
FROM "notes"
WHERE type = "note"
SORT date DESC
```
