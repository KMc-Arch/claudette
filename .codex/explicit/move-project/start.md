---
version: 1
short-desc: "Move a child project within the apex, carrying identity + transcripts + sessions"
runtime: python
reads:
  - "^/.state/roots.db"                     # the identity spine + claims — who moves
  - "^/"                                     # the project tree being moved (FS walk for child roots)
  - "~/.claude/projects/<slug>/"            # transcript stores that follow the move
  - "~/.claude/sessions/*.json"             # paused-session cwd rewrite + active-session guard
  - "^/.codex/reactive/roots-register/"     # the SOLE writer — relink() dispatches here
  - "^/.codex/reactive/transcript-slug/"    # the store-slug derivation (collision preflight)
  - "^/.codex/reactive/sqlite/"             # the house write-connection factory
writes:
  - "^/.state/roots.db"                     # spine rows — ONLY through roots-register.relink()
  - "^/"                                     # the project tree — os.rename source -> dest
  - "~/.claude/projects/<slug>/"            # transcript stores re-slugged to follow (via relink / best-effort)
  - "~/.claude/sessions/*.json"             # cwd field rewritten for paused sessions under the move
---

# move-project

Relocate a **child project** (and every root project nested inside it) to a new
location **within the apex**, carrying all of its Claude-side state so nothing is
orphaned: the `root_id` **identity spine** (preserved — the same id, versioned to
the new path), its **transcript history**, and the **working directory** of any
paused session that lived inside it.

The **intentional-move complement of `/roots` relink**. `/roots` *recovers* from a
move already done out of band (the dir is gone, the identity orphaned); `/move-project`
*performs* the move and reconciles everything in one step.

**Apex-only.** The identity spine and the addressable-agent inventory live only at
the apex; a child has nothing to move identities in.

## What it is — a thin wrapper over the single writer

`/move-project` carries **no identity/claim write SQL of its own**. Every spine
mutation dispatches to `roots_register.relink()` — the SOLE writer of the identity
tables (boot and `/roots` call the same module). Three copies of claim-mutation is
exactly the divergence bug the shared module exists to prevent. This command
**orchestrates** already-built primitives; it adds the tree move, the session
rewrite, the reconcile, and the report around them.

Dependencies (all on `main`): `roots_register.relink()` (spine + transcript
re-slug, collision-refusing, savepoint-rolling-back), the shared `transcript-slug`
module, and `cboot --materialize-only` (reconcile agent files + inventory).

## CONFIRMED HOLD on execution

**Dry-run (a plan) is the default.** A real move mutates the filesystem, the
identity spine, and the transcript stores — so it requires **`--execute`** AND
either an interactive confirmation at a real terminal **or** `--yes`. Claude MUST
show the dry-run plan and get the user's confirmation before running `--execute`.
Building the command is not held; running a real move is.

## WAL discipline (a load-bearing constraint)

This command does **every** db read and write on **one** house write connection and
**never** opens an `immutable=1&mode=ro` reader. Those RO readers go blind to a
write-connection's un-checkpointed WAL commits (BL-46, mileqa round-4); by never
opening one here, a stale-ownership read is impossible **by construction**.

## What moves, and how

| Artifact | Action |
|---|---|
| Project tree (+ nested roots) | **cold `os.rename`** source -> dest (this mount ghosts hot-tree renames) |
| Identity of each nested root project | `relink(root_id, new_rel)` — spine versioned under the **same** `root_id`; the @name claim is untouched, so a live project's agent survives the move |
| Transcript store of each identity | re-slugged old->new by `relink()` (destination collision is **refused**, never clobbered) |
| Transcript store of an *unregistered* nested root | best-effort re-slug; reported — it re-canonicalizes at the new path on next boot |
| Paused-session `cwd` (`~/.claude/sessions/*.json`) | rewritten source-prefix -> dest-prefix |
| Agent files + walk inventory | reconciled by `cboot --materialize-only` (idempotent) |

## Report-only — never rewritten (RULED)

- **Child `.git` internals** (a nested project that is its own repo).
- **Windows Task Scheduler** path registrations.
- **Cross-project textual references** in backlogs / memories / designs that mention
  the old path.

These are surfaced in the plan and the final report; the human resolves them.

## Non-goal — cross-platform migration (RUL-028)

The re-slug operates in **one** path system. A WSL `/mnt/...` <-> native Windows
`D:\...` move is out of scope and **must not** be hardened for here; it fails safe
(unlinked at the destination, orphaned at the source, both reported by `/roots`).

## Guards

- **Containment:** dest must resolve **strictly inside the apex** (an egress dest is
  refused). Source must be strictly inside the apex and **not** the apex itself.
- **Visibility:** a `_`-prefixed source or dest is refused (those paths do not exist
  to Claude).
- **Destination free:** dest must not exist; its parent must; dest must not be inside
  source.
- **Not in use:** a real move is refused while any **live** session (a running PID)
  has its cwd inside the source tree.

## Execution

```
python .codex/explicit/move-project/move_project.py <source> <dest> \
       --project-root ^ [--execute] [--yes]
```

1. Claude reads this `start.md`, then runs the command with `<source>` and `<dest>`
   (each absolute or apex-relative) and `--project-root` set to the apex.
2. **Default is dry-run:** it prints the full plan (what moves, which identities
   relink, which stores follow, sessions to rewrite, report-only items, any
   blockers) and stops.
3. Claude relays the plan and **gets the user's confirmation**. Only then does it
   re-run with `--execute` (adding `--yes` after an explicit confirmation, or
   letting the terminal prompt).
4. On a real move the identity+tree+transcript step is atomic with **written
   rollback**; the post-move reconcile (sessions, `cboot`, report) is best-effort
   and its failures are reported, never rolled back over a good move.
