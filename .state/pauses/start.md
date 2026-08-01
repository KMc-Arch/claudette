---
version: 1
---

# Pauses

Session context snapshots for later resumption. Created by the `pause` command, read by `unpause`.

## Folder Structure

```
YYYYMMDD.N/
    context.md    # What we were doing, key decisions, open questions
    state.md      # Files viewed/modified, pending work, file inventory
```

N auto-increments for multiple pauses on the same day.

## Lifecycle

- Created by `pause`, never modified after creation
- Read by `unpause` to restore session context
- **Preserved** by bare `purge` (pauses are precious — they enable `/resume`); cleaned
  only by `purge all`. The `start.md` here always survives.
