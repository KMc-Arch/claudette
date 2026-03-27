---
version: 1
trigger: "session boot complete"
reads:
  - "^/.codex/"
  - "^/.state/prefs-resolved.json"
  - "^/.claude/skills/"
  - "^/.claude/agents/"
writes:
  - "^/.state/tests/boot/"
---

# boot-attestation

Verifies that session boot completed correctly. Fires after all implicit tiers finish.

## What It Checks

| Check | How |
|---|---|
| Frontmatter loaded | `^` resolves correctly |
| Path containment active | Session scope is bounded |
| State gravity active | State operations target nearest `root: true` |
| Identity isolation active | No cross-project context leakage |
| Preferences resolved | `prefs-resolved.json` exists and is not stale |
| Platform shims registered | `.claude/skills/` and `.claude/agents/` populated (if codex-register ran) |

## Output

Writes attestation log to `^/.state/tests/boot/YYYY-MM-DDTHHMM.log` using the standard per-entry log format (see `.state/tests/start.md`).

## On Failure

If any check fails, log the failure and continue the session. Boot attestation is observational — it reports problems but does not gate the session. The user should be informed of any failures so they can decide whether to proceed or investigate.
