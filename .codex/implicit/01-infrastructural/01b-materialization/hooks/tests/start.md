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

- `mutate_guards.sh` — the mutation proof. Reverts each hardening one at a time
  and requires the suites above to go **red**. This is what makes them evidence
  rather than decoration; run it after any change to a guard or a suite.
  Run: `bash mutate_guards.sh` — exit 0 = every mutant caught. Takes a few minutes
  (22 mutants x 3 suites); it is a developer gate, not something to run inline.

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
