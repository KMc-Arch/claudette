---
version: 2
short-desc: Read-only structural validation (60 checks, safe anytime)
reads:
  - "^/.codex/"
  - "^/.state/"
  - "^/.claude/"
  - "^/.gitignore"
  - "^/CLAUDE.md"
  - "^/.templates/"
  - "^/cboot.py"
writes:
  - "^/.state/tests/explicit/test-safe/"
---

# test-safe

Read-only structural validation of the Claudette2 instance. Safe to run anytime — makes no changes, creates no files (except the test log).

## Usage

`test-safe` — run all tests, report pass/fail

## Output Format

Print results as they complete. Passing tests get one line. Failing tests get the failure detail. Tests with multiple sub-conditions show each sub-result indented. Summary at the end.

```
[PASS] T01 — CLAUDE.md exists and has apex-root: true
[PASS] T02 — .codex/start.md exists
[FAIL] T46 — autoMemoryDirectory is absolute
       Expected: absolute path starting with / or drive letter
       Got: .state/memory (relative path)
[WARN] T48 — Auto-memory is landing in .state/memory/ and NOT in user profile
       [WARN] Positive: no memory files found in .state/memory/ besides start.md (may not have accumulated yet)
       [PASS] Negative: no leakage to default external location for this project

═══════════════════════════════════════
  RESULTS: 57/60 passed, 1 failed, 1 warn, 1 skip
═══════════════════════════════════════
```

**Sub-test reporting:** When a test has multiple conditions (labeled 1/2 or Positive/Negative), print each sub-condition as an indented `[PASS]`, `[FAIL]`, or `[WARN]` line beneath the parent test. The parent test's overall verdict is the worst of its sub-conditions (FAIL > WARN > PASS).

Also write results to `^/.state/tests/explicit/test-safe/YYYY-MM-DDTHHMM.log`.

## Test Suite

Run every test below **in order**. For each test, evaluate the condition. Print `[PASS]` or `[FAIL]` with the test ID and title. On failure, print indented detail lines showing expected vs actual.

---

### Category A: Boot Chain & Structure

**T01** — CLAUDE.md exists at `^/CLAUDE.md`
Condition: file exists

**T02** — CLAUDE.md has `apex-root: true` in frontmatter
Condition: read the file, parse YAML frontmatter, check for `apex-root: true`

**T03** — CLAUDE.md body references `.codex/start.md` and `.state/start.md`
Condition: body text contains both strings

**T04** — Child template CLAUDE.md exists
Condition: file exists at `^/.templates/child/CLAUDE.md`

**T05** — Child template CLAUDE.md has `root: true` and `codex:` in frontmatter
Condition: two sub-checks:
1. frontmatter contains `root: true`
2. frontmatter contains `codex:` key

**T06** — `.codex/start.md` exists and has `version:` in frontmatter
Condition: file exists, frontmatter has `version` key

**T07** — `.state/start.md` exists and has `version:` in frontmatter
Condition: same

**T08** — `.gitignore` excludes `_`-prefixed items
Condition: file exists, contains line matching `_*` OR a bare `*` (inverted whitelist model where `*` catches everything including `_`-prefixed items)

---

### Category B: Implicit Tiers

**T09** — All four implicit tiers exist
Condition: directories exist at `.codex/implicit/01-infrastructural/`, `02-foundational/`, `03-standard/`, `04-supplementary/`

**T10** — 01a-resolution contains `frontmatter.md` and `path-containment.md`
Condition: both files exist

**T11** — 01b-materialization contains `pref-resolve/start.md`, `codex-register/start.md`, `statusline/start.md`
Condition: all three files exist

**T12** — 02-foundational contains `identity-isolation.md` and `state-gravity.md`
Condition: both files exist

---

### Category C: Hooks

**T13** — All 13 hook scripts exist
Condition: these files exist in `.codex/implicit/01-infrastructural/01b-materialization/hooks/`:
`boot-inject.sh`, `prefs-staleness-check.sh`, `memory-redirect-check.sh`, `visibility-guard.sh`, `containment-guard.sh`, `gravity-guard.sh`, `api-guard.sh`, `audit-immutability-guard.sh`, `claude-md-immutability-guard.sh`, `codex-edit-notify.sh`, `trace-logger.sh`, `session-close.sh`, `subagent-conformance.sh`

**T14** — All 13 hooks are registered in `.claude/settings.json`
Condition: read `.claude/settings.json`, for each script filename from T13, verify the filename appears in a `"command"` value somewhere in the hooks section

**T15** — `visibility-guard.sh` covers all 6 tool types
Condition: in `.claude/settings.json`, `visibility-guard.sh` appears in matchers that collectively cover `Read`, `Glob`, `Grep`, `Bash`, `Write`, `Edit`

**T16** — `containment-guard.sh` and `gravity-guard.sh` match `Write|Edit`
Condition: both scripts appear in a PreToolUse entry with matcher containing `Write` and `Edit`

**T17** — `api-guard.sh` matches `Bash`
Condition: appears in a PreToolUse entry with matcher containing `Bash`

**T18** — Every hook path in `.claude/settings.json` points to a file that exists
Condition: extract all `"command"` values from hooks section, for each that starts with `bash `, check that the script path after `bash ` exists as a file

---

### Category D: Explicit Commands

**T19** — All 10 explicit command folders exist
Condition: these folders exist in `.codex/explicit/`: `audit`, `bundle`, `new-project`, `pause`, `purge`, `rebuild`, `scrub`, `test-safe`, `test-burn`, `unpause`

**T20** — Each explicit command folder has a `start.md`
Condition: `start.md` exists in each folder from T19

---

### Category E: Reactive & Reflexive

**T21** — Reactive modules exist: `sqlite/start.md`, `backlog-reprint/start.md`
Condition: both files exist

**T22** — `sqlite/sqlite.py` exists
Condition: file exists

**T23** — Reflexive modules exist: `boot-attestation/start.md`, `codex-test-on-edit/start.md`, `contract-conformance/start.md`, `session-compliance/start.md`
Condition: all four files exist

---

### Category F: State Structure

**T24** — `.state/memory/start.md` exists
Condition: file exists

**T25** — `.state/memory/user.md` exists
Condition: file exists

**T26** — `.state/memory/decisions.md` exists
Condition: file exists

**T27** — `.state/memory/state-abstract.md` exists
Condition: file exists

**T28** — `.state/work/start.md` exists
Condition: file exists

**T29** — `.state/work/` contains `backlog.md`, `platform.md`, `architecture.md`, `boundaries.md`, `enhancements.md`
Condition: all five files exist

**T30** — `.state/tests/start.md` and `.state/tests/audits/start.md` exist
Condition: both files exist

**T31** — `.state/traces/start.md` exists
Condition: file exists

**T32** — `.state/bundles/start.md` exists
Condition: file exists

**T33** — `.state/prefs.json` exists and is valid JSON
Condition: file exists, read it, confirm it parses as JSON (even if empty `{}`)

---

### Category G: Preference System

**T34** — `.codex/pref-options.json` exists and is valid JSON
Condition: file exists, parses as JSON

**T35** — `.codex/prefs.json` exists and is valid JSON
Condition: file exists, parses as JSON

**T36** — Every key in `prefs.json` exists in `pref-options.json`
Condition: for each key in `.codex/prefs.json`, that key exists in `.codex/pref-options.json`

**T37** — `prefs-resolved.json` exists and is valid JSON with `_meta`
Condition: if file exists, parse as JSON, verify it contains `_meta.generated`. If file doesn't exist, `[WARN]` (cboot.py may not have run).

**T38** — Every key in `prefs-resolved.json` (except `_meta`) exists in `pref-options.json`
Condition: if T37 passed, for each non-`_meta` key in resolved file, verify it exists in `pref-options.json`. If T37 was WARN, `[SKIP]`.

---

### Category H: Specs

**T39** — `.codex/specs/.base.md` exists (note: dot prefix, NOT underscore)
Condition: file exists at `.codex/specs/.base.md`

**T40** — `.codex/specs/architecture.md` and `dependencies.md` exist
Condition: both files exist

**T41** — `.codex/specs/child-project.md` exists
Condition: file exists

---

### Category I: Platform Bridge

**T42** — `.claude/settings.json` exists and is valid JSON
Condition: file exists, parses as JSON

**T43** — `.claude/settings.json` has `customInstructions` field
Condition: JSON contains key `customInstructions`

**T44** — `.claude/settings.json` `$comment` contains "GENERATED"
Condition: JSON `$comment` value contains the string "GENERATED". If not, `[WARN]` — file may have been hand-edited.

**T45** — `.claude/settings.local.json` exists
Condition: file exists (warn-only — not a hard fail if missing, since it's machine-specific. Print `[WARN]` instead of `[FAIL]`)

**T46** — `autoMemoryDirectory` is set and is an absolute path
Condition: if T45 passed, read the file, extract `autoMemoryDirectory`, verify it starts with `/` or a drive letter. If T45 was WARN, skip this test with `[SKIP]`.

**T47** — `autoMemoryDirectory` points to `.state/memory` for this project
Condition: if T46 passed, verify the path ends with `.state/memory` and resolves to `^/.state/memory`. If T46 was skipped, skip this too.

**T48** — Auto-memory is landing in `.state/memory/` and NOT in user profile
Condition: Two checks, both must pass:
1. **Positive:** `.state/memory/MEMORY.md` exists OR at least one `.md` file (besides `start.md`) exists in `.state/memory/`. This confirms auto-memory is writing to the correct location. If no memory files exist at all, `[WARN]` — the system may not have accumulated any memories yet (expected on first boot).
2. **Negative:** Run `bash -c "ls ~/.claude/projects/*/memory/*.md 2>/dev/null"` and check if any returned files belong to THIS project (match the project path slug or leaf folder name). If memory files exist in the default external location for this project, `[FAIL]` with the external path — auto-memory is leaking. If no match, this check passes.
Overall: PASS requires positive check pass + negative check pass. WARN if positive is uncertain but negative passes. FAIL if negative check finds leakage.

---

### Category J: Cross-Reference Integrity

**T49** — `sqlite.py` docstring references `start.md` not `sqlite.md`
Condition: read `.codex/reactive/sqlite/sqlite.py`, two sub-checks:
1. Positive: a line containing "See" references `start.md`
2. Negative: no line containing "See" references `sqlite.md`
A missing reference (no "See" line at all) is also a failure.

**T50** — `.codex/specs/architecture.md` references `.base.md` not `_base.md`
Condition: read the file, two sub-checks:
1. Positive: contains a reference to `.base.md`
2. Negative: does NOT contain a reference to `_base.md`

---

### Category K: Scripts & Templates

**T51** — `cboot.py` exists at project root
Condition: file exists at `^/cboot.py`

**T52** — `scrub.py` exists in `.codex/explicit/scrub/`
Condition: file exists

**T53** — `purge.py` exists in `.codex/explicit/purge/`
Condition: file exists

**T54** — `bootstrap-child.py` exists in `.codex/explicit/new-project/`
Condition: file exists

**T55** — `.templates/child/` exists and contains `CLAUDE.md`
Condition: directory and file exist

**T56** — `.templates/child/.state/` has expected subdirs
Condition: `memory/`, `work/`, `tests/`, `traces/` all exist under `.templates/child/.state/`

**T57** — `.templates/child/.gitignore` exists
Condition: file exists

---

### Category L: Frontmatter Contract Spot-Checks

**T58** — `bundle/start.md` `writes:` is not empty
Condition: read frontmatter, verify `writes` is not `[]` or absent. Catches the `writes: []` regression.

**T59** — `rebuild/start.md` `writes:` is not empty
Condition: same check

**T60** — `new-project/start.md` `writes:` is not empty
Condition: same check

---

## Execution Notes

- Use the Read tool to check file existence and contents. Do NOT use Bash for file reads.
- Use Glob to verify directory contents efficiently.
- For JSON validation, read the file and check if the content is well-formed JSON.
- Count passes, fails, warns, and skips separately. Report all four in the summary.
- For tests with numbered sub-conditions (1, 2) or labeled sub-checks (Positive, Negative): print each sub-result as an indented line beneath the parent. The parent's overall verdict is the worst of its sub-conditions (FAIL > WARN > PASS). Only count the parent in the summary totals, not the sub-checks.
- Write the full log to `.state/tests/explicit/test-safe/` with timestamp filename.
