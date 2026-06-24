---
version: 1
short-desc: "Destructive purge verification — populates, purges, verifies"
runtime: python
---

# test-purge

Destructive test for purge correctness. Populates dummy content, runs purge (standard or all), and verifies the right files survived or died.

## Usage

```
python Testing/TestBench/.codex/explicit/test-purge/test-purge.py [populate|standard|all]
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
- `.tmp/sandbox/` contents (disposable rigs)

### Purge-all should additionally remove:
- `.state/memory/` files (except `start.md`)
- `.state/work/` files (except `start.md`)
- `.state/plans/` files (except `start.md`)
- `.state/bundles/` contents
- Loose `.tmp/` buffers older than the freshness window (12h)

### Must survive both:
- `.state/tests/audits/` — immutable
- All `start.md` files — structural manifests (including `.tmp/start.md`)
- `CLAUDE.md` — project identity
- `.codex/` — framework (including this test)
- Loose `.tmp/` buffers modified within the freshness window (kept by `purge all`)

### Must be reported but NOT removed:
- Scratch-looking files found *outside* `.tmp/` (straggler detection) — purge surfaces them in its output but never deletes them.

## Location

This command lives inside `TestBench/.codex/` specifically so it survives purge-all. The test environment is self-contained and disposable.
