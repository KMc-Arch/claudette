---
version: 2
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
- User-level `~/.claude/projects/<hash>/` footprint (external auto-memory)

## `purge all`

Everything in default scope, plus:
- `.state/memory/` files (user profile, decisions, state abstract)
- `.state/work/` files (backlog, platform notes, architecture debt)

**This is destructive.** Requires CONFIRMED HOLD — single user confirmation before execution.

## What Is Never Purged

- `.codex/` — the framework definition, never cleaned by purge
- `.state/tests/audits/` — immutable records, never deleted by automated processes
- `.state/pauses/` — historical session context, preserved
- `.state/plans/` — implementation plans, preserved
- `.state/bundles/` — portable project snapshots, preserved

## Scoped to Child Project

When targeting a child project (`purge <project>`), only that project's `.state/` and `.claude/` are cleaned. The parent's state is untouched. State gravity applies — the purge targets the project's own paths, not the parent's.

## Execution

```
python .codex/explicit/purge/purge.py [default|all|<project>] --project-root ^ [--dry-run] [--confirm]
```

1. Determine scope: default, all, or child project.
2. If `purge all`, warn that `.state/memory/` and `.state/work/` will be wiped and get explicit confirmation.
3. Run `purge.py` with appropriate flags (`--dry-run` to preview, `--confirm` to skip interactive prompt).
4. Report what was removed.
