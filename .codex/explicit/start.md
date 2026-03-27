---
version: 1
---

# Explicit

Explicit entries are user-invoked commands, protocols, and procedures. They load lazily: folder names are listed at boot, content is read only on invocation.

## Invocation

Users invoke explicit entries by name or description. Each entry folder contains a `start.md` describing what it does, its parameters, and when to use it.

## `short-desc` Frontmatter Key

Every explicit entry should declare `short-desc:` in its `start.md` frontmatter — a one-line summary displayed in the `/command` menu. `cboot.py` reads this key when generating skill shims. The body's first paragraph serves as the long description, read on invocation. Keep `short-desc` under ~70 characters; flag destructive commands clearly (e.g., "DESTRUCTIVE ...").

## Platform Correlation: Explicit Entries ARE Skills

Claude Code's `.claude/skills/` directory contains generated shims — one-line redirects pointing back to these entries. The codex entry is authoritative; the shim is derived.

Slash-command registration is handled by `codex-register` at boot. Do not write skill definitions directly in `.claude/skills/`.

## Output Directories

Before writing output, ensure the target directory from the module's `writes:` declaration exists. Create it with `mkdir -p` if needed. Do not ask the user — output directories are infrastructure, not a decision.

## Isolation

Any explicit entry may declare `isolation: subagent` in its `start.md` frontmatter to run in its own context window. When isolated, the entry's `reads:`/`writes:` declarations constrain what the sub-agent can access. See `.codex/start.md` for the full I/O boundary spec.
