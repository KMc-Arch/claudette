---
version: 1
---

# Plans

Plan files are Claude Code's built-in mechanism for multi-step implementation planning. When plan mode is active, Claude writes a structured plan to a `.md` file before executing work.

---

## Platform Setting

The `plansDirectory` key in `.codex/settings.json` redirects plan files from Claude Code's default location (`~/.claude/`) into project-local state:

```json
"plansDirectory": ".state/plans"
```

This keeps plans co-located with the project they belong to, subject to state gravity. Child projects inherit the setting via `child_propagate.py` and store plans in their own `.state/plans/`.

---

## File Format

Plan files are auto-named by Claude Code with random three-word slugs (e.g., `frolicking-cuddling-hartmanis.md`). Contents are markdown with a title, context, and step-by-step implementation sections. Claude Code manages the lifecycle -- files are created, updated, and referenced automatically.

---

## Lifecycle

- **Created** when a session enters plan mode (manually via `/plan` or automatically for complex tasks)
- **Updated** as the plan is refined during conversation
- **Consumed** during implementation -- Claude follows the plan's steps
- **Retained** after session ends -- plans persist as a record of implementation intent

Plans are not memory files and do not carry typed frontmatter. They are session artifacts that happen to persist.

---

## Signal Prefixes

See `.state/start.md` for the canonical taxonomy. Plans rarely need signal prefixes, but `DECISION:` is appropriate when a plan records a significant architectural choice.
