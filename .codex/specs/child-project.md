# Child Project Spec

Minimum standard for child projects created under a claudette2 instance.

---

## Required Structure

```
<project>/
    CLAUDE.md                   # root: true, codex: ^/^/.codex
    .state/
        start.md                # references ^/^ for inherited definitions
        prefs.json              # project preference overrides (may be empty)
        memory/
            start.md
            decisions.md        # when project has its own design history
        work/
            start.md
            backlog.md          # project-specific work tracking
        tests/
            start.md
        traces/
            start.md
```

## CLAUDE.md Requirements

- Frontmatter MUST include `root: true`
- Frontmatter MUST include `codex: ^/^/.codex` to make inheritance explicit
- Body points to `.state/start.md` only (codex is inherited, not local)

## Codex Inheritance

- Child projects inherit `^/^/.codex` via Claude Code's ancestor walk — no duplication needed
- NO `.codex/` unless project-specific entries exist
- If a local `.codex/` exists, same-name entries REPLACE parent entries (innermost wins); non-colliding entries supplement
- See `.codex/start.md` codex override rule for details

## When to Add Local Codex Entries

A child project should add its own `.codex/` entries only when:
- It needs to override a parent behavior (e.g., different scrub patterns)
- It has project-specific reactive triggers (e.g., a database module for a project that uses Postgres instead of SQLite)
- It has project-specific explicit commands

## State Gravity

All `.state/` operations within a child project target the child's `.state/` by default. The parent's `.state/` is only accessed when the user provides explicit `^/^` path notation.

## Bundle

On `bundle`, the child gains its own `.codex/` (inlined from `^/^/.codex`), its CLAUDE.md becomes `apex-root: true`, `^/^` references coalesce to `^`, and `codex: ^/^/.codex` becomes `codex: .codex`.
