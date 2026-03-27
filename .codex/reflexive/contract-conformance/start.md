---
version: 1
trigger: "explicit module execution completes"
reads:
  - "^/.codex/explicit/"
  - "^/.state/"
writes:
  - "^/.state/tests/reflexive/contract-conformance/"
---

# contract-conformance

Verifies that an explicit module's actual output matched its declared `writes:` contract. The third verification leg alongside unit tests (code correctness) and session compliance (boundary adherence).

## When It Triggers

After any explicit module finishes execution.

## What It Checks

Compares the module's declared `writes:` paths against what was actually produced:
- **Declared but not written** — the module promised an output it didn't deliver.
- **Written but not declared** — the module produced an output it didn't promise.

## Severity

Mismatches are logged at `SURPRISE:` level — unexpected, not necessarily wrong. The declaration may need updating rather than the behavior changing.

## Scope

- Only checks `writes:` (outputs are observable post-hoc; inputs are harder to verify without filesystem monitoring).
- Only fires for explicit modules (reactive and reflexive modules fire on conditions, not user invocation — their I/O is less predictable).
- Depends on `reads:`/`writes:` declarations being present. If a module omits declarations, there's nothing to check.

## Output

Writes conformance log to `^/.state/tests/reflexive/contract-conformance/YYYY-MM-DDTHHMM.log`.
