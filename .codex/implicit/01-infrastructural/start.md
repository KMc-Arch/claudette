---
version: 1
---

# 01 — Infrastructural

Must load before ANY output. Non-negotiable. Contains two sub-bands:

| Sub-band | Purpose | Contents |
|---|---|---|
| `01a-resolution/` | Interpretation directives. Resolve symbols, paths, scope boundaries. Must be internalized before executables run. | `frontmatter.md`, `path-containment.md` |
| `01b-materialization/` | Boot-time artifact generation. Produce files the session needs before user interaction. | `pref-resolve/`, `codex-register/`, `statusline/` |

Sub-bands load in order: 01a completes before 01b begins. Within each sub-band: directives (single files) before executables (module folders), alphabetical tiebreaker.
