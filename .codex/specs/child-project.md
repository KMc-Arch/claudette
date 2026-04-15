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

## Naming Convention

The `name:` frontmatter field is **user-authoritative** — the creator chooses it and the command trusts it verbatim (digits, casing, punctuation preserved as given). The folder name is **derived** from `name:`.

### Folder derivation (applied in order)

1. Transliterate non-ASCII characters to ASCII (`unicodedata` NFKD fold — good for accented Latin; exotic scripts may need richer transliteration later).
2. Lowercase.
3. Strip a trailing ` Group` suffix. Groups are emergent; the folder doesn't carry the `Group` marker — only the `name:` does.
4. Replace ` ` with `-`.
5. Strip characters outside `[a-z0-9-]`.
6. Collapse consecutive hyphens; strip leading/trailing hyphens.

### Groups

A root is a **group** when it contains one or more nested roots. A group's `name:` ends with ` Group`. Maintained by convention: when `new-project` scaffolds inside an existing root whose own name doesn't end with ` Group`, it flags — non-blockingly — that the parent should be renamed. The user performs the rename manually.

### Collision handling

Folder-name collisions are resolved by numeric suffix:
- Check case-insensitively whether the derived folder collides with an existing sibling (safe on case-insensitive filesystems like NTFS).
- If no collision, use the derived name as-is.
- If any sibling matches `<base><N>` (where `N` is one or more trailing digits), use `max(N) + 1`.
- Otherwise, use `2`.

The numeric suffix lives **only in the folder name**, never in the `name:` field. Apply the same transliteration to existing siblings during collision detection so accented-name collisions are caught.

### Name changes

If `name:` changes after creation (e.g., a leaf becomes a group and gains ` Group`), **flag the user to update Majel accordingly** — Majel may have recorded the prior name. The user decides whether to migrate.

### Apex

The apex CLAUDE.md declares `name: Claudette`. Its folder name is the installation path and is not governed by these derivation rules.
