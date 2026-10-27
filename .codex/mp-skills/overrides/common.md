---
version: 1
---

# Common overrides (all mp-skills)

This file replaces `setup-matt-pocock-skills`. **Never run that skill**: its step 4 edits the
`CLAUDE.md` body, which is under an ABSOLUTE HOLD, and it defaults to GitHub issues, which
`remote-guard` blocks.

Paths below use `^` = the nearest `root: true` project (state gravity).

## Where things go

| Upstream default | Here instead |
|---|---|
| Issue tracker: GitHub (`gh issue …`, `gh api …`) | **Never.** `remote-guard` blocks all `gh issue*` / `gh api*`, reads included. Don't work around it. |
| Issue tracker: local `.scratch/<feature>/` | `^/.state/plans/<effort>/`, using the operations in `skills/setup-matt-pocock-skills/issue-tracker-local.md` with `.scratch/` read as `^/.state/plans/`. |
| Specs: `.scratch/<feature>/spec.md` | `^/.state/plans/<feature>/spec.md` |
| `GLOSSARY.md` / `GLOSSARY-MAP.md` at the repo root | `^/.state/memory/reference/glossary.md` (one file; add sections if contexts ever diverge) |
| `docs/adr/NNNN-*.md` | An entry in the matching `^/.state/memory/decisions/decisions-*.md`, in that file's existing style |
| `docs/agents/*.md` config | None; this file is the config |
| Research notes | `^/.state/plans/<effort>/research/<slug>.md`, or `^/.state/memory/reference/` if durable beyond the effort. **No throwaway git branches.** |
| Triage labels (`needs-triage`, `ready-for-agent`, …) | None. Unattended work goes through Heartbeat (`/hb-send`), never labels. |

**Never create** at a repo root: `GLOSSARY.md`, `GLOSSARY-MAP.md`, `docs/adr/`, `docs/agents/`, `.scratch/`.
**Every new folder** gets a `start.md` (codex convention).

## Hard limits (governance wins)

- **`CLAUDE.md` / `AGENTS.md`**: never edit or create. Skills that say to (`setup-matt-pocock-skills`,
  `writing-for-agents`) stop at a draft for the operator.
- **Symlinks**: never create. Any install uses `--copy`.
- **Hooks**: `git-guardrails-claude-code` and `setup-pre-commit` install hooks. Don't run them without
  first checking for conflicts with the existing guard hooks and the pre-push scrub.
- **Containment**: write only inside `^`. This library is read-only from a project session.
- **Tracked state is framework-exclusive** in zdm: no client identifiers in plans, tickets or glossary.

## "Cross-reference with code"

If the project's memory marks its code as **harvest-only** (zdm since 2026-09-29), check claims
against the redesign artifacts (e.g. `designs/*.drawio`). Cite the old code only as prior art or a
lesson, never as the truth a design must match.
