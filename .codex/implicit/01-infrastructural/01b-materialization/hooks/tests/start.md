---
version: 1
---

# hooks/tests

Developer-run test harnesses for the enforcement hooks. **Not** registered in the
hook inventory (`../start.md`) and **not** materialized as hooks — plain checks
you run by hand.

- `test_guard_extraction.sh` — proves both guards decode the write target with a
  real JSON parser: the escaped-quote traversal fail-open is closed, `notebook_path`
  (NotebookEdit — the `Write|Edit` matcher fires on it by substring) is checked like
  `file_path`, and any parse failure / missing interpreter fails **closed**.
  Run: `bash test_guard_extraction.sh` — exit 0 = all pass.

- `test_guards_walkup.sh` — proves `gravity-guard.sh` and `containment-guard.sh`
  resolve the containment ceiling to the nearest `root: true` ancestor of the
  launch dir (BL-35), in lockstep with `../../01a-resolution/frontmatter.md`.
  Both guards are run through the same scenario matrix so they cannot drift apart.
  Run: `bash test_guards_walkup.sh` — exit 0 = all pass.
