# Command Reference

All commands can be invoked by name in conversation ("audit this project", "scrub full") or as slash commands (`/pause`, `/purge all`). Claude reads the command's protocol from the codex and follows it.

## test-safe -- Structural Validation

Read-only. 66 checks across 13 categories. Safe to run anytime, makes no changes (writes only a log file).

```
test-safe
```

**What it checks:**
- Boot chain and structure (CLAUDE.md, codex, state)
- All 14 hook scripts exist and are registered
- Hook matcher coverage (visibility-guard covers all 6 tool types, etc.)
- All 18 command folders exist with start.md manifests
- Reactive and reflexive modules present
- State structure (memory, work, tests, traces files)
- Preference system integrity (schema, cascade, resolved output)
- Audit specs present
- Platform bridge (settings.json generated, auto-memory configured correctly)
- Cross-reference integrity (no stale references between files)
- Scripts and templates present
- Frontmatter contract spot-checks

**Output:** `[PASS]`, `[FAIL]`, `[WARN]`, or `[SKIP]` per test, with a summary. Log written to `.state/tests/explicit/test-safe/`.

## test-burn -- Functional End-to-End Tests

**Modifies the instance.** Creates temporary files, exercises commands, cleans up. Run `test-safe` first.

```
test-burn
```

**What it does:**
1. Creates a child project, verifies its structure
2. Runs scrub in full mode
3. Creates fake trace, boot, session, and memory files
4. Runs purge (default) and verifies only transient files were removed
5. Runs purge all and verifies memory files were also removed
6. Deletes the test child project and verifies cleanup

**30 steps (B01–B24 incl. lettered sub-steps) across 7 phases** — Phase 7 is hook behavioral tests. Run `cboot.py` after test-burn to restore any generated artifacts that were purged.

## scrub -- Secrets and PII Scanner

Scans files against a pattern file for sensitive content (API keys, tokens, credentials, PII).

```
scrub              # scan staged git changes (diff mode)
scrub full         # scan all tracked files
scrub <path>       # scan a specific file or directory
```

**Pattern file:** `.codex/explicit/scrub/patterns.txt` -- one regex per line, `#` for comments.

**Non-git projects:** If the project is not a git repository, `diff` and `full` modes fall back to scanning all files in the project directory.

**Output:** Report in `.state/tests/explicit/scrub/` with file, line number, and matched pattern. Exit 0 = clean, exit 1 = matches found.

**Automated enforcement:** A fail-closed pre-push hook (`.codex/explicit/scrub/hooks/pre-push`) is wired into every repo via `core.hooksPath` by `cboot` (BDRY-03, done 2026-07-30). Pushes are blocked until a per-commit scrub of the pushed range passes; `scrub:allow` is the escape hatch. Running scrub manually before large pushes is still recommended to avoid gate surprises.

## audit -- Quality Verification

Runs quality specs against a project using disposable sub-agents (separate Claude instances that read the project and report findings).

```
audit                           # all specs, current project
audit architecture              # specific spec
audit my-api                    # all specs, child project
audit my-api architecture deep  # full invocation with depth
```

**Depth tiers:**

| Depth | What It Covers |
|-------|---------------|
| shallow | Structure and surface configuration only |
| standard | Key source files, patterns, conventions |
| deep | Broad cross-referencing, coherence assessment, full analysis |

**Output:** Findings written to `.state/tests/audits/YYYYMMDD-HHMM/`. Audit records are immutable -- the `audit-immutability-guard.sh` hook prevents modification after creation.

## mileqa -- Pre-Milestone Holistic QA

**Commits to a feature branch** (creates one if on main -- invoking mileqa authorizes its branch-local commits; it never pushes). Iterative multi-agent QA gate, typically run before `/milestone`.

```
mileqa
mileqa <scope>
```

**What it does:**
1. Checkpoint-commits pending work on the feature branch
2. Fans out a blind QA panel -- cold readers (reconstruct functionality from the artifacts alone), adversaries (push every seam), plus lenses fit to the subject -- via multi-agent workflows
3. Adversarially verifies every finding, then triages critical/high/medium/low
4. Fixes all critical + high in-round with proving tests; backlogs deliberate deferrals
5. Repeats with a rotated/expanded panel -- up to 3 rounds or until a full pass is all medium-or-less

**Exit states:** CLEAN (all verified findings <= medium; milestone gate open), EXHAUSTED (3 rounds, confirmed critical/high still emerging -- not a pass; the gate stays closed and only the user can open it; the report carries the cross-round defect-class trajectory: narrowing = bounded residuals, flat/widening = redesign signal), ESCALATION (finding exceeds scope; user rules, loop resumes).

**Output:** Per-round reports + summary in `.state/tests/mileqa/YYYYMMDD-HHMM/`; a commit at every checkpoint and round.

## new-project -- Child Project Scaffolding

Creates a new child project with the standard Claudette2 structure.

```
new-project my-api
```

**Creates:**
```
my-api/
    CLAUDE.md              (root: true, codex: ^/^/.codex)
    .gitignore
    .claude/
        settings.local.json    (auto-memory configured)
    .state/
        start.md
        prefs.json
        memory/
            start.md
            decisions.md
        work/
            start.md
            backlog.md
        tests/
            start.md
        traces/
            start.md
```

The child inherits the parent's codex automatically. It has its own state (memory, backlog, preferences) that is isolated from the parent.

## pause -- Save Session Context

Captures current session state for later resumption.

```
pause
```

**Creates:** `.state/pauses/YYYYMMDD.N/` with two files:
- `context.md` -- what you were doing, key decisions, open questions
- `state.md` -- files viewed/modified, pending work

The goal is that another Claude instance with no memory of the session can resume from these files alone.

## unpause -- Restore a Paused Session

```
unpause
```

Lists the 3 most recent pauses, asks which to restore, reads the pause files, and re-establishes context. Outputs a structured summary of what was captured.

## purge -- Clean Transient State

```
purge              # clean transient artifacts (safe)
purge <project>    # clean a child project's transient state
purge all          # nuclear reset: transcripts, memory, work, .tmp/ (requires confirmation)
```

**Default scope** (bare `purge`) removes:
- `.claude/` session files (`.jsonl`, `.md`) -- preserves `settings*.json`
- `.claude/skills/` and `.claude/agents/` (regenerated at next boot)
- `.state/prefs-resolved.json` (regenerated at next boot)
- `.state/tests/` transient outputs (not audits, not boot reports)
- **keep-recent**, pruned to the newest 5: `.state/traces/` and `.state/tests/boot/`

Bare purge KEEPS everything precious -- transcripts, pauses, memory, work, plans,
bundles, and loose `.tmp/` buffers. Sandbox rigs and stray scratch files are
reported, never deleted.

**`purge all`** is a nuclear reset (destructive; Confirmed Hold -- single confirmation).
Beyond the default scope it also removes:
- the user-level transcript store `~/.claude/projects/<slug>/`
- `.state/memory/`, `.state/work/`, `.state/plans/`, `.state/bundles/` contents
- `.state/pauses/` contents
- keep-recent dirs wiped entirely (not pruned)
- the **entire `.tmp/`** -- loose buffers, `.tmp/sandbox/` rigs, and every subdir

**Never purged (any scope):** `.codex/`, `CLAUDE.md`, audit records, `_`-prefixed
items, and every `start.md` manifest -- so `.state/pauses/`, `.state/bundles/`, and
the other `.state/` dirs always survive as empty shells even under `purge all`;
`cboot.py`, `ctest.py`, `chooks.py`.

## bundle -- Package for Portability

Creates a standalone copy of a child project by inlining all inherited codex content.

```
bundle              # bundle current child project
bundle my-api       # bundle a specific child project
```

**Output:** `.state/bundles/YYYYMMDD-HHMM-<project>/`

The bundled project can operate independently without the parent Claudette2 instance.

## rebuild -- Restructure from Audit Findings

Interactive, multi-phase restructuring of a project based on prior audit results. Requires a completed audit first.

```
rebuild my-api
```

**Phases:**
0. Pre-flight (optional deep audit)
1. Analysis and questions
2. Requirements refinement
3. Specification (initial draft, then final)
4. Rebuild (actual output)

**Output:** `^/<project>-rebuild-YYYYMMDD-HHMM/` as a sibling of the target project.

## Common Workflows

### Daily development

```
python cboot.py              # start session
[work normally]
pause                        # end of day
```

Next day:

```
python cboot.py
unpause                      # picks up where you left off
```

### Before pushing code

```
scrub                        # check staged changes for secrets
# or
scrub full                   # check all tracked files
```

### Setting up a new sub-project

```
new-project my-api           # scaffold
audit my-api                 # baseline check
```

### Periodic health check

```
test-safe                    # 66 structural checks
```

### Deep verification after changes

```
python ctest.py              # bootstrap verification (outside Claude)
python chooks.py             # hook tests (outside Claude)
test-safe                    # structural validation (inside Claude)
test-burn                    # functional end-to-end (inside Claude)
python cboot.py              # re-boot to restore generated artifacts
```

## Read Next

| Document | When to Read It |
|----------|----------------|
| [README.md](README.md) | Overview and quick start |
| [README-concepts.md](README-concepts.md) | Governance primitives, memory types, nesting |
| [README-testing.md](README-testing.md) | Test infrastructure details |
