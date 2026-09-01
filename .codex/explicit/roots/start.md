---
version: 1
short-desc: "Reconfigure the root inventory (agent on/off, rename, relink)"
runtime: python
reads:
  - "^/.state/roots.db"                     # the durable registry — drift is read from the tables
  - "^/.claude/agents/"                     # divergence check (agent-file markers)
  - "^/.codex/reactive/roots-register/"     # the SOLE writer module — every mutation dispatches here
  - "^/.codex/reactive/agent-ownership/"    # marker_matches / name derivation / reserved names
  - "^/.codex/reactive/transcript-slug/"    # relink re-slugs the transcript store (via the writer)
  - "^/.codex/reactive/sqlite/"             # the house connection factory (roots.py loads it directly)
writes:
  - "^/.state/roots.db"                     # identity/claim rows — ONLY through roots-register
  - "^/.claude/agents/"                     # sweeps an agent file a disable/rename just un-claimed
  - "~/.claude/projects/<slug>/"            # relink renames the transcript store (outside ^, via os.rename in the module)
---

# roots

Reconfigure the **root inventory** — the `root_id` identity spine, the @name
claims, and the opt-in decisions in `^/.state/roots.db`. `/roots` is the
out-of-band **complement of boot's first-touch prompt**: boot detects a new root
and asks once; `/roots` lets a human revisit that answer at any quiet moment.

Named `/roots` (**not** `/status` — `/status` is a Claude Code built-in). It
operates on the root inventory, so the name names that.

**Apex-only.** `.claude/agents/` is never propagated to a child, so a child has
no addressable-agent inventory to reconfigure.

## What it is

A **thin wrapper** over the shared writer module
(`^/.codex/reactive/roots-register/roots_register.py`) — the SOLE writer of
`roots_register` / `agent_registry` / `agent_optin` identity rows. `/roots`
carries **no identity/claim write SQL of its own**; every mutation dispatches to a
module function (`mint` / `accept` / `close_claim` / `rename_claim` / `relink` /
`deconflict`). Boot calls the same module, and `/move-project` will once it lands
on this branch — three copies of claim-mutation is exactly the divergence bug the
shared module prevents. (`/move-project` will import the module's `relink()`
**directly**, not this command.)

## Drift surface (read-only, computed from the tables — never a re-walk)

`/roots` reports three classes, read straight from `roots.db` (the `roots` walk
cache from the last boot, the identity spine, the claims):

- **unlinked** — `roots` rows with `canonical_id IS NULL`: a walked directory the
  mint never canonicalized (a dir created after the day-one mint, not yet decided).
- **orphaned** — CURRENT `roots_register` rows whose `rel_path` is absent from the
  last walk (COLLATE NOCASE): the directory the identity points at is gone — a
  candidate for **relink** if it moved.
- **divergence** — CURRENT `agent_registry` claims whose on-disk agent file no
  longer carries our marker for its current rel — or for a *past* rel of that same
  identity (`agent_ownership.marker_is_current_or_past_rel`, the move-aware test, so
  a relinked-but-unprojected file is recognised as ours and NOT flagged).
  **Report-only, always** — a diverged file is never rewritten or deleted, because a
  human has been in it.

## Reconfigure operations

Each **changes an answer already made** and dispatches to the writer module:

- **turn an agent OFF** — `close_claim(root_id, 'opted-out')` closes the claim and
  flips the opt-in decision to disabled; the now-un-claimed agent file is swept
  (guarded by the marker — a hand-edited file is left in place).
- **turn a declined root ON** — records the enabled decision via `accept`, then
  tells you to run `python cboot.py --materialize-only`. This is the deliberate
  projection choice: `/roots` records only the decision and leaves the agent
  **file** to boot, exactly the split boot itself uses (first-touch `accept`
  records the YES; the projection pass derives the @name, de-conflicts against the
  whole live agents directory, opens the claim, and writes the file). Reproducing
  that de-confliction inside a thin command would duplicate the projection pass.
- **rename an @name** — `deconflict` re-checks reserved/taken (grandfathers win),
  then `rename_claim` closes+reopens under the new name (same `root_id`). The old
  file is swept; the next materialize projects the renamed one.
- **relink an orphaned identity** — `relink(root_id, new_rel_path)` versions the
  spine under the **same** `root_id` and re-slugs the transcript store; the claim
  is untouched (a live project's agent survives the move). The new `rel_path` is
  chosen from the unlinked candidates (an unlinked walked root is the likely move
  target).
- **canonicalize an unlinked root** — `mint(rel_path)` allocates a fresh
  `root_id`. This is the "it's a new project" half of re-canonicalizing a
  first-touch mis-call; the "it's the moved-here old project" half is **relink** of
  the orphaned identity onto that same `rel_path`.

## TTY discipline

An interactive mutation requires **both** `stdin` and `stdout` to be a real
terminal (mirroring cboot's `_interactive`). A **non-TTY** invocation (a hook, a
script) prints the drift report and exits 0, **mutating nothing**.

## Execution

```
python .codex/explicit/roots/roots.py [--project-root ^]
```

1. Claude reads this `start.md`, then runs `roots.py` with `--project-root` set to
   the apex.
2. At a terminal, `/roots` prints the drift report and offers the reconfigure
   menu. Off a terminal, it prints the drift report and stops.
3. A relink or a re-enable/rename that changed the agent-file inventory is
   followed by `python cboot.py --materialize-only` to reconcile the files (the
   command says so when it applies).
