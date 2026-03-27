---
version: 1
trigger: "executable files in .codex/ edited"
reads:
  - "^/.codex/"
writes:
  - "^/.state/tests/"
---

# codex-test-on-edit

Runs a module's test suite when its executable files are modified. Catches regressions immediately.

## When It Triggers

When any `.py`, `.sh`, or other executable file within a `.codex/` module is edited during the session.

## Procedure

1. Identify the edited module (the folder containing the edited file).
2. Check if the module has a `test/` subfolder.
3. If yes, run all `test_*.py` files in the `test/` subfolder.
4. Write results to `.state/tests/<mirror-path>/` where `<mirror-path>` mirrors the module's codex location (e.g., editing `.codex/explicit/scrub/scrub.py` → results to `.state/tests/explicit/scrub/`).
5. Report pass/fail to the user.

## If No Test Suite

If the edited module has no `test/` subfolder, log that the module was edited but no tests exist. This is informational, not a failure.
