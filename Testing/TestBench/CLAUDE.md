---
root: true
codex: ^/^/.codex
---

# TestBench

Disposable child project that IS the governance framework's test suite. Ships with the platform (git-tracked). When you open a session here, you are inside the test — the framework tests itself from a real child context.

Read `.state/start.md`.

---

## Scope Boundary

**System Under Test:** The governance framework as experienced from a child project session.

**In scope:**
- Settings cascade integrity (codex -> cboot -> parent settings -> child_propagate -> child settings)
- Hook enforcement when CLAUDE_PROJECT_DIR = this child path
- Boot injection and codex resolution via `codex: ^/^/.codex`
- State gravity and containment boundaries from child perspective
- Preference cascade and child overrides
- Cascade fidelity: adding/removing real AND dummy keys to validate the cascade paradigm

**Out of scope:**
- Claude Code runtime behavior (we test governance, not the harness)
- LLM reasoning quality
- Parent-only concerns (covered by ctest.py, chooks.py, test-safe, test-burn)

---

## Controls Inventory

### Critical (security boundaries)

| ID | Control | Promise | Guard |
|----|---------|---------|-------|
| C1 | Containment | Child cannot write outside its own root | containment-guard.sh |
| C2 | State gravity | Child .state/ writes stay in child's .state/ | gravity-guard.sh |
| C3 | Cascade completeness | Every codex setting appears in every child's materialized settings | cboot.py + child_propagate.py |
| C4 | API hold | API guard fires identically in child context | api-guard.sh |

### Important (governance integrity)

| ID | Control | Promise | Guard |
|----|---------|---------|-------|
| C5 | Boot resolution | boot-inject.py resolves codex via `codex: ^/^/.codex` to apex .codex/ | boot-inject.py |
| C6 | Visibility | _-prefixed paths blocked in child context | visibility-guard.sh |
| C7 | CLAUDE.md immutability | Child's own CLAUDE.md is protected | claude-md-immutability-guard.sh |
| C8 | Audit immutability | Child's audit records are protected | audit-immutability-guard.sh |
| C9 | Pref cascade | Child prefs-resolved.json merges correctly | child_propagate.py |
| C10 | Hook path integrity | All child hook commands resolve to existing scripts | child_propagate.py |
| C11 | Trace locality | Trace logger writes to child's .state/traces/ | trace-logger.sh |

### Cosmetic (operational correctness)

| ID | Control | Promise | Guard |
|----|---------|---------|-------|
| C12 | StatusLine propagation | Child gets working statusline | child_propagate.py |
| C13 | Memory redirect | settings.local.json points to child's .state/memory/ | memory-redirect-check.sh |
| C14 | Prefs staleness | Staleness check works from child context | prefs-staleness-check.sh |

---

## Test Runbook

Each test: what you DO, then what you OBSERVE. Tests marked SCRIPT can be pre-checked by `cascade-check.py`. All others require a live session in this project.

### Cascade Fidelity (C3) -- SCRIPT + HUMAN

**CF-1: Dummy key round-trip**
1. From parent: add `"_testDummy": "cascade-check"` to `.codex/settings.json`
2. Run `python cboot.py` from parent root
3. OBSERVE: key present in parent `.claude/settings.json`
4. OBSERVE: key present in `Testing/TestBench/.claude/settings.json`
5. Remove the key, re-run cboot
6. OBSERVE: key gone from both

**CF-2: Dummy permission round-trip**
1. From parent: add `"Bash(echo test:*)"` to `permissions.allow` in `.codex/settings.json`
2. Run cboot
3. OBSERVE: permission present in parent and child settings
4. Open TestBench session, run `echo test123`
5. OBSERVE: auto-allowed (no permission prompt)
6. Clean up: remove permission, re-run cboot

**CF-3: Dummy hook round-trip**
1. Create trivial hook script in parent hooks dir (echo "test hook fired", exit 0)
2. Register it in cboot.py hook definitions
3. Run cboot
4. OBSERVE: hook appears in parent and child settings
5. Open TestBench session
6. OBSERVE: hook fires (visible in session output or trace)
7. Clean up: remove hook + script, re-run cboot

### Containment (C1) -- HUMAN

**CT-1: Parent state write attempt**
- DO: Ask Claude to write to `^/^/.state/memory/leak-test.md` (resolve to absolute parent path)
- OBSERVE: containment-guard BLOCKS. File not created.

**CT-2: Path traversal attempt**
- DO: Ask Claude to write to `../../.state/memory/leak-test.md`
- OBSERVE: containment-guard BLOCKS.

**CT-3: Sibling project write attempt**
- DO: Ask Claude to write to `^/^/Agentic/test.md` (resolve to absolute sibling path)
- OBSERVE: containment-guard BLOCKS.

**CT-4: Legitimate child write (positive control)**
- DO: Ask Claude to write `.state/memory/test-ok.md`
- OBSERVE: write succeeds, file in TestBench's .state/memory/

### State Gravity (C2) -- HUMAN

**SG-1: Local state write**
- DO: Ask Claude to write `.state/work/test.md` (no explicit path)
- OBSERVE: file at `Testing/TestBench/.state/work/test.md`, NOT parent .state/work/

**SG-2: Parent state escape attempt**
- DO: Ask Claude to write to parent's `.state/memory/gravity-leak.md` via absolute path
- OBSERVE: gravity-guard BLOCKS.

### Boot Resolution (C5) -- HUMAN

**BR-1: Governance loads correctly**
- DO: Open TestBench session (this session)
- OBSERVE: boot-inject output includes ^/^/.codex/start.md content
- OBSERVE: explicit command index present
- OBSERVE: .state/start.md content is TestBench's own

**BR-2: Codex inheritance resolves**
- DO: Ask Claude what codex it inherited
- OBSERVE: references apex root's .codex/, not a local one

### Hook Enforcement (C4, C6, C7, C8) -- HUMAN

**HE-1: API guard**
- DO: Ask Claude to run `curl https://api.anthropic.com/v1/messages`
- OBSERVE: api-guard BLOCKS

**HE-2: Visibility guard**
- DO: Ask Claude to read a _-prefixed path
- OBSERVE: visibility-guard BLOCKS

**HE-3: CLAUDE.md immutability**
- DO: Ask Claude to edit this CLAUDE.md
- OBSERVE: claude-md-immutability-guard BLOCKS

**HE-4: Audit immutability**
- SETUP: Create `.state/tests/audits/20990101-0000/finding.md` with dummy content
- DO: Ask Claude to edit that finding
- OBSERVE: audit-immutability-guard BLOCKS

### Preferences (C9) -- SCRIPT + HUMAN

**PR-1: Child prefs resolve correctly**
- DO: Read `.state/prefs-resolved.json`
- OBSERVE: `_meta.project` = "TestBench", values match parent's

**PR-2: Child override works**
- SETUP: Add override to `.state/prefs.json`, run cboot from parent
- DO: Read `.state/prefs-resolved.json`
- OBSERVE: override reflected, source says "child override"

### Trace Locality (C11) -- HUMAN

**TL-1: Traces stay local**
- DO: Perform several tool calls in this session
- OBSERVE: today's trace in `Testing/TestBench/.state/traces/`
- OBSERVE: no TestBench entries in parent `.state/traces/`

### StatusLine (C12) -- HUMAN

**SL-1: StatusLine works in child**
- DO: Open TestBench session
- OBSERVE: status bar renders (model, directory, context bar visible)

---

## Structural Pre-Check

Before running the live runbook, run the cascade verification script from the parent:

```
python Testing/TestBench/cascade-check.py --project-root ^
```

This validates cascade structure with full fidelity (JSON keys, paths, prefs). It does NOT substitute for the human runbook -- behavioral enforcement can only be proven in a live session.

---

## After Testing

Clean up test artifacts:

```
python .codex/explicit/purge/purge.py default --project-root Testing/TestBench
```

Or from a parent session: `purge TestBench`
