---
version: 1
---

# Bundles

Point-in-time portable snapshots of child projects. Each bundle is a self-contained copy with all parent references resolved — it can operate independently without the parent claudette2 instance.

## Folder Structure

```
YYYYMMDD-HHMM-<project>/
    <full project tree with resolved references>
```

## Lifecycle

- Created by the `bundle` explicit command
- Each bundle is a snapshot, not a sync mechanism
- Bundles are never modified after creation
- Old bundles can be deleted manually (purge preserves bundles by default)

## What's Included

- Full project source tree
- Inlined `.codex/` (resolved from parent)
- `.state/memory/` and `.state/work/` (project knowledge)

## What's Excluded

- `.state/traces/` (session-specific, not portable)
- `.claude/` transient artifacts (session state)
