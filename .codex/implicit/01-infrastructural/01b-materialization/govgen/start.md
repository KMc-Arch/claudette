---
version: 1
runtime: python
reads:
  - "./sub-preamble.md"
  - "^/.codex/explicit/<module>/start.md"
writes: []
---

# govgen

Governance resolver — emits the exactly-right governance payload for an actor class, as one generated text. **Prototype: `subagent` profile only** (the dispatch-time channel). Emits to stdout; writes nothing.

The principle: all governance delivery is the output of one deterministic program. Humans author codex sources; govgen composes them per actor; channels carry only generated artifacts. Curation happens at generate time, so no delivered text ever needs semantic forking ("skip this if you're a sub").

## Usage

```
python govgen.py subagent --root <path> [--module <name>]
```

- `--root` — the dispatch root: absolute path, or `^/`-prefixed (resolved against `CLAUDE_PROJECT_DIR`, falling back to cwd). Gravity and containment are emitted **resolved** — concrete paths, not `^` notation — so a blind subagent needs no resolution rules to comply.
- `--module` — an explicit codex module name; its declared `reads:`/`writes:` frontmatter becomes an I/O contract block in the preamble.

The dispatcher runs this at dispatch time and embeds the output in the Agent prompt. No round trip for the subagent; the caller controls arming, so compliance is checkable (see Verification).

## Profiles

Defined in `govgen.py` (`PROFILES` — data next to its tests, one diffable home):

| Profile | Status | Budget (bytes) |
|---|---|---|
| `subagent` | live | 2,000 |
| `interactive` / `headless` / `bundle` | reserved — arrive at the Phase B build-time cutover | — |

**Budget = the region admission test, mechanized.** Every emitted byte is paid on every spawn that carries it. Exceeding a profile budget is a build failure (exit 3), never a silent trim.

## Sentinel & versioning

Output is framed by `=== GOV-PREAMBLE v<hash8> ===` … `=== END GOV-PREAMBLE v<hash8> ===`. The hash covers the template, the profile table, and `govgen.py` itself — any generator change mints a new version, making stale preambles detectable by inspection.

## Verification (prototype tier)

`subagent-conformance.sh` (SubagentStop) directs a post-dispatch check that the dispatch was armed with a `GOV-PREAMBLE` sentinel — warn-level, directive-layer. Mechanical pre-dispatch enforcement (a PreToolUse hook on the Agent tool) is deliberately deferred to the Phase B cutover, when hook registration moves from `cboot.py` hardcode into codex data; adding a 15th hook script before that would touch the hardcoded registry, the hook-count assertions (test-safe T13), and chooks in one step — too many variables for a prototype.

## Exit codes

`0` emitted · `2` usage/validation error (unknown profile, bad root, missing module) · `3` profile budget exceeded.

## Tests

```
python tests/test_govgen.py
```

Determinism, budget, root resolution (rooted / unrooted-warn / missing), contract-block resolution, frontmatter list parsing. Golden-per-profile snapshots join ctest at the build-time cutover.

## Roadmap (Phase B, BL-15)

Build-time cutover absorbs: the boot-core floor (authorship returns to codex; cboot splices govgen output into CLAUDE.md regions), `specs/.base.md` (becomes a govgen source), `/bundle` step 4 (bundle profile), and `.claude/agents` definitions. `boot-inject.py` is then deleted and SessionStart shrinks to a freshness check. Prerequisite: BL-16 (cboot atomic writes).
