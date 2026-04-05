---
version: 1
short-desc: "Destructive purge verification — populates, purges, verifies"
runtime: python
---

# test-purge

Destructive test for purge correctness. Populates dummy content, runs purge (standard or all), and verifies the right files survived or died.

## Usage

```
python Metaclawd/TestBench/.codex/explicit/test-purge/test-purge.py [populate|standard|all]
```

- `populate` — create dummy files in all purgeable locations (resets to known state)
- `standard` — populate, run standard purge, verify
- `all` — populate, run purge-all, verify

## What It Tests

### Standard purge should remove:
- `.claude/` session files (`.jsonl`, `.md`)
- `.state/prefs-resolved.json`
- `.state/tests/boot/` reports
- `.state/traces/` session traces
- `.state/pauses/` session snapshots

### Purge-all should additionally remove:
- `.state/memory/` files (except `start.md`)
- `.state/work/` files (except `start.md`)
- `.state/plans/` files (except `start.md`)
- `.state/bundles/` contents

### Must survive both:
- `.state/tests/audits/` — immutable
- All `start.md` files — structural manifests
- `CLAUDE.md` — project identity
- `.codex/` — framework (including this test)

## Location

This command lives inside `TestBench/.codex/` specifically so it survives purge-all. The test environment is self-contained and disposable.
