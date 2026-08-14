---
version: 1
---

# hooks/tests

Developer-run test harnesses for the enforcement hooks. **Not** registered in the
hook inventory (`../start.md`) and **not** materialized as hooks — plain checks
you run by hand.

- `test_guard_extraction.sh` — proves `gravity-guard.sh` and `containment-guard.sh`
  decode the write target with a real JSON parser: the escaped-quote traversal
  fail-open is closed, `notebook_path` (NotebookEdit) is checked like `file_path`,
  and any parse failure / missing interpreter fails **closed**. Run:
  `bash test_guard_extraction.sh` — exit 0 = all pass.
