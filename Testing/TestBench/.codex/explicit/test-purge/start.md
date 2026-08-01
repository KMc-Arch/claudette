---
version: 2
short-desc: "Destructive purge verification — populates, purges, verifies the allowlist model"
runtime: python
---

# test-purge

Destructive test for purge correctness. Populates dummy content, runs purge, and
verifies the right files survived or died against purge's **allowlist model** (see
`^/^/.codex/explicit/purge/start.md`). Designed to run from the apex root.

## Usage

```
python Testing/TestBench/.codex/explicit/test-purge/test-purge.py [MODE]
```

Modes: `populate` · `standard` · `all` · `dryrun` · `footprint` · `child` · `symlink` · `full`
(`full` runs every non-populate mode and aggregates).

## What It Tests

### Bare `purge` (standard) removes:
- `.claude/` session files (`.jsonl`, `.md`) — preserves `settings*.json` and `_`-prefixed
- `.claude/skills/` and `.claude/agents/` (generated shims)
- `.state/prefs-resolved.json`
- `.state/tests/` transient outputs (NOT audits, NOT boot reports)
- Keep-recent dirs pruned to the newest 5 **real** files each: `.state/traces/` and the
  two `.state/tests/boot/` report kinds (`*-bootstrap.md`, `*-refresh-*.md`). A
  `_`-prefixed match never takes a keep slot.

Bare purge **keeps** everything precious — transcripts, `.state/pauses/`, `.state/memory/`,
`.state/work/`, `.state/plans/`, `.state/bundles/`, and loose `.tmp/` buffers.

### `purge all` additionally removes (no recency sparing):
- Keep-recent dirs **wiped entirely** (keep=0)
- `.state/memory/`, `.state/work/`, `.state/plans/`, `.state/bundles/` contents (except `start.md`)
- `.state/pauses/` contents
- The external transcript store `~/.claude/projects/<slug>/` (tested under an ISOLATED HOME)
- The **entire `.tmp/`** — loose buffers, `.tmp/sandbox/` rigs, and every subdir

### Must survive every scope (the hard floor):
- `.state/tests/audits/` — immutable
- Every `start.md` — including `.tmp/start.md`
- All `_`-prefixed items — protected at **every depth** (a nested `.state/memory/sub/_secret.md`
  and a 2-level-deep `.state/memory/deep/deeper/_deep.md`, and the dirs that hold them, both survive `all`)
- Symlinks — never followed or deleted; their targets are never reached through them
- `CLAUDE.md`, `.codex/` (including this test)

### Must be reported but NOT removed:
- `.tmp/sandbox/` rigs — under **bare/child** scope (report-only); under `all` they are DELETED.
- Scratch-looking files found *outside* `.tmp/` at the project root (straggler detection) —
  report-only in **every** scope.

## Verification integrity

The suite is built to actually fail on a regression: the footprint test carries an
**independent golden-slug oracle** (not derived from purge's own function), the escape
test isolates the containment guard from the not-a-dir check, and the fail-loud
missing-footprint WARNING is asserted, not just exercised.

## Location

This command lives inside `TestBench/.codex/` so it survives `purge all`. The test
environment is self-contained and disposable; cleanup self-heals via `cboot --project`.
