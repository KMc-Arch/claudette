---
version: 1
---

# State

The state directory holds all instance-specific accumulation. Everything observational or accumulated lives here: memory, work tracking, test outputs (including audits), and preference overrides.

State is never shared between instances unless deliberately migrated. All `.state/` operations default to the nearest `root: true` context (state gravity — see `.codex/start.md`).

---

## Signal Prefix Taxonomy

Optional prefixes for entries in any `.state/` subdirectory. These are the **canonical definitions** — each subdirectory's `start.md` references this section and contextualizes for its domain.

| Prefix | Meaning |
|---|---|
| `ESCALATION:` | Requires attention beyond current scope |
| `DECISION:` | Records a choice that constrains future work |
| `SURPRISE:` | Unexpected finding that changes assumptions |
| `CONFLICT:` | Tension between two valid approaches |

Most entries should NOT have a prefix. Overuse dilutes signal value.

---

## Subdirectories

- **`memory/`** — Knowledge: who, why, what we know. Typed files with retrieval semantics.
- **`work/`** — Project state: what's tracked. Backlog, platform constraints, architecture debt, boundary gaps, enhancements.
- **`tests/`** — All verification outputs, consolidated. Boot attestation, compliance, audits, module test results.
- **`traces/`** — Session observability records. What happened during a session: codex loading, trigger activity, module invocations, tool calls.
- **`plans/`** — Plan mode files. Claude Code's multi-step implementation plans, redirected here by `plansDirectory` setting.
- **`pauses/`** — Session context snapshots for later resumption. Created by the `pause` command.
- **`bundles/`** — Point-in-time portable snapshots of child projects. Created by the `bundle` command.

---

## Root-Level Files

- **`prefs.json`** — Instance preference overrides. Merged on top of `.codex/prefs.json`. Does not travel.
- **`prefs-resolved.json`** — Generated at boot by `pref-resolve`. Single flat file of effective preferences after full cascade resolution. Claude reads ONLY this file for preferences. Regenerated each session.
