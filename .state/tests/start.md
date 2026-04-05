---
version: 1
---

# Tests

All verification outputs consolidated here. Mirrors `.codex/` structure where applicable.

---

## Output Locations

| Category | Path | Produced by |
|---|---|---|
| Boundary compliance | `compliance/` | `reflexive/session-compliance` |
| Audit records | `audits/` | `explicit/audit` |
| Contract conformance | `reflexive/contract-conformance/` | `reflexive/contract-conformance` |
| Implicit module tests | `implicit/<mirror-path>/` | `reflexive/codex-test-on-edit` |
| Explicit module tests | `explicit/<mirror-path>/` | `reflexive/codex-test-on-edit` |
| Reactive module tests | `reactive/<mirror-path>/` | `reflexive/codex-test-on-edit` |

---

## Diagnostic Map

When something goes wrong, look here:

| Failure type | Look in |
|---|---|
| Rule or boundary violation | `compliance/` |
| Code bug in a codex module | `implicit/`, `explicit/`, or `reactive/` |
| Audit finding | `audits/` |
| Module output doesn't match declaration | `reflexive/contract-conformance/` |

---

## Per-Entry Log Format

Each log entry follows a consistent structure:

1. **Timestamp** — ISO 8601 (e.g., `2026-03-23T14:30:00Z`)
2. **Files examined** — list, tagged `[new]` or `[re-examined]`
3. **Findings** — what was observed
4. **Outputs produced** — list, tagged `[created]` or `[updated]`
5. **User instructions** — verbatim, if any were given for this run
6. **Analytical judgments** — reasoning behind non-obvious conclusions

---

## Signal Prefixes

See `.state/start.md` for the canonical taxonomy. In test context:
- `ESCALATION:` — finding warrants immediate session interruption
- `SURPRISE:` — result contradicts expected behavior

---

## Naming Convention

- Log files: `YYYY-MM-DDTHHMM.log` (ISO 8601, minute precision)
- Audit folders: `YYYYMMDD-HHMM/` (same convention, as folder)

---

## Retention

| Category | Policy |
|---|---|
| Compliance checks | Keep last 10 runs. Archive older on demand. |
| Audit records | **Immutable. Never deleted.** Codex snapshot required per run. |
| Module test results | Keep latest per module. Prior results overwritten. |
| Contract conformance | Keep last 10 runs. Archive older on demand. |

---

## Audit Special Properties

Audit records in `audits/` have additional rules defined in `audits/start.md`:
- Immutable once written — findings are never retroactively edited
- Each run includes a `codex-snapshot/` of relevant codex state at execution time
- Post-hoc resolutions (false positives, acknowledgements) go in a companion file, not in the audit itself
