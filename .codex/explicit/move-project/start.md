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

- **Child `.git` internals** — *detected*: any `root: true` nested project under the
  source that carries a `.git` is listed by path (a plain nested git repo without the
  `root: true` marker moves fine but is not enumerated).
- **Windows Task Scheduler** path registrations — a fixed *reminder*, not scanned for.
- **Cross-project textual references** in backlogs / memories / designs that mention
  the old path — a fixed *reminder*, not scanned for.

The detected `.git` set is itemized in the plan and final report; the two reminders
print unconditionally. The human resolves all three.

## Non-goal — cross-platform migration (RUL-028)

The re-slug operates in **one** path system. A WSL `/mnt/...` <-> native Windows
`D:\...` move is out of scope and **must not** be hardened for here; it fails safe
(unlinked at the destination, orphaned at the source, both reported by `/roots`).

## Guards

All path comparisons **fold case** (ASCII, matching the DB's `COLLATE NOCASE`) —
this drvfs mount is case-insensitive, so a case-variant of a path is the same
directory and must not slip a guard.

- **Containment:** dest must resolve **strictly inside the apex** (an egress dest is
  refused). Source must be strictly inside the apex and **not** the apex itself.
- **Visibility / framework:** a source or dest whose apex-relative path has any
  `_`-prefixed **or** `.`-prefixed component is refused — the underscore-invisible
  paths and the dot-prefixed framework internals (`.state`, `.codex`, …) are never
  moved.
- **Destination free:** dest must not exist; its parent must; dest must not be inside
  source.
- **Destination store free (registered):** a move is refused if a **registered**
  identity's transcript store already occupies the destination slug (a merge would
  destroy real session history — `relink()` refuses it anyway). An *unregistered*
  nested root's store collision is **not** a blocker — best-effort, reported (see the
  moves table).
- **Not in use (best-effort):** a real move is refused while a session file records a
  cwd inside the source tree **and** its PID is still running (`/proc`). This is a
  PID-heuristic, not a hard guarantee: a stale file whose PID was reused reads as
  live (false block), and a live session not represented by a running PID under the
  source is not seen (false clear). It catches the common case; it is not proof.

## Troubleshooting — a move denied with `EACCES`

A tree move fails with `Permission denied` (`EACCES`) when another process holds a
file **or a directory** under the source open — and **one locked descendant
directory blocks moving the whole subtree**, even though the source node itself is
free and no file is locked. On WSL the holder is almost always a **Windows** app
(an Explorer window, an editor/viewer, or Search indexing a file here), invisible
to Linux `/proc`.

The command **fails safe**: the atomic core rolls back (tree move + spine writes
reverted). Rollback is best-effort — if the *reverse* rename itself fails (a lock
appears on the destination), the command says so plainly (`rollback was INCOMPLETE`)
and names the paths to reconcile with `/roots`, rather than falsely claiming a clean
revert. On `EACCES`/`EPERM` it also runs a **locked-descendant scan**: on WSL it shells to a
PowerShell exclusive-open probe over the whole source subtree and prints the exact
locked path(s); off WSL it prints the portable explanation. Close the holder
(name it with Sysinternals `handle64.exe <folder>` or Process Explorer → Ctrl+F),
then re-run. The scan is best-effort and never itself raises.

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
   re-run with `--execute` (adding `--yes` after an explicit confirmation). Without
   `--yes`, `--execute` at a real terminal prompts for confirmation by requiring the
   operator to **type the destination path exactly**; off a terminal (or a mismatch)
   it refuses (exit 1) and moves nothing. (`--home` overrides `~` for hermetic tests
   only.)
4. On a real move the identity+tree+transcript step is atomic with **written
   rollback**, and the cold `os.rename` is **verified after the fact** (a 9p ghost —
   a rename that "succeeds" but leaves an unstattable dirent — trips the rollback
   rather than committing identity over a broken destination). The post-move reconcile
   (sessions, `cboot`, report) is best-effort and its failures are reported, never
   rolled back over a good move.
