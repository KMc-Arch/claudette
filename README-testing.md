# Test Infrastructure

Claudette2 has a four-tier test system. The tiers are ordered from fastest and safest to slowest and most thorough.

## Tier Overview

| Tier | Tool | Runs Where | Duration | Modifies State? | What It Checks |
|------|------|-----------|----------|-----------------|---------------|
| 1 | `python ctest.py` | Terminal (no LLM) | Milliseconds | No | Bootstrap outputs are correct |
| 2 | `python chooks.py` | Terminal (no LLM) | Seconds | Minimal (trace files) | Hook scripts behave correctly |
| 3 | `test-safe` (in Claude) | Claude session | Minutes | No (log only) | 60 structural checks |
| 4 | `test-burn` (in Claude) | Claude session | Minutes | Yes (temporary) | End-to-end functional tests |

**Recommended order:** Run them in tier order. If tier 1 fails, do not proceed to tier 2. If tier 3 fails, fix issues before running tier 4.

## Tier 1: ctest.py -- Bootstrap Verification

```
python ctest.py
python ctest.py --project-root /path/to/project
```

Validates that `cboot.py` produced correct outputs. Pure Python, no network calls.

**17 checks across 8 categories:**

| ID Range | Category | What It Checks |
|----------|----------|---------------|
| V01-V02 | Skill shims | Shim count matches commands, each has SKILL.md |
| V03-V05 | Preferences | prefs-resolved.json exists, valid JSON, keys match schema |
| V06-V09 | Settings | settings.json exists, has GENERATED marker, hook count, all hook paths resolve |
| V10-V12 | Auto-memory | settings.local.json exists, autoMemoryDirectory is absolute, points to .state/memory |
| V13 | Scaffolding | All 13 expected directories exist |
| V14-V15 | Structure | Hook/command/module counts, start.md presence |
| V16 | Critical files | CLAUDE.md, cboot.py, .codex/start.md, .state/start.md, .gitignore, child template |
| V17 | Scripts | scrub.py, purge.py, bootstrap-child.py exist |

**Exit codes:** 0 = all pass, 1 = any failure.

## Tier 2: chooks.py -- Hook Behavioral Tests

```
python chooks.py
python chooks.py --project-root /path/to/project
```

Feeds mock tool-call JSON to each hook script via stdin and validates exit codes and stdout/stderr. Tests that hooks correctly allow or block specific operations.

**13 hooks tested, ~45 individual test cases:**

| Hook | Test IDs | Key Behaviors Tested |
|------|----------|---------------------|
| visibility-guard.sh | VG01-VG05 | Blocks `_`-prefixed paths, allows normal paths, catches nested underscore segments |
| containment-guard.sh | CG01-CG04 | Blocks writes outside project root, allows inside, handles relative paths |
| gravity-guard.sh | GG01-GG03 | Blocks `.state/` writes to parent project, allows local state writes |
| api-guard.sh | AG01-AG05 | Blocks pip install anthropic, import anthropic, curl to api.anthropic.com |
| audit-immutability-guard.sh | AI01-AI03 | Blocks edits to existing audit findings, allows decisions.md and non-audit writes |
| claude-md-immutability-guard.sh | CM01-CM03 | Blocks root CLAUDE.md edits, allows child CLAUDE.md and other files |
| boot-inject.sh | BI01-BI03 | Outputs boot sequence with command index |
| prefs-staleness-check.sh | PS01-PS04 | Detects missing prefs-resolved.json, no false warnings when fresh |
| memory-redirect-check.sh | MR01-MR04 | Warns when auto-memory not configured, silent when correct |
| codex-edit-notify.sh | CE01-CE06 | Notifies on .py/.sh edits in codex, silent on .md and non-codex files |
| trace-logger.sh | TL01-TL02 | Writes trace entries to daily trace file |
| session-close.sh | SC01-SC03 | Outputs session-closing governance prompt |
| subagent-conformance.sh | SA01-SA02 | Outputs subagent completion checklist |

**Coverage verification:** At the end of every run, chooks.py verifies that every hook has at least one test (COV1) and every test maps to an existing hook (COV2).

**Exit codes:** 0 = all pass, 1 = any failure.

## Tier 3: test-safe -- Structural Validation

Run from inside a Claude session:

```
You: run test-safe
```

60 read-only checks across 12 categories (A through L). See [README-commands.md](README-commands.md) for the category list. This is the most comprehensive structural check because it runs inside Claude's context and can verify things the external scripts cannot (like cross-reference integrity between documentation files).

**Output format:**
```
[PASS] T01 -- CLAUDE.md exists and has apex-root: true
[PASS] T02 -- .codex/start.md exists
[FAIL] T46 -- autoMemoryDirectory is absolute
       Expected: absolute path starting with / or drive letter
       Got: .state/memory (relative path)

===================================
  RESULTS: 57/60 passed, 1 failed, 1 warn, 1 skip
===================================
```

Log written to `.state/tests/explicit/test-safe/`.

## Tier 4: test-burn -- Functional End-to-End

Run from inside a Claude session:

```
You: run test-burn
```

17 tests across 6 phases. This test **modifies your instance** -- it creates a temporary child project, runs scrub and purge, then cleans up. Always run `test-safe` first. Run `python cboot.py` afterward to restore any generated artifacts that were removed during purge testing.

See [README-commands.md](README-commands.md) for the detailed phase breakdown.

## When Tests Fail

### General approach

1. **Read the failure detail.** Every failing test prints what it expected and what it got.
2. **Check whether the issue is real or environmental.** Some tests (like T45-T47 for auto-memory) may show WARN on first boot before `cboot.py` has run.
3. **Fix the root cause, then re-run the failing tier.** Do not skip ahead to higher tiers.

### Common failure scenarios

**ctest.py failures:**

| Failure | Likely Cause | Fix |
|---------|-------------|-----|
| V01 -- Skill shims mismatch | A command was added/removed without re-running cboot.py | Run `python cboot.py` |
| V06-V09 -- settings.json issues | settings.json was hand-edited | Delete `.claude/settings.json`, run `python cboot.py` |
| V10-V12 -- auto-memory wrong | settings.local.json misconfigured | Delete `.claude/settings.local.json`, run `python cboot.py` |
| V13 -- missing directories | Directories were deleted | Run `python cboot.py` (scaffold step recreates them) |

**chooks.py failures:**

| Failure | Likely Cause | Fix |
|---------|-------------|-----|
| Script not found | Hook script missing from hooks directory | Verify `.codex/implicit/01-infrastructural/01b-materialization/hooks/` contains all 13 .sh files |
| Wrong exit code | Hook logic error or Bash compatibility issue | Read the hook script, check for platform-specific issues (Windows line endings, path separators) |
| COV1 -- untested hooks | New hook added without tests | Add test functions in chooks.py with `@register_test("hook-name.sh")` |

**test-safe failures:**

| Failure | Likely Cause | Fix |
|---------|-------------|-----|
| T13-T18 -- hook issues | Hooks not registered or paths broken | Run `python cboot.py` to regenerate settings.json |
| T37-T38 -- prefs issues | prefs-resolved.json missing or stale | Run `python cboot.py` to regenerate |
| T45-T47 -- auto-memory | settings.local.json not created | Run `python cboot.py`; if still failing, check PLAT-02 in `.state/work/platform.md` |
| T48 -- memory leaking | Auto-memory writing to default location | Fix autoMemoryDirectory path, then run `purge` to clean external memory |

**test-burn failures:**

| Phase | Likely Cause | Fix |
|-------|-------------|-----|
| Phase 1 (child project) | Template files missing or bootstrap-child.py broken | Check `.templates/child/` exists with CLAUDE.md |
| Phase 2 (scrub) | scrub.py or patterns.txt missing | Verify `.codex/explicit/scrub/scrub.py` and `patterns.txt` exist |
| Phase 4-5 (purge) | purge.py logic error | Check `.codex/explicit/purge/purge.py` |
| Phase 6 (cleanup) | Artifacts not cleaned up | Manually check for and remove `test-burn-child/` and test files listed in B17 |

### After fixing

Always re-run the full tier that failed, not just the individual test. Test ordering can matter -- a fix for one test may affect others.

## Running Tests in CI

`ctest.py` and `chooks.py` are designed for CI pipelines -- they require no LLM, run in seconds, and return standard exit codes:

```yaml
- name: Verify Claudette2 bootstrap
  run: python ctest.py

- name: Test hook scripts
  run: python chooks.py
```

`test-safe` and `test-burn` require a live Claude session and consume API tokens, so they are typically run manually or in a dedicated integration environment.

## Read Next

| Document | When to Read It |
|----------|----------------|
| [README.md](README.md) | Overview and quick start |
| [README-setup.md](README-setup.md) | Installation and first-boot troubleshooting |
| [README-commands.md](README-commands.md) | Full command details (test-safe and test-burn specs) |
