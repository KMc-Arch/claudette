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

`NNN` is the day's ordinal, zero-padded to 3 digits and assigned as **MAX+1**
over the **completed** folders for that date (each ordinal parsed as an integer,
so legacy unpadded `YYYYMMDD.N` names still count) — a deleted or interrupted
folder never causes a re-mint that overwrites a survivor. `unpause` sorts by
numeric ordinal, so the padding is cosmetic, not load-bearing. Pauses are written
atomically: `pause` builds the snapshot in a `.tmp-YYYYMMDD.NNN/` staging folder
and renames it to the final name only when both files are written; a folder is a
valid pause only once it is final-named and holds both `context.md` and
`state.md`. A `.tmp-*` folder is an interrupted pause — ignored by `unpause`, and
reaped by the next `pause` for that day.

## Lifecycle

- Created by `pause`, never modified after creation
- Read by `unpause` to restore session context
- **Preserved** by bare `purge` (pauses are precious — they enable `/unpause`); cleaned
  only by `purge all`. The `start.md` here always survives.
