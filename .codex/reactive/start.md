---
version: 1
---

# Reactive

Reactive entries respond to the USER's context. They activate when external conditions are detected in the current session.

## Trigger Model

Each reactive entry declares its trigger condition in frontmatter:

```yaml
---
trigger: "child project uses SQLite"
---
```

At session boot, only frontmatter is read to build a trigger index. Full content loads only when a trigger matches.

## Trigger Matching

Triggers are natural-language conditions evaluated by Claude against the current session context. A trigger matches when the described condition is observably true in the session — a file pattern is present, a tool is being used, a project characteristic is detected.

Triggers should be specific and falsifiable. Prefer "child project imports sqlite3" over "project might use a database."

## Isolation

Any reactive entry may declare `isolation: subagent` to run in its own context window. When isolated, `reads:`/`writes:` constrain access. See `.codex/start.md` for the full I/O boundary spec.
