---
version: 1
---

# 00 — Preboot

Runs before all other tiers. Contains scripts that cboot.py executes to prepare child projects before any session starts.

Unlike tiers 01-04, preboot entries are **not Claude directives** — they are Python modules called by cboot.py during the parent boot sequence. Their output (materialized artifacts at child projects) enables children to launch independently with full hook and preference coverage.

| Entry | Purpose |
|---|---|
| `child_propagate.py` | Discover child projects, materialize their `.claude/settings.json` (hooks with `../` paths) and `.state/prefs-resolved.json` (parent prefs + child overrides). |
