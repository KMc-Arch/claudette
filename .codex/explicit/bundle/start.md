---
version: 2
short-desc: Package a child project as a standalone portable copy
reads:
  - "^/.codex/"
  - "^/.state/"
writes:
  - "^/.state/bundles/"
---

# bundle

Create a portable, self-contained copy of a child project by resolving all external references to the parent into inlined content. The bundled project can operate independently without the parent claudette2 instance.

## Usage

`bundle` — bundle the current child project
`bundle <project>` — bundle a specific child project

## Output Location

`^/.state/bundles/YYYYMMDD-HHMM-<project>/` — timestamped to enable multiple bundles. Lives under `.state/` for state gravity compliance.

## What Bundle Does

1. Copy the full project tree into the output folder.
2. Copy `^/^/.codex/` into the bundled project's own `.codex/`.
3. Update CLAUDE.md: `root: true` → `apex-root: true`.
4. Replace `codex: ^/^/.codex` with `codex: .codex`.
5. Coalesce all `^/^` references in codex entries to `^`.
6. Populate `.codex/prefs.json` from the resolved cascade at bundle time (flattened snapshot).
7. Generate `.claude/settings.json` from `.codex/settings.json`.
8. Resolve `start.md` chain references so the bundled project is self-interpreting.

## Rules

- The source project is **never modified**. Bundle operates on a copy.
- `.state/memory/` is included (project knowledge is part of the bundle).
- `.state/work/` is included (project state is part of the bundle).
- `.state/traces/` is excluded (session-specific, not portable).
- `.claude/` transient artifacts are excluded (session state is not portable).
- The bundle is a point-in-time snapshot, not a sync mechanism.

## Codex Override Resolution

If the child project has local `.codex/` entries that override parent entries (same-name, innermost wins), the bundle includes the **child's version** — the override is baked in. The parent's overridden entries are not included.

## Open

The inlining algorithm for edge cases (nested `^/^` references within inlined content, `start.md` chain flattening across levels, preference cascade snapshot vs. live resolution) is not yet fully specified.
