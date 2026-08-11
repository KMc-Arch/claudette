---
version: 1
---

# Pauses

Session context snapshots for later resumption. Created by the `pause` command, read by `unpause`.

## Folder Structure

```
YYYYMMDD.NNN/         # NNN = zero-padded day ordinal (001, 002, …)
    context.md    # What we were doing, key decisions, open questions
    state.md      # Files viewed/modified, pending work, file inventory
```

`NNN` is the day's ordinal, zero-padded to 3 digits and assigned as MAX+1 of the
existing folders for that date — so names sort chronologically and a deleted
folder never causes a re-mint. Pauses are written atomically: `pause` builds the
snapshot in a `.tmp-YYYYMMDD.NNN/` staging folder and renames it to the final
name only when complete. A `.tmp-*` folder is an interrupted pause, ignored by
`unpause`.

## Lifecycle

- Created by `pause`, never modified after creation
- Read by `unpause` to restore session context
- **Preserved** by bare `purge` (pauses are precious — they enable `/unpause`); cleaned
  only by `purge all`. The `start.md` here always survives.
