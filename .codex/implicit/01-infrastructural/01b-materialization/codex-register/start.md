---
version: 1
runtime: python
reads:
  - "^/.codex/explicit/"
  - "^/.codex/reflexive/"
  - "^/.codex/settings.json"
writes:
  - "^/.claude/skills/"
  - "^/.claude/agents/"
  - "^/.claude/settings.json"
---

# codex-register

Platform shim materializer. Walks the codex and generates thin registration artifacts in `.claude/` so Claude Code's native mechanisms (skills, agents, cron) can discover codex-defined modules.

## Trigger

Runs at boot as part of `01b-materialization`. Must complete before user interaction — slash commands and subagents need to be registered.

## What It Generates

| Codex source | Platform target | Condition |
|---|---|---|
| Each folder in `explicit/` | `.claude/skills/<name>/SKILL.md` | Entry exists |
| Any module with `isolation: subagent` | `.claude/agents/<name>.md` | `isolation: subagent` in frontmatter |
| Reflexive temporal triggers | Cron task registration | `trigger: "cron ..."` in frontmatter |

## Shim Format

Generated shims are one-line redirects. They contain no substantive content — the codex entry is authoritative.

```markdown
# .claude/skills/scrub/SKILL.md
---
name: scrub
---
Read and follow .codex/explicit/scrub/start.md
```

## Settings Materialization

Reads `.codex/settings.json`, resolves module references in the `modules` map, assembles the flattened settings, and writes to `.claude/settings.json` with a `$comment` marking it as generated.

## Graceful Degradation

If this module fails, shims can be written manually. The failure mode is missing registrations (obvious — slash commands don't work), not wrong registrations (silent — wrong behavior). The system degrades to manual setup, not to corruption.

**Current status:** Step 1 of the walk algorithm (explicit -> skill shims) is handled by `boot-inject.sh` as a bash fallback. The shims are generated at every SessionStart, ensuring they always exist even without the full Python implementation. Steps 2-4 are deferred until modules declare `isolation: subagent` or `trigger: "cron ..."`.

## Walk Algorithm

1. List all folders in `.codex/explicit/`. For each, generate a skill shim.
2. Scan all `start.md` files across `.codex/` for `isolation: subagent`. For each, generate an agent shim.
3. Scan `.codex/reflexive/` for `trigger: "cron ..."`. For each, register a cron task.
4. Read `.codex/settings.json`. For each key in `modules`, read the referenced module `settings.json` and merge into the output.
5. Write all artifacts to `.claude/`.
