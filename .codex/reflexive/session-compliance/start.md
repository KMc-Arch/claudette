---
version: 1
trigger: "session closing"
reads:
  - "^/.state/"
writes:
  - "^/.state/tests/compliance/"
---

# session-compliance

Verifies boundary adherence at session close. Checks whether the session respected governance rules throughout its lifetime.

## What It Checks

| Check | What it verifies |
|---|---|
| State gravity | Were all `.state/` writes to the nearest `root: true` context? Any parent-state writes without explicit `^/^` notation? |
| Path containment | Did the session access paths outside `^`? |
| Identity isolation | Was cross-project context imported without explicit authorization? |
| Enforcement tiers | Were any ABSOLUTE HOLD or CONFIRMED HOLD items bypassed? |
| `_` visibility | Were any `_`-prefixed items accessed? |

## Output

Writes compliance summary to `^/.state/tests/compliance/YYYY-MM-DDTHHMM.log` using the standard per-entry log format.

## Limitations

Compliance checking is retrospective and directive-based. It relies on Claude's own recollection of session activity. There is no filesystem-level audit trail — compliance is best-effort, not guaranteed. Trace files (`.state/traces/`) provide supplementary observability.
