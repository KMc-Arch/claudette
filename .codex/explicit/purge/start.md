---
version: 9
short-desc: "Clean transient state; purge all is a nuclear reset (CONFIRMED HOLD)"
runtime: python
reads:
  - "^/"                            # project-root top level — straggler detection (iterdir)
  - "^/.state/"
  - "^/.claude/"
  - "^/.tmp/"
  - "^/.codex/reactive/agent-ownership/"  # loads agent_ownership.py to gate .claude/agents/ deletions
  - "~/.claude/projects/<slug>/"   # external transcript store — resolved under `purge all`
writes:
  - "^/.state/"
  - "^/.claude/"
  - "^/.tmp/"
  - "~/.claude/projects/<slug>/"   # external transcript store — `purge all` only, outside ^
---

# purge

Clean transient state. Purge operates on an explicit **allowlist** of categories —
nothing outside the list is ever eligible, in any scope. Scope levels differ only
in which allowlisted categories are in play and whether recency-sparing applies.

## Usage

`purge` — quotidian tidy (safe, regenerable state only)
`purge <project>` — bare rules aimed at a child project
`purge all` — nuclear reset, including transcripts and project brains (CONFIRMED HOLD)

> `all` triggers the nuclear scope **only as a standalone token**. "all" inside a
> phrase — "purge all of the sandbox", "purge all the children" — is natural
> language, not the argument: resolve the real target, and if it is genuinely
> ambiguous, ask before acting.

## Bare `purge` (no arguments)

Removes only regenerable / genuinely-transient state, and prunes keep-recent dirs:

- `.claude/` files (`.jsonl`, `.md`) — preserves `settings*.json` and `_`-prefixed
- `.claude/skills/` (generated shims — regenerated at next boot)
- `.claude/agents/` — **only the files cboot currently claims**. Ownership is a lookup of each file's path against the current `agent_registry` rows in `.state/roots.db`, never a guess from the file's contents: nothing here opens or decodes a candidate file. A hand-authored agent is preserved and reported, whatever it contains — including one that carries a marker-shaped line. A file the registry DOES claim is also preserved if its marker is gone or altered: cboot refuses to overwrite such a file because a human has edited it, and purge deleting what cboot preserves would be the two tools disagreeing. Reading the marker there only ever prevents a deletion, so ownership is still decided by the registry alone. If the registry is missing or unreadable, cboot owns **nothing** and the whole directory is preserved. `<name>.md.tmp` staging leftovers are always removed. The rule is shared with cboot, in `.codex/reactive/agent-ownership` — purge does not carry its own copy.
- `.state/prefs-resolved.json` (regenerated at next boot)
- `.state/tests/` transient outputs (compliance logs etc. — NOT audits, NOT boot)
- **Keep-recent**, pruned to the newest `KEEP_RECENT` (5) of **each kind**:
  `.state/traces/` (`*.trace`) and `.state/tests/boot/` (`*-bootstrap.md` and
  `*-refresh-*.md`, pruned independently so each keeps its own newest 5). A
  `_`-prefixed match is excluded from the candidate list — it never occupies a keep slot.

Bare purge **keeps** everything precious — transcripts, pauses, memory, work,
plans, bundles, and loose `.tmp/` buffers are untouched.

## `purge all`

A **nuclear reset**. Everything on the allowlist, with **no recency sparing**:

- Everything bare purge deletes, but keep-recent dirs are **wiped entirely** (not pruned)
- **Precious / session history**: transcripts (`~/.claude/projects/<slug>/`) and
  `.state/pauses/` contents
- **High-value / project brains**: `.state/memory/`, `work/`, `plans/`, `bundles/`
- The **entire `.tmp/`** — loose buffers, `.tmp/sandbox/` rigs, and every other
  subdir — cleared (only `.tmp/start.md` and `_`-prefixed items survive)

**This is destructive and cannot be undone.** It is a CONFIRMED HOLD: state the
full blast radius back to the user and get a single confirmation before **any**
deletion runs. The confirmation gates the *entire* run, not just the incremental
high-value removals. Because a misread of a phrase-"all" would trigger this same
loud confirmation, the announcement is itself the disambiguation backstop.

`purge all` is a deliberate, quiet-moment operation (typically prepping something
to ship, not a working copy). Explicit confirmation *is* its guard, which is why
there is no `.tmp/` freshness window — nuclear means nuclear, no exceptions
*within the allowlist*.

> **Slug caveat (inherited).** The transcript store is located by slugifying the
> resolved project path exactly as Claude Code does — every non-alphanumeric character
> becomes `-`. That mapping is **not injective**: two roots differing only in
> punctuation (e.g. `…/~majel` and a hypothetical `…/.majel`) resolve to the *same*
> store. Purge targets exactly the store Claude Code associates with this project —
> which, for such a collision, is the shared one. This is faithful to Claude Code's own
> behavior (colliding projects genuinely share a store); an injective encoding would
> compute a slug Claude Code never created and thus never find the store at all — the
> original transcript-skipping bug. Removal stays confined to `~/.claude/projects/` and
> refuses symlinked footprints. If no store resolves, `purge all` warns (fail-loud).

## Detection (report-only)

Purge **reports but never deletes**:

- `.tmp/sandbox/` rigs — **bare and child scope only**. Sandbox can hold live work,
  so each rig is surfaced and the user decides what to clear. Under `purge all` the
  sandbox is **cleared outright** (see above) rather than reported.
- Transient-looking files (`*.bak`, `*msg.txt`, `*-prbody.md`, …) found *outside*
  `.tmp/` at the project root — straggler detection for the transient-gravity
  convention. Report-only in **every** scope, `purge all` included.

## What Is Never Purged (the hard floor)

Never on any allowlist, in any scope — also guarded by separate boundaries:

- `.codex/` — the framework definition
- `.state/tests/audits/` — immutable records (audit-immutability boundary)
- `.state/roots.db` — the durable registry. It stopped being a rebuildable cache when it took on `agent_optin` (decisions a human made once) and `agent_registry` (the claims every generated agent file depends on). Deleting it would orphan them all, and would leave purge permanently unable to tell cboot's files from hand-authored ones.
- `start.md` files — structural manifests (includes `.tmp/start.md`)
- `_`-prefixed items — invisible to every op: not listed, not counted toward a
  keep-recent window, not recursed into. Protected at **every depth** — a directory
  that holds one is emptied of deletables but survives, so a nested `_secret.md` or a
  buried `start.md` is never destroyed by a blind recursive delete.
- **Symlinks** — never followed and never deleted, at any depth. A symlinked file or
  directory is treated as protected, so `purge all` never reaches its target *through*
  the link (a dir holding a symlink survives, holding the link). This covers a
  symlinked `.claude/agents/` as much as a symlinked `skills/`: the per-file sweep
  checks the directory itself before iterating it.

## Scoped to Child Project

`purge <project>` applies the **bare** rules to a child's own `.claude/` and
`.state/`. The parent's state is untouched; state gravity targets the child's own
paths. Precious and high-value categories are never touched in child scope (there
is no `all` for a child — nuke a child by opening a session rooted there, or via
`bundle` for a clean shippable copy).

### Nested Children (Groups)

A child is addressed by its path relative to `^`. A **direct** child is the common
case (`purge TestBench`); a group-nested child is also reachable by a relative path
(`purge Services/MyProject`) — `purge_child` accepts any target that stays inside `^`
and applies the bare rules there. By convention each group **owns its children**, so
the cleaner workflow for a nested child is a session rooted at the group (`^` = the
group). Prefer that especially when you want the post-run rematerialize (step 5) to
resolve cleanly — `cboot --project` resolves relative to the apex, so a nested child
must be given by absolute path (see Execution step 5).

## Execution

```
python .codex/explicit/purge/purge.py [default|all|<project>] --project-root ^ [--dry-run] [--confirm]
```

1. Determine scope: default (bare), all (nuclear), or child project.
2. If `purge all`, state the full blast radius (transcripts, pauses, memory, work,
   plans, bundles, and the entire `.tmp/` including sandbox rigs) and get explicit
   confirmation before running.
3. Run `purge.py` with appropriate flags (`--dry-run` to preview, `--confirm` to
   skip the interactive prompt once the user has confirmed).
4. Report what was removed and what was detected-but-kept.
5. **Rematerialize** (skip entirely on `--dry-run`). Purge deletes regenerable
   boot artifacts — `.claude/skills/`, cboot's own `.claude/agents/` files,
   `prefs-resolved.json` —
   so immediately regenerate them rather than leaving them missing until the next
   boot. This restores only *generated* artifacts; user content removed by
   `purge all` (memory, work, …) is intentionally not restored.
   - Apex scope (`default`/`all`): `python cboot.py --materialize-only`. This runs a
     full apex materialization (all children re-propagated, every repo's git hooks
     rewritten) and writes one fresh boot report + trace marker — so after `purge all`
     the wiped `tests/boot/` and `traces/` hold a single current entry rather than
     sitting empty. That breadth is idempotent and intended; it is deliberately not
     narrowed for a nuclear, quiet-moment operation.
   - Child scope (`purge <project>`): `python cboot.py --project <ABSOLUTE path to the
     purged child>`. Pass the resolved absolute path, not a bare name — `cboot`
     resolves `--project` relative to the **apex**, not the current `^`, so a
     group-nested child given by bare name would not be found. Skip this step entirely
     when the child is not `root: true`: it has no generated shims/settings to restore
     and `cboot --project` will (correctly) reject it.

   Both regenerate shims/settings without launching Claude.
