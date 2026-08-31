---
version: 7
short-desc: Read-only structural validation (77 checks, safe anytime)
reads:
  - "^/.codex/"
  - "^/.state/"
  - "^/.claude/"
  - "^/.gitignore"
  - "^/CLAUDE.md"
  - "^/README-concepts.md"
  - "^/.templates/"
  - "^/cboot.py"
  - "^/.git/ (T52a only: config via its mandated git command; hook presence via Read)"
  - "^/**/.codex/ and ^/**/.claude/ (child settings scans, T48a/T48b)"
  - "~/.claude/projects/ (EXTERNAL, read-only — T48 leak probe only)"
  - "EXTERNAL read-only probes by mandated machinery (T18/T48b/T52a): shutil.which PATH-dir stats, interpreter/script existence stats outside ^, git config effective-value read (may source ~/.gitconfig)"
writes:
  - "^/.state/tests/explicit/test-safe/"
---

# test-safe

Read-only structural validation of the Claudette2 instance. Safe to run anytime — makes no changes, creates no files (except the test log).

## Usage

`test-safe` — run all tests, report pass/fail

## Output Format

Print results as they complete. Passing tests without sub-conditions get one line (sub-conditioned tests always show their indented sub-results). Failing tests get the failure detail. Tests with multiple sub-conditions show each sub-result indented. Summary at the end.

```
[PASS] T01 — CLAUDE.md exists at ^/CLAUDE.md
[PASS] T02 — CLAUDE.md has apex-root: true in frontmatter
[FAIL] T46 — autoMemoryDirectory is absolute
       Expected: absolute path starting with / or drive letter
       Got: .state/memory (relative path)
[WARN] T48 — Auto-memory is landing in .state/memory/ and NOT in user profile
       [WARN] Positive: no memory files found in .state/memory/ besides start.md (may not have accumulated yet)
       [PASS] Negative: no leakage to default external location for this project

═══════════════════════════════════════
  RESULTS: 74/77 passed, 1 failed, 1 warn, 1 skip
═══════════════════════════════════════
```

**Sub-test reporting:** When a test has multiple conditions (labeled 1/2 or Positive/Negative), print each sub-condition as an indented `[PASS]`, `[FAIL]`, or `[WARN]` line beneath the parent test. The parent test's overall verdict is the worst of its sub-conditions (FAIL > WARN > PASS).

Also write results to `^/.state/tests/explicit/test-safe/YYYY-MM-DDTHHMMSS.log` (seconds prevent same-minute rerun overwrite).

## Test Suite

Run every test below **in order**. For each test, evaluate the condition. Print the verdict tag (`[PASS]`/`[FAIL]`/`[WARN]`/`[SKIP]`) with the test ID and title. On failure, print indented detail lines showing expected vs actual.

---

### Category A: Boot Chain & Structure

**T01** — CLAUDE.md exists at `^/CLAUDE.md`
Condition: file exists

**T02** — CLAUDE.md has `apex-root: true` in frontmatter
Condition: read the file, parse YAML frontmatter, check for `apex-root: true`

**T02a** — Boot-core region integrity in apex CLAUDE.md
Condition: four sub-checks (the region is the primary governance delivery — apex + every child receive it via the CLAUDE.md ancestor walk; deleting or emptying it strips governance silently):
1. Exactly one line containing the literal `boot-core:begin` and exactly one containing `boot-core:end`, begin line before end line (substring semantics — the live begin marker legitimately carries prose inside its comment)
2. The region between them contains all three mandated section headings (`Governance Primitives`, `Naming Conventions`, `Instance State`) AND their load-bearing bodies: the literals `ABSOLUTE HOLD` and `CONFIRMED HOLD` each followed within their subsection (its heading line to the next heading of any level or the end marker, whichever first) by a `MUST NOT perform [X]` operative line, plus the naming table's `visibility-guard.sh` row, plus — within the same subsection windows — the ABSOLUTE HOLD resistance clauses (`No other input` and `Default is refusal`) and the CONFIRMED HOLD operative clause (`wait for a single confirmation`) — surviving headings over deleted bodies are a gutted region and `[FAIL]`
3. The Instance State section carries the `state-abstract.md` read mandate
4. `^/README-concepts.md` exists (the boot-core's lazy-vocabulary target)

**T03** — CLAUDE.md body references `.codex/start.md` and `.state/start.md`
Condition: body text contains both strings

**T03a** — Backstop ↔ sentinel token contract
Condition: three sub-checks (the layer-2 backstop must fire iff governance failed to load; token drift on either side makes it always-fire or never-fire — the CONFIRMED-critical class the mileqa cadre caught live):
1. The CLAUDE.md backstop conditions on the literal trigger token `=== BOOT INSTRUCTIONS ===` (interactive-session recovery) AND carries the dispatched-subagent carve-out (anchor: the literal `Dispatched subagents`). Both anchors must be present in the pre-`boot-core:begin` backstop region; they may share one line or sit on adjacent backstop bullets (fc26b38 split the single paragraph into an Interactive-Sessions bullet and a Dispatched-subagents bullet — the drift this guards against is an anchor going *missing*, not the two living on separate lines)
2. `boot-inject.py` contains exactly one occurrence of that token, and it sits inside the branch taken when governance sources loaded (statically: within the `else` arm of the `if not sources:` fork — not in the GOVERNANCE FAILED block, not unconditional before/after the branch, and with NO intervening compound statement (`if`/`for`/`while`/`try`) between the `else:` line and the emission: the emission sits one indentation level below the `else:`)
3. The failure-branch marker `GOVERNANCE FAILED TO LOAD` is present in `boot-inject.py` (sentinel-withholding path intact)

**T03b** — boot-inject.py hardening invariants
Condition: three sub-checks (static content checks only — behavioral verification belongs to chooks/test-bench, never this suite):
1. The literal returned on the no-override fallback path of `_ceiling_bytes()` is positive and below 29,898 (the lowest observed spill; per upper-bound doctrine the true threshold is known only from failures). The `BOOT_INJECT_CEILING` env override is an intentional, unclamped escape hatch — out of scope for this static suite (BL-27).
2. The over-ceiling degradation stub is present (anchor: the literal `GOVERNANCE BUNDLE OVER CEILING`)
3. `state-abstract.md` is NOT emitted eagerly by the hook (laziness is a recorded decision). Operationally: the string `state-abstract` must not occur on any NON-COMMENT line of boot-inject.py outside the boot-instructions/stub emission text blocks (lines whose stripped form starts with `#` are exempt — comments are inert), and the literal `state-abstract.md` appears in the boot-instructions block (the read mandate). Declared residual: dynamically-constructed names are out of scope — a static suite guards drift, not deliberate obfuscation

**T04** — Child template CLAUDE.md exists
Condition: file exists at `^/.templates/child/CLAUDE.md`

**T05** — Child template CLAUDE.md has `root: true` and `codex:` in frontmatter
Condition: two sub-checks:
1. frontmatter contains `root: true`
2. frontmatter contains `codex:` key

**T05a** — Child template does NOT carry boot-core or backstop
Condition: `.templates/child/CLAUDE.md` contains none of: a `boot-core:` marker, the `=== BOOT INSTRUCTIONS ===` token, or the content canaries `Governance Primitives`, `ABSOLUTE HOLD`, `CONFIRMED HOLD`, `visibility-guard.sh`, `state-abstract.md` (one absence-canary per boot-core section, mirroring T02a's presence anchors — markerless copying of any section's content is the same defect). In-tree children receive governance via the ancestor walk; bundles get it materialized by `/bundle` step 4 — duplication into the template would double-deliver and drift.

**T06** — `.codex/start.md` exists and has `version:` in frontmatter
Condition: file exists, frontmatter has `version` key

**T06a** — `boot:cut` trim contract in `.codex/start.md`
Condition: three sub-checks (marker deletion re-inflates the boot payload toward the ~29.9 KB spill; an emptied eager section degrades boot to a warning):
1. A line-anchored `boot:cut` marker is present and matches the pattern `boot-inject.py` cuts on (`BOOT_CUT_RE`)
2. The eager section above the marker is non-empty
3. The eager section carries the Boot-Core pointer (anchors: `Boot-Core` and `boot-core:begin` both appear above the cut)

**T07** — `.state/start.md` exists and has `version:` in frontmatter
Condition: same

**T08** — `.gitignore` excludes `_`-prefixed items
Condition: file exists and contains a line whose stripped content is exactly `*` (the inverted-whitelist catch-all), exactly `_*`, or exactly `**/_*`. Literal line comparison — no regex semantics. (`/_*` does NOT satisfy: root-anchored, excludes `_`-items at repo root only.)

---

### Category B: Implicit Tiers

**T09** — All five implicit tiers exist
Condition: directories exist at `.codex/implicit/00-preboot/`, `01-infrastructural/`, `02-foundational/`, `03-standard/`, `04-supplementary/` (00-preboot added to the enumeration 2026-08-01 — closes the BL-07 omission class at the test layer)

**T10** — `.codex/implicit/01-infrastructural/01a-resolution/` contains `frontmatter.md` and `path-containment.md`
Condition: both files exist

**T11** — `.codex/implicit/01-infrastructural/01b-materialization/` contains `pref-resolve/start.md`, `codex-register/start.md`, `statusline/start.md`
Condition: all three files exist

**T12** — 02-foundational contains `identity-isolation.md`, `state-gravity.md`, `transient-gravity.md`
Condition: all three files exist

---

### Category C: Hooks

**T13** — All 13 hook scripts exist
Condition: these files exist in `.codex/implicit/01-infrastructural/01b-materialization/hooks/`:
`boot-inject.py`, `prefs-staleness-check.sh`, `memory-redirect-check.sh`, `visibility-guard.sh`, `containment-guard.sh`, `gravity-guard.sh`, `remote-guard.sh`, `audit-immutability-guard.sh`, `claude-md-immutability-guard.sh`, `codex-edit-notify.sh`, `trace-logger.sh`, `session-close.sh`, `subagent-conformance.sh`

**T14** — Hook registration is bidirectionally complete
Condition: two sub-checks (dynamic — a 14th script added to `hooks/` must not land invisible):
1. Every script filename from T13 appears in a `"command"` value somewhere in the hooks section of `.claude/settings.json`
2. Every `*.sh` and `*.py` file directly in the `hooks/` directory (exclude `__pycache__/`) appears in a `"command"` value — no unregistered stragglers; other file types are out of scope

**T14a** — boot-inject.py is bound to SessionStart
Condition: in `.claude/settings.json`, `boot-inject.py` appears in a command under `hooks.SessionStart`. (Binding only — emission ORDER is deliberately unasserted: other SessionStart hooks are observed to emit first without harm, and no ordering requirement has been verified.)

**T15** — `visibility-guard.sh` covers all 6 tool types
Condition: in `.claude/settings.json`, `visibility-guard.sh` appears in matchers that collectively cover `Read`, `Glob`, `Grep`, `Bash`, `Write`, `Edit`. Matcher semantics: treat each matcher as a regex; a tool is covered if the regex matches the full tool name (an empty or wildcard matcher covers all tools)

**T16** — `containment-guard.sh` and `gravity-guard.sh` match `Write|Edit`
Condition: both scripts appear in a PreToolUse entry with matcher containing `Write` and `Edit`

**T17** — `remote-guard.sh` matches `Bash`
Condition: appears in a PreToolUse entry with matcher containing `Bash` (structural binding only; behavioral push-block coverage remains BL-24 / chooks territory)

**T18** — Every hook and statusLine command path in `.claude/settings.json` points to a file that exists
Condition: extract ALL `"command"` values from the hooks section plus `statusLine.command` — not just those starting with `bash `; the boot hook is now a quoted-python command and must not escape this check. Tokenize each with `shlex.split` (posix), expand `$CLAUDE_PROJECT_DIR`/`${CLAUDE_PROJECT_DIR}` to `^` and apply `expanduser` to every token, then verify: the interpreter exists (absolute → on disk; non-absolute-but-path-bearing → resolve against `^`, never `shutil.which`; bare name → `shutil.which`); the script argument — the first NON-FLAG token after the interpreter — exists on disk, resolving non-absolute tokens (with or without a separator) against `^`, no other fallback — not found → FAIL as script-missing (interpreter forms `-c` and `-m` exempt the command from the script check — inline code and module names are not filesystem paths; drop leading `VAR=value` assignment tokens, matching `^[A-Za-z_][A-Za-z0-9_]*=`, before selecting the interpreter). Redundant with T48b's apex row by design — this is the cheap first layer.

---

### Category D: Explicit Commands

**T19** — Every explicit command folder is registered as a skill shim
Condition: enumerate the folders in `.codex/explicit/` (exclude the `start.md` file). For each folder `F`, `.claude/skills/F/SKILL.md` must exist (`[FAIL]` if missing), and its description line — the first non-empty body line after the frontmatter, which must begin with the literal `[codex] ` (shim frontmatter carries only `name:`, never a `description:` key) — must equal `[codex] ` + the `short-desc` from `.codex/explicit/F/start.md` (surrounding quotes stripped) — mismatch = `[WARN]` (stale materialization; cboot re-run pending); a description line NOT beginning `[codex] `, or a `description:` frontmatter key present, = `[FAIL]` (registration-shape defect — cboot always writes the prefix, so its absence means hand-editing, never staleness; deliberate tightening 2026-08-02); a missing core-floor command = `[FAIL]`. This is registration completeness — it replaces a brittle hardcoded folder list, so new commands (e.g. `ask`) are covered automatically. Core commands that must be present: `ask`, `audit`, `backup`, `break-glass`, `break-glass-qa`, `bundle`, `checkWinTasks`, `mileqa`, `milestone`, `new-project`, `pause`, `purge`, `rebuild`, `scrub`, `test-bench`, `test-burn`, `test-safe`, `unpause` (the full 2026-08-01 inventory — this floor moves only by deliberate edit).

**T20** — Each explicit command folder has a `start.md`
Condition: `start.md` exists in each folder enumerated in T19

---

### Category E: Reactive & Reflexive

**T21** — Reactive modules exist: `.codex/reactive/sqlite/start.md`, `.codex/reactive/backlog-reprint/start.md`
Condition: both files exist

**T22** — `.codex/reactive/sqlite/sqlite.py` exists
Condition: file exists

**T23** — Reflexive modules exist under `.codex/reflexive/`: `codex-test-on-edit/start.md`, `contract-conformance/start.md`, `session-compliance/start.md`
Condition: all three files exist

---

### Category F: State Structure

**T24** — `.state/memory/start.md` exists
Condition: file exists

**T25** — Auto-memory index integrity
Condition: three sub-checks (replaces the retired `user.md` — the memory model moved to typed auto-memory files; the user profile lives in `state-abstract.md`):
1. Positive: `.state/memory/MEMORY.md` exists (the auto-memory index)
2. Integrity: every markdown link target in `MEMORY.md` (`[title](file.md)`) resolves to an existing file in `.state/memory/`
3. Reverse: memory `.md` files on disk (excluding `start.md`, `MEMORY.md`, `state-abstract.md`) that are NOT linked from `MEMORY.md` are a `[WARN]` regardless of body content — the tombstone rationale (files declaring themselves deprecated/superseded, awaiting deletion) explains why this is WARN rather than FAIL; it exempts nothing

**T26** — Decision memories exist as typed files
Condition: at least one `decision_*.md` file exists in `.state/memory/`, and every `decision_*.md` present is linked from `MEMORY.md` — `[FAIL]` for an unexplained orphan; `[WARN]` if the orphan's file contains, case-insensitively, any of `deprecated`, `superseded`, or `tombstone` (a deliberate tombstone; this rule applies to orphans only — linked files are never body-scanned). (Replaces the retired monolithic `decisions.md`.)

**T27** — `.state/memory/state-abstract.md` exists
Condition: file exists

**T28** — `.state/work/start.md` exists
Condition: file exists

**T29** — `.state/work/` contains `backlog.md`, `platform.md`, `architecture.md`, `boundaries.md`, `enhancements.md`
Condition: all five files exist

**T30** — `.state/tests/start.md` and `.state/tests/audits/start.md` exist
Condition: both files exist

**T30a** — /mileqa report convention under `.state/tests/mileqa/`
Condition: if `.state/tests/mileqa/` is absent, `[SKIP]` (no runs yet). If present, two sub-checks:
1. Every subdirectory name matches `^\d{8}-\d{4}$` (run-timestamp convention)
2. `.state/tests/mileqa/` itself has a `start.md` (every-folder convention); run subdirectories (`YYYYMMDD-HHMM/`) are report data and are NOT required to carry one

**T31** — `.state/traces/start.md` exists
Condition: file exists

**T31a** — `.state/plans/start.md` exists
Condition: file exists

**T31b** — `.state/pauses/start.md` exists
Condition: file exists (live `/pause`/`/unpause` surface)

**T32** — `.state/bundles/start.md` exists
Condition: file exists

**T33** — `.state/prefs.json` is valid JSON if present (optional override layer)
Condition: the file is an optional, sparse instance-override input to the pref cascade (`pref-resolve/start.md`: each layer is sparse; missing keys fall through) — absence is normal and cboot resolves without it. If present, it MUST parse as JSON — `[FAIL]` on malformed content (a broken override layer corrupts materialization silently). If absent, `[PASS]` with note `(optional layer absent — cascade falls through)`. The materialization OUTPUT is what T37/T38 validate.

---

### Category G: Preference System

**T34** — `.codex/pref-options.json` exists and is valid JSON
Condition: file exists, parses as JSON

**T35** — `.codex/prefs.json` exists and is valid JSON
Condition: file exists, parses as JSON

**T36** — Every key in `prefs.json` exists in `pref-options.json`
Condition: for each key in `.codex/prefs.json`, that key exists in `.codex/pref-options.json`

**T37** — `^/.state/prefs-resolved.json` exists and is valid JSON with `_meta`
Condition: the resolved file lives at `^/.state/prefs-resolved.json` (state, NOT `.codex/`). If it exists, parse as JSON, verify it contains `_meta.generated`. If it doesn't exist, `[WARN]` (cboot.py may not have run).

**T38** — Every key in `prefs-resolved.json` (except `_meta`) exists in `pref-options.json`
Condition: if T37 passed, for each non-`_meta` key in resolved file, verify it exists in `pref-options.json`. If T37 was WARN or FAIL, `[SKIP]` (upstream not PASS).

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
Condition: if T46 passed, verify the path ends with `.state/memory` and resolves to `^/.state/memory`. If T46 was skipped or FAILED, `[SKIP]` this too.

**T48** — Auto-memory is landing in `.state/memory/` and NOT in user profile
Condition: Two checks, both must pass:
1. **Positive:** `.state/memory/MEMORY.md` exists OR at least one `.md` file (besides `start.md`) exists in `.state/memory/`. This confirms auto-memory is writing to the correct location. If no memory files exist at all, `[WARN]` — the system may not have accumulated any memories yet (expected on first boot).
2. **Negative:** Run `bash -c "ls ~/.claude/projects/*/memory/*.md 2>/dev/null"` and check whether any returned file's project directory name EXACTLY equals the slug of `^` (rule: every character outside `[A-Za-z0-9]` in the absolute path is replaced by `-` — observed for `/`, `.`, `~` on this machine; the worked example is authoritative for this suite: `/mnt/claudette` → `-mnt-claudette`). Exact equality only — never prefix, substring, or leaf-name matching: sibling slugs such as `-mnt-claudette--plugins-cppc` are other session roots and must not match. If memory files exist under the exact-slug directory, `[FAIL]` with the external path — auto-memory is leaking. If no match, this check passes.
Overall: PASS requires positive check pass + negative check pass. WARN if positive is uncertain but negative passes. FAIL if negative check finds leakage.

**T48a** — No broken `Bash(command:...)` permission syntax anywhere
Condition: scan set = every `settings.json` and `settings.local.json` whose parent directory is named `.codex` or `.claude`, anywhere under `^/` including `.templates/` (a broken rule in the template would re-seed every new child), AFTER applying the skip list, matched against ANY path segment at any depth: `_`-prefixed segments (visibility-guard territory), `.state`, `.tmp` (disposable rigs). Settings files under other parent directories (e.g. `BravoGroup/Bravo/.act/config/settings.json`) are DELIBERATELY out of scope — foreign-tool settings are not Claude permission surfaces. For each in-scope file, read it and check whether the literal string `Bash(command:` appears. The legacy form `Bash(command:xxx*)` matches nothing — the colon is treated as a literal character — so any rule in this form is dead weight (allow lists don't auto-approve; deny lists don't block). Canonical form is `Bash(xxx:*)`. See `.state/memory/feedback_permission_syntax.md`.
- **PASS** if zero files contain `Bash(command:`.
- **FAIL** if any file contains it — list each offending file and the count of occurrences.
The scan-set rule above is complete — nothing else, no judgment calls. Enumerate with `os.walk` or equivalent that traverses dot-directories; wildcard engines that exclude hidden segments by default are non-conforming (they would silently drop `.templates/`).

**T48b** — All `.claude/settings.json` hook commands resolve to existing files
Condition: Glob `**/.claude/settings.json` AND `**/.claude/settings.local.json` under `^/` (local files declare hooks that execute identically at session start) — the enumeration MUST traverse hidden intermediate segments (e.g. `.templates/`); engines that exclude dot-segments from `**` by default are non-conforming as configured. Skip `_`-prefixed, `.tmp`, and `.state` path segments AT ANY DEPTH (`_` = visibility-guard territory; `.tmp` = rigs exist to be broken, scratch content must not fail the suite; `.state` = snapshots are non-live — bundle outputs are validated at bundle time by `/bundle` step 4 and the T60.1 floor). For each file, parse as JSON. For every command string in `hooks` (walk all events × matchers × hooks) and in `statusLine.command`:
1. Tokenize the command respecting shell quoting (use `shlex.split` in posix mode) FIRST, then per token expand `$CLAUDE_PROJECT_DIR` / `${CLAUDE_PROJECT_DIR}` to the OWNING settings file's project root (the directory containing that `.claude/`) and apply `expanduser`. Tokenize-before-expand is deliberate — expanding into the raw string first would fragment tokens if the expansion value contains whitespace; this matches T18's order (the two layers are step-identical by design). The env-var form is the mandatory bundle form (BL-19/BL-26); unexpanded it is neither absolute nor a bare interpreter and would silently escape the checks below, making the guard vacuous.
2. Identify tokens: drop leading `VAR=value` assignment tokens (matching `^[A-Za-z_][A-Za-z0-9_]*=`); the interpreter is the first remaining token; the script argument is the first NON-FLAG token after it (leading-`-` tokens are flags; interpreter forms `-c` and `-m` exempt the command from the script check — inline code and module names are not filesystem paths).
3. **Malformed-shape check:** apply the regex `[A-Za-z]:[\\/].*[A-Za-z]:[\\/]` to each step-1 token INDIVIDUALLY; reject the command if any single token matches (a token may contain at most one drive-letter root). Do NOT apply the regex to the whole command string — a legitimate Windows interpreter+script pair has one drive letter per token and must pass. Catches the `C:/root/"C:/interpreter"` class of bug.
4. **Interpreter check:** if absolute (starts with `/` or matches `^[A-Za-z]:[\\/]`), verify it exists on disk. If non-absolute but containing a path separator, resolve against the owning settings file's project root — exists there → pass, else FAIL (never route path-bearing tokens through `shutil.which`: its cwd-relative fallback makes the verdict depend on runner cwd). If a bare name (`bash`, `python`, `python3`), verify `shutil.which` resolves it.
5. **Script check:** if a script argument is present, verify it exists on disk — absolute as-is; a non-absolute token (with or without a path separator) resolves against the owning settings file's project root; no other fallback — not found there → FAIL (script missing).
- **PASS** if every command in every file tokenizes cleanly and all referenced paths exist.
- **FAIL** with `<file>: <hook_event>: <command>` for each offender, plus the specific failure reason (malformed / interpreter missing / script missing).

Catches the hook-propagation regression class directly: had T48b existed, the 26-child breakage from the boot-inject.py migration would have been caught at audit time instead of session-start time. The step-1 expansion is what makes the `$CLAUDE_PROJECT_DIR` env-var form actually validated — the pre-2026-08-01 spec claimed this coverage while `shlex` left the token non-absolute and the checks silently skipped it (a vacuous guard). Declared residual: this is one-level static resolution — a registered wrapper script that internally execs a dead path passes; wrapper internals are behavioral territory (chooks / the BL-24 class).

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

**T50a** — `.state/work/start.md` file table matches disk
Condition: every file named in the Files table of `.state/work/start.md` exists in `.state/work/` — the canon-vs-disk drift class surfaced 2026-08-01: T25/T26 were spec-stale false-fails (checks rewritten in v3); T29 was live drift (disk missing a template-canonical file — repair the disk, never relax the check). Missing listed files are a `[FAIL]`; extra unlisted `.md` files on disk (excluding `start.md`, the every-folder convention file) are a `[WARN]` (canon behind reality).

---

### Category K: Scripts & Templates

**T51** — `cboot.py` exists at project root
Condition: file exists at `^/cboot.py`

**T52** — `scrub.py` exists in `.codex/explicit/scrub/`
Condition: file exists

**T52a** — scrub pre-push hook: source + wiring
Condition: three sub-checks. Wiring is `core.hooksPath`, NOT a copy into `.git/hooks/` — cboot points every repo at the codex hooks dir:
1. `.codex/explicit/scrub/hooks/pre-push` exists and is non-empty (the fail-closed per-commit push gate)
2. `git -C ^ config core.hooksPath` (mandated read-only command) resolves, relative to the repo, to `.codex/explicit/scrub/hooks` — `[WARN]` if unset or wrong (that is the real cboot-re-run wiring gap); normalize before comparing: an absolute path equal to `^/.codex/explicit/scrub/hooks` is equivalent
3. Inverted legacy probe: a live non-sample `^/.git/hooks/pre-push` EXISTS → `[WARN]` — `core.hooksPath` silently hides it (matches cboot's own displaced-hooks warning)

**T53** — `purge.py` exists in `.codex/explicit/purge/`
Condition: file exists

**T54** — `bootstrap-child.py` exists in `.codex/explicit/new-project/`
Condition: file exists

**T55** — `.templates/child/` exists and contains `CLAUDE.md`
Condition: directory and file exist (redundant with T04 by design — cheap second layer)

**T56** — `.templates/child/.state/` has the full template manifest
Condition: `memory/`, `work/`, `tests/`, `traces/`, `plans/`, `bundles/`, `pauses/` all exist under `.templates/child/.state/`, AND `.templates/child/.state/prefs.json` exists (a bootstrap regression dropping any of these would previously go unnoticed)

**T57** — `.templates/child/.gitignore` exists
Condition: file exists

---

### Category L: Frontmatter Contracts & Version Floors

These checks validate declaration shape and anchors only. Declaration truthfulness (declared vs. actual writes) is verified at runtime by the `contract-conformance` reflexive module — an observer, not a gate; static body-vs-contract analysis is deliberately out of scope here.

**T58** — Every explicit command declares a `writes:` contract
Condition: enumerate every `.codex/explicit/*/start.md` (generalized 2026-08-01 — the fixed bundle/rebuild/new-project trio missed real offenders). `[FAIL]` for any command whose frontmatter has no `writes:` key, or whose `writes:` value is not a YAML list (null, scalar, or mapping values are undeclared contracts in disguise; an empty list is valid). Genuinely read-only commands must declare `writes: []` explicitly.

**T59** — Empty `writes:` only for declared read-only commands
Condition: commands with `writes: []` must be in the read-only set (`test-bench`, `unpause`, `checkWinTasks`); any command OUTSIDE that set with an empty or absent-value `writes` is a `[FAIL]` — the `writes: []` regression class (bundle, rebuild, new-project, mileqa, ask et al. all carry write obligations). The read-only set moves only by deliberate edit, same doctrine as T19 — a new `writes: []` command FAILing here is the review gate working.

**T60** — Hardened-command version floors
Condition: three sub-checks (a rollback below these floors silently revives pre-hardening semantics):
1. `bundle/start.md` frontmatter `version >= 3` AND body references the boot-core region copy (`boot-core:begin`) — step-4 materialization intact
2. `purge/start.md` frontmatter `version >= 9` AND body contains `allowlist` AND `CONFIRMED HOLD` appears in the file — the nuclear gate stays gated
3. `mileqa/start.md` frontmatter `version >= 5` AND `writes:` includes `^/.state/tests/mileqa/`

---

### Category M: Worker Modes & `/ask`

**T61** — `/ask` command is registered and current
Condition: `.codex/explicit/ask/start.md` exists; its frontmatter declares `isolation: subagent`, a non-empty `short-desc`, and a `writes:` that includes `^/.tmp/` (the hard-mode out-of-band request channel T63 depends on); and the shim `.claude/skills/ask/SKILL.md` exists.

**T62** — `roots.db` schema (if present)
Condition: SKIP if `.state/roots.db` is absent — meaning the inventory has never run here. Do NOT read that absence as "a rebuildable cache is missing, no matter": the `roots`/`meta` tables are rebuilt every boot, but `agent_optin` and `agent_registry` (see T64) are **durable** — they hold decisions a human made once and the claims every file in `^/.claude/agents/` depends on, and nothing regenerates them. If present, open it STRICTLY READ-ONLY via `sqlite3.connect("file:<abs-path>?immutable=1&mode=ro", uri=True)` — `immutable=1` is the operative flag: a plain `mode=ro` open of a WAL-mode db still creates/updates the `-wal`/`-shm` side files (mode=ro governs only the main file), itself a read-only-contract breach; `mode=ro` stays as the belt because SQLite silently ignores unrecognized URI parameters. Do NOT open through the sqlite factory here: its `PRAGMA journal_mode=WAL` persists a journal-mode flip into the db file. Stated caveats: with change detection disabled the verdict is undefined if anything writes roots.db during the open, and committed-but-uncheckpointed `-wal` frames from a crashed writer are invisible (stale snapshot) — keep the connection short-lived: open, check, close. Verify the `roots` table contains AT LEAST the columns `name, abs_path, rel_path, parent_path, depth, is_apex, contains_roots` (superset semantics — the live schema also carries `id` and `generated_at`) and exactly one row with `is_apex = 1`. An error opening the database read-only is a `[FAIL]` reporting the exception text.

**T63** — `/ask` hard mode is injection-safe
Condition: in `ask/start.md`, the `hard` branch delivers `<request>` **out-of-band as a file** — written with the Write tool into `.tmp/` and run via `python cboot.py … --exec-file '<reqfile>'` — so the request bytes never appear on a shell command line. FAIL if the branch puts `<request>` into shell syntax in any form: a `--exec "<request>"` interpolation, or a heredoc (`--exec - <<'…'`) whose fixed delimiter is itself a public injection vector.

**T64** — Addressable agents agree with the durable registry
Condition: SKIP if `.state/roots.db` is absent, or if it is present but has no `agent_registry` table (`SELECT name FROM sqlite_master WHERE type='table' AND name='agent_registry'`) — the feature has never run here. Otherwise open the db STRICTLY READ-ONLY exactly as T62 mandates: `sqlite3.connect("file:<abs-path>?immutable=1&mode=ro", uri=True)`, NOT through the sqlite factory (its `PRAGMA journal_mode=WAL` persists a journal-mode flip into the file, and a plain `mode=ro` open of a WAL db still creates `-wal`/`-shm`). Short-lived: open, read, close. An error opening read-only is a `[FAIL]` reporting the exception text.

CURRENT = the rows of `SELECT rel_path, agent_name, agent_file FROM agent_registry WHERE valid_to IS NULL`. **CURRENT is the sole authority on which files cboot owns** — ownership is this lookup, never an inference from a file's contents. A file's marker is checked below only to detect tampering with a file the registry already claims; it never adds a file to CURRENT and never removes one. Read a file in `^/.claude/agents/` with `errors="replace"` and treat an unreadable one as "no marker" — a file that cannot be decoded is a reporting matter, never a verdict on ownership.

Seven sub-checks:
1. **Apex is never addressable.** No CURRENT row has `rel_path = '.'`. `[FAIL]` — the apex IS the session, not a subagent.
2. **Every claim has a decision.** `agent_optin` exists, and every CURRENT `rel_path` has a row there with `enabled = 1`. `[FAIL]` per claim with no decision or a decision of 0 — a claim the apex cannot justify means the two tables have drifted.
3. **Every claim has its file.** `^/<agent_file>` exists for each CURRENT row. `[WARN]` per missing file, not `[FAIL]`: the registry row is committed before the file lands, so a crash in between is a designed-for state that the next boot heals by writing the file. Report it as "rerun cboot".
4. **Claimed files still carry their marker.** For each CURRENT row whose file exists, its first non-blank line after the frontmatter block must fullmatch `<!-- cboot:agent root=(?P<root>"(?:[^"\\]|\\.)*") generated="[^"]*" -->` with `json.loads(root)` equal to the row's `rel_path`. Mechanically: strip a leading UTF-8 BOM; if the text up to the first `\n`, stripped, is exactly `---`, find the closing fence with `re.search(r"^---[ \t]*$", rest, re.M)` (no closing fence = the whole text is the body) and start the body after it; take the body's first line that is non-blank when stripped; `re.fullmatch` the marker on it. `[WARN]` per file that fails — cboot's own response is to warn and leave the file untouched, never to overwrite, so a diverged file is a report, not a defect in the tool.
5. **Unclaimed files are hand-authored and out of scope.** Every `*.md` directly in `^/.claude/agents/` that no CURRENT row claims gets one `[WARN]` line naming it — including one that carries a well-formed marker, which confers nothing. cboot and purge both leave these alone. This is inventory, never `[FAIL]`.
6. **`roots` mirrors the registry.** First confirm the `roots` table exists (a boot that crashed between its `DROP TABLE` and `CREATE TABLE` leaves it absent — `[FAIL]` this sub-check alone with `roots table missing — rerun cboot` rather than letting the query raise). Otherwise `SELECT rel_path, agent_name, agent_file FROM roots WHERE agent_enabled = 1` must equal the subset of CURRENT whose files exist on disk — same `rel_path` set, same `agent_name` and `agent_file` for each. `[FAIL]` listing each rel_path enabled-without-a-current-row, current-without-being-enabled, or disagreeing. A claim whose file is missing is deliberately absent from the mirror (an @name is advertised only once it exists), so sub-check 3's WARN set is excluded here rather than double-reported.
7. **No staging leftovers.** No `*.md.tmp` directly in `^/.claude/agents/`. `[WARN]` per file — cboot and purge both sweep these, so one at rest means the last sweep did not run.

Parent verdict is the worst across sub-checks; print offenders only. Stated caveat, inherited from T62: with `immutable=1` the verdict is undefined if anything writes roots.db during the open, and uncheckpointed `-wal` frames from a crashed writer are invisible.

---

## Execution Notes

- HARD CONTRACT — 100% read-only: the ONLY write this suite may perform is its own log under `.state/tests/explicit/test-safe/`. Never execute project scripts or hooks, never open a database writable (see T62's `mode=ro`), never touch git state. Static content checks only.
- Use the Read tool to check file existence and contents. Do NOT use Bash for file reads — except where a test's Condition mandates specific machinery (e.g. T48's `ls`, T52a's `git config`, T62's `mode=ro` sqlite open, T18/T48b's `shlex.split` + `shutil.which`); the mandate in a test's Condition is the authority, this list is illustrative.
- Dependent tests: when a test conditions on an upstream test and the upstream verdict is not among the enumerated branches, print `[SKIP]` citing the upstream test ID and its verdict.
- Use Glob to verify directory contents efficiently.
- For JSON validation, read the file and check if the content is well-formed JSON.
- Count passes, fails, warns, and skips separately. Report all four in the summary.
- For tests with numbered sub-conditions (1, 2) or labeled sub-checks (Positive, Negative): print each sub-result as an indented line beneath the parent. The parent's overall verdict is the worst of its sub-conditions (FAIL > WARN > PASS). The same worst-of rule governs EVERY per-item iterated test (e.g. T13, T14, T18, T19, T20, T26, T36, T38, T48a, T48b, T50a, T56, T58, T59): the parent verdict is the worst across items; print offenders only. Only count the parent in the summary totals, not the sub-checks.
- Write the full log to `.state/tests/explicit/test-safe/` with timestamp filename.
