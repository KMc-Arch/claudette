---
version: 2
---

# ~outbox

A **message bus**, not a curated project folder. Handoffs **from this project to another actor** are
dropped here; the recipient reads its own subfolder and acts. Nothing is written across the fence into
the recipient's tree. `~`-prefixed folders are visible (not `.`-internal, not `_`-invisible) and never
git-tracked. Convention established 2026-08-09 (`~majel/~outbox`).

    ~outbox/<recipient>/<ITEM>.md          # one file per item (single file — the claim is an atomic rename)
    ~outbox/<recipient>/inflight/<ITEM>.md # claimed by the recipient; a crash leaves it here (orphan)

## Recipients

| recipient | who reads it |
|---|---|
| `hb` | Heartbeat — the nightly unattended runner (`^/^/.hb-heartbeat/`). **Only approved items go here.** |
| `<project-slug>` | a sibling project's session picks it up on its next boot |

## `hb` items

**Do not hand-author them — run `/hb-send`**, the planner that vets an item for *definitional
solvency* and writes it via the deterministic `hb.py send` writer (the single owner of the format).
The canonical item schema — every field, the structural (`write_scope`/`write_forbid`) vs advisory
(`read_scope`/`read_forbid`) vs decision (`autonomy`/`forbid`/`pre_auth`) tiers, and how the runner
consumes them — lives in ONE place: `^/^/.hb-heartbeat/spec.md` (§10.7) and the command at
`^/^/.codex/explicit/hb-send/start.md`. This bus folder does not restate it (so it can never drift).
