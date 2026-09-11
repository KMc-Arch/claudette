---
version: 2
---

# hooks/tests

Developer-run test harnesses for the enforcement hooks. **Not** registered in the
hook inventory (`../start.md`) and **not** materialized as hooks — plain checks
you run by hand. Each honours `GUARD_DIR=<dir>` so `mutate_guards.sh` can point
them at mutated copies.

- `test_guard_extraction.sh` — how the guards decode the write target. Proves
  the escaped-quote traversal fail-open is closed, that `notebook_path` is
  decoded like `file_path`, that a non-string path / malformed JSON / missing
  interpreter all fail **closed**, and that an oversized path cannot make
  normalization fall back to the raw string.
  Run: `bash test_guard_extraction.sh` — exit 0 = all pass.

- `test_guards_walkup.sh` — how the guards resolve the containment ceiling `^`
  (BL-35): the nearest `root: true` ancestor of the launch dir, with every
  undecidable marker fencing **at** that directory rather than being walked past
  to a looser ceiling. **Every walk-up/marker scenario runs through both guards**;
  the few guard-specific scenarios (hostile CPD, fallback, symlinks) are covered
  for drift by the byte-identity check instead.
  Run: `bash test_guards_walkup.sh` — exit 0 = all pass.

- `test_guards_identical.sh` — asserts the shared decision core (between the
  `guard-core` markers) is byte-identical in both guards.
  Run: `bash test_guards_identical.sh` — exit 0 = identical.

- `test_claude_md_guard.sh` — `claude-md-immutability-guard.sh`: EVERY CLAUDE.md
  (case-insensitive name; trailing-dot/space, `:stream` and invisible-character
  aliases; a hardlink in the same directory; any depth — a parent session is held
  to the child's rule) has an immutable body, fences and structural keys; only
  `name:` / `orchestrator:` lines with valid values may change, and a moved line
  is re-checked; the edit is judged by its result (Edit, `replace_all`, full
  Write), including the line break the Edit tool also deletes on an empty
  `new_string`; the first line containing `---` must be exactly `---` (Claude
  Code ends the block there); CR/BOM/non-LF files and results, frontmatter past
  64 KiB and auto-memory CLAUDE.md files are refused; an existing CLAUDE.md must be
  named by its exact on-disk spelling; creating one is refused; every unvettable
  input fails **closed** (bad JSON or bytes, unstatable/unlistable/unreadable
  targets, device-namespace, drive-relative, `/proc`, `//proc` and `/dev/fd`
  paths, a backslash path naming a CLAUDE.md on POSIX, a planted `json.py`, a
  relative-PATH or Store-stub interpreter, a closed stderr). Cases that prove a
  path check aim at a CLAUDE.md that EXISTS where a mis-reading would look, with a
  `name:`-only change, so the named check is the only thing that can block.
  Payloads are raw UTF-8, as Claude Code sends them. Needs a case-sensitive
  `TMPDIR`; uses the apex's `.state/tmp` for the exact-name case when that is
  case-insensitive; permission cases run only where chmod takes effect;
  POSIX-only cases skip under Windows Python.
  Run: `bash test_claude_md_guard.sh` — exit 0 = all pass.

- `mutate_claude_md_guard.sh` — the mutation proof for the suite above: one
  mutant per hardening (about 80), each required to turn the suite red. The
  controls it deliberately does not mutate, and the mutants that apply only where
  the suite could run the proving case (reported as ENV), are named with the
  reason in its header.
  Run: `bash mutate_claude_md_guard.sh` — exit 0 = every mutant caught. ~25 minutes.

- `mutate_guards.sh` — the mutation proof. Reverts each hardening one at a time
  and requires the suites above to go **red**. This is what makes them evidence
  rather than decoration; run it after any change to a guard or a suite.
  Run: `bash mutate_guards.sh` — exit 0 = every mutant caught. Takes a few minutes
  (22 mutants x 3 suites); it is a developer gate, not something to run inline.

- `test_egress_scan.sh` — the DETECTIVE egress sweep `symlink-egress-scan.sh`
  (on-demand, **not** a PreToolUse hook and not part of `mutate_guards.sh`'s guard
  matrix). Proves an in-^ symlink is left alone, a symlink whose real target
  escapes ^ is reported (exit 1) naming the target, the `_`-prefix and `.git/`
  skips hold, a symlink to ^ itself is not an escape, dangling links are
  range-checked by their lexical target (out flagged, in fine), `--quarantine`
  neutralises the link, and usage / not-a-directory errors exit 2. Creates its
  fixtures as symlinks in a disposable `mktemp` sandbox outside ^.
  Run: `bash test_egress_scan.sh` — exit 0 = all pass.

## Two things these suites deliberately do NOT establish

**Notebooks are not guarded.** The live PreToolUse matcher is `Write|Edit`,
which does not match `NotebookEdit` — the tool never reaches either hook. The
guards decode `notebook_path` so they are correct the moment the matcher is
widened, and the suites prove that decoder. They cannot prove notebooks are
covered, and no unit test here can: piping JSON into the script bypasses the
matcher by construction. An earlier version of this file claimed the matcher
"fires on it via substring". That was false. See BL-56.

**Bash writes are not guarded.** Both hooks are registered on file-write tools
only. `echo >`, `sed -i`, `tee`, and interpreter one-liners never reach them.
See BDRY-10 in `^/.state/work/boundaries.md`.

## Why the assertions look the way they do

A block assertion requires `rc=2` **and** a `BLOCKED:` line on stderr. `rc=2` on
its own is also bash's exit code for a syntax error, so an rc-only assertion
stays green against a guard that never executes a line — measured: 17 of 17
block cases "passed" against a guard that failed to parse.

Fixtures write their own `root: true` marker instead of skipping when `TMPDIR`
sits under a root tree. Skipping loses the coverage exactly where the walk-up is
most interesting.

The previous version of this file claimed the two guards "are run through the
same scenario matrix so they cannot drift apart". Three scenarios ran against
one guard only, and a `resolve_root` change made in a single guard passed every
suite. The claim is now enforced two ways — every scenario runs both guards, and
the shared core is asserted byte-identical — rather than asserted in prose.
