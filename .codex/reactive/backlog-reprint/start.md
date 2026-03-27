---
version: 1
trigger: "backlog item resolved or status changed"
reads:
  - "^/.state/work/backlog.md"
writes: []
---

# backlog-reprint

Reprints the current backlog when work item status changes. Provides visibility into the updated state after a resolution.

## When It Triggers

When a backlog item is marked as resolved, mitigated, or its severity changes.

## Procedure

1. Read `^/.state/work/backlog.md` (state gravity applies — reads from the nearest `root: true` context).
2. Print a formatted summary of remaining open items, grouped by priority.
3. If no items remain, note that the backlog is clear.
