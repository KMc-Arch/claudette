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
| Reflexive temporal triggers | Cron task registration | `trigger: "cron ..."` in frontmatter |

`.claude/agents/<name>.md` is NOT generated here. Project agents come from `cboot.py::generate_agents`, driven by the opt-in decisions and claims held in `.state/roots.db` — not by any walk of the codex. Module-shim generation for `isolation: subagent` (the row this table used to carry) remains unimplemented.

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

**Current status:** Step 1 of the walk algorithm (explicit -> skill shims) is handled by `cboot.py` pre-launch. `boot-inject.py` (SessionStart hook) handles context injection only. Project agent files are handled separately by `cboot.py::generate_agents` (decision-driven, not by this walk). Steps 2-4 are deferred until modules declare `trigger: "cron ..."`; a module-shim step for `isolation: subagent` was never implemented.

## Walk Algorithm

1. List all folders in `.codex/explicit/`. For each, generate a skill shim.
2. (Deferred, unimplemented) Scan all `start.md` files across `.codex/` for `isolation: subagent`. For each, generate an agent shim. Project agents in `.claude/agents/` are generated separately by `cboot.py::generate_agents`, not by this step.
3. Scan `.codex/reflexive/` for `trigger: "cron ..."`. For each, register a cron task.
4. Read `.codex/settings.json`. For each key in `modules`, read the referenced module `settings.json` and merge into the output.
5. Write all artifacts to `.claude/`.
