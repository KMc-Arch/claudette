---
version: 1
---

# State

Project-specific state. See `^/^/.state/start.md` for the full signal prefix taxonomy and subdirectory descriptions.

All `.state/` operations default to this project's `.state/` (state gravity). The parent's `.state/` is only accessed with explicit `^/^` path notation.

## Subdirectories

- **`memory/`** — Project knowledge. See `^/^/.state/memory/start.md` for type taxonomy.
- **`work/`** — Project tracking. See `^/^/.state/work/start.md` for entry schema.
- **`tests/`** — Verification outputs.
- **`traces/`** — Session observability.

## Root-Level Files

- **`prefs.json`** — Project preference overrides. Merged on top of instance and codex prefs.
