---
version: 1
---

# hooks/tools

On-demand detective and maintenance scripts that live beside the hooks but are
**not** registered hooks — run by hand or by `cboot`, never as
PreToolUse/SessionStart hooks. Kept in this subdirectory so the hook-registration
completeness check (test-safe T14) only ever sees real hooks directly in
`hooks/`; a script here is a tool, not a forgotten-to-register hook.

- `symlink-egress-scan.sh` — the DETECTIVE egress sweep. Reports symlinks under a
  root whose real target escapes that root — the egress links the as-referenced
  resolution model authorises but no input-gate can prevent (interpreter-created,
  and transitive from `git`/`tar`/`npm`/`venv`). **Not a boundary** — the boundary
  is environment isolation (BL-61); this only surfaces what slipped in.
  Usage: `bash symlink-egress-scan.sh [ROOT] [--quarantine]` — ROOT defaults to
  `$CLAUDE_PROJECT_DIR`; exit 0 = clean, 1 = egress found (reported), 2 = usage
  error. Covered by `../tests/test_egress_scan.sh`.

  It has **no allowlist**, so a boot-time sweep would flag every accepted egress
  link (a client-data mount, `.tmp` shims) on each run. Wiring it at boot is
  therefore deferred hardening (BL-62 [R4-5]) that first needs a `.tmp` skip plus
  an accepted-egress allowlist; today it is on-demand only.
