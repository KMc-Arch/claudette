---
version: 1
---

# hooks/tests

Developer-run test harnesses for the enforcement hooks. **Not** registered in the
hook inventory (`../start.md`) and **not** materialized as hooks — plain checks
you run by hand.

- `test_guards_walkup.sh` — proves `gravity-guard.sh` and `containment-guard.sh`
  resolve the containment ceiling to the nearest `root: true` ancestor of the
  launch dir (BL-35), in lockstep with `../../01a-resolution/frontmatter.md`.
  Both guards are run through the same scenario matrix so they cannot drift apart.
  Run: `bash test_guards_walkup.sh` — exit 0 = all pass.
