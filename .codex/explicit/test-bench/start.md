---
version: 1
short-desc: "Run TestBench cascade check and report human test reminders"
runtime: python
reads:
  - .codex/settings.json
  - .claude/settings.json
  - Testing/TestBench/.claude/settings.json
  - .state/prefs-resolved.json
  - Testing/TestBench/.state/prefs-resolved.json
writes: []
---

# test-bench

Run the TestBench cascade integrity check, then remind the human which tests require a live session.

## Execution

```
python Testing/TestBench/cascade-check.py --project-root ^
```

For the full round-trip (injects + removes a dummy key through the cascade):

```
python Testing/TestBench/cascade-check.py --project-root ^ --with-roundtrip
```

## After Script Results

Report the results, then remind:

> **Human-only tests** require opening a Claude Code session in `Testing/TestBench/`:
>
> - **CT-1 thru CT-4**: Containment boundary (can child write outside its root?)
> - **SG-1, SG-2**: State gravity (do .state/ writes stay local?)
> - **BR-1, BR-2**: Boot resolution (does codex inheritance work?)
> - **HE-1 thru HE-4**: Hook enforcement (API, visibility, immutability guards)
> - **TL-1**: Trace locality (do traces stay in child's .state/traces/?)
> - **SL-1**: StatusLine renders in child session
>
> See `Testing/TestBench/CLAUDE.md` for the full runbook.
