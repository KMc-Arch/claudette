---
version: 1
---

# 01b — Materialization

Boot-time artifact generation. These modules produce files the session needs before any user interaction. They run after 01a-resolution directives are internalized.

## Modules

| Module | Produces | Required for |
|---|---|---|
| `pref-resolve/` | `.state/prefs-resolved.json` | Correct behavioral configuration |
| `codex-register/` | `.claude/skills/`, `.claude/agents/`, cron registrations | Platform integration (slash commands, subagents, scheduled tasks) |
| `statusline/` | Status bar output | Terminal session context display |
