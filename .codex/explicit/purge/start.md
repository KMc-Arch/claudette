---
version: 3
short-desc: "Clean transient state; purge all is DESTRUCTIVE (requires confirmation)"
runtime: python
reads:
  - "^/.state/"
  - "^/.claude/"
writes:
  - "^/.state/"
  - "^/.claude/"
---

# purge

Clean transient state. Removes session artifacts, generated files, and optionally high-value state files.

## Usage

`purge` — clean transient artifacts
`purge <project>` — clean a child project's transient state
`purge all` — full reset including memory and work (CONFIRMED HOLD)

## Default Scope (no arguments)

Removes transient state that accumulates during sessions:
- `.claude/` files (`.jsonl`, `.md`) — preserves `settings*.json` and `_`-prefixed items
- `.claude/skills/` and `.claude/agents/` (generated shims — regenerated at next boot)
- `.state/prefs-resolved.json` (regenerated at next boot)
- `.state/tests/` transient outputs (boot, compliance logs — NOT audits)
- `.state/traces/` session traces
- `.state/pauses/` session context snapshots
- User-level `~/.claude/projects/<hash>/` footprint (external auto-memory)

## `purge all`

Everything in default scope, plus:
- `.state/memory/` files (user profile, decisions, state abstract)
- `.state/work/` files (backlog, platform notes, architecture debt)
- `.state/plans/` implementation plans
- `.state/bundles/` portable project snapshots

**This is destructive.** Requires CONFIRMED HOLD — single user confirmation before execution.

## What Is Never Purged

- `.codex/` — the framework definition, never cleaned by purge
- `.state/tests/audits/` — immutable records, never deleted by automated processes
- `start.md` files — structural manifests, protected in all scopes
- `_`-prefixed items — invisible by convention, always skipped

## Scoped to Child Project

When targeting a child project (`purge <project>`), only that project's `.state/` and `.claude/` are cleaned. The parent's state is untouched. State gravity applies — the purge targets the project's own paths, not the parent's.

### Nested Children (Groups)

`purge <project>` only reaches direct children of `^`. Children nested inside groups (e.g., `Services/MyProject/`) must be purged from a session rooted at the group level, where `^` = the group. This is consistent with state gravity — each group owns its children.

## Execution

```
python .codex/explicit/purge/purge.py [default|all|<project>] --project-root ^ [--dry-run] [--confirm]
```

1. Determine scope: default, all, or child project.
2. If `purge all`, warn that `.state/memory/`, `work/`, `plans/`, and `bundles/` will be wiped and get explicit confirmation.
3. Run `purge.py` with appropriate flags (`--dry-run` to preview, `--confirm` to skip interactive prompt).
4. Report what was removed.
