---
version: 1
runtime: python
reads:
  - "./sub-preamble.md"
  - "./govgen.py (self-hash for the version sentinel)"
  - "^/.codex/explicit/<module>/start.md"
  - "<dispatch-root>/CLAUDE.md (root: true probe)"
writes: []
---

# govgen

Governance resolver — emits the exactly-right governance payload for an actor class, as one generated text. **Prototype: `subagent` profile only** (the dispatch-time channel). Emits to stdout; writes nothing.

The principle: all governance delivery is the output of one deterministic program. Humans author codex sources; govgen composes them per actor; channels carry only generated artifacts. Curation happens at generate time, so no delivered text ever needs semantic forking ("skip this if you're a sub").

## Usage

```
python govgen.py subagent --root <path> [--module <name>]
```

- `--root` — the dispatch root: absolute, `^/`-prefixed (resolved against `CLAUDE_PROJECT_DIR`, falling back to cwd), or cwd-relative. The filesystem root is refused; a root outside `CLAUDE_PROJECT_DIR` emits a warning but proceeds. Gravity and containment are emitted **resolved** — concrete paths, not `^` notation — so a blind subagent needs no resolution rules to comply.
- `--module` — an explicit codex module name (contained to `.codex/explicit/` — separators and dot-leading names refused); its declared `reads:`/`writes:` frontmatter becomes an I/O contract block in the preamble.

**Contract-entry grammar:** an entry's head token (split at the first whitespace of any kind) resolves by prefix — `./` module-relative, `^/` dispatch-root-relative, `^/^/` apex-relative; trailing slash preserved as a directory marker. Annotation tokens carrying `^` notation (including bare `^`) resolve by the SAME rules with the SAME refusals — annotations get no laundering privileges. When an entry needs an apex and none is known, the whole entry falls back to `as-declared:` (heads and annotations behave identically; nothing half-resolves). Refused with exit 2: `..` escapes of the containment base (textual always; physical/symlink-resolved when the path exists), backslash separators (not in the grammar), sentinel-colliding or line/paragraph-separator content (incl. U+2028/U+2029/NEL/VT/FF), non-string/list declaration types, unparseable frontmatter. Block-list declarations tolerate interior blank/comment lines (YAML-consistent, never silently truncated); an unterminated flow-list quote degrades to a single preserved item, never fragments. Unprefixed entries are emitted unresolved, labeled `as-declared:`. Scalar declarations are one-item lists. Tests are hermetic (the suite scrubs `CLAUDE_PROJECT_DIR`; CPD behaviors are tested explicitly).

The dispatcher runs this at dispatch time and embeds the output in the Agent prompt. No round trip for the subagent; the caller controls arming, so compliance is checkable (see Verification).

## Profiles

Defined in `govgen.py` (`PROFILES` — data next to its tests, one diffable home):

| Profile | Status | Budget (bytes) |
|---|---|---|
| `subagent` | live | 2,000 |
| `interactive` / `headless` / `bundle` | reserved — arrive at the Phase B build-time cutover | — |

**Budget = the region admission test, mechanized.** Every emitted byte is paid on every spawn that carries it. Exceeding a profile budget is a build failure (exit 3), never a silent trim.

## Sentinel & versioning

Output is framed by `=== GOV-PREAMBLE v<hash8> ===` … `=== END GOV-PREAMBLE v<hash8> ===`. The hash covers the template, the profile table, and `govgen.py` itself — it versions the **generator**, not the per-dispatch payload: any generator change mints a new version, making stale preambles detectable by inspection. Per-dispatch content (root, module contract) is deliberately outside the hash — a contract edit in a module's `start.md` shows up in the emitted text, not the version.

## Verification (prototype tier)

`subagent-conformance.sh` (SubagentStop) carries the arming-check line, but SubagentStop stdout does not reach model context on this platform, so that channel is currently directive-dead at runtime ([[BL-29]], mileqa 2026-08-02) — arming discipline rides the dispatching protocols (mileqa / ask briefs) until then. Mechanical pre-dispatch enforcement (a PreToolUse hook on the Agent tool) is deliberately deferred to the Phase B cutover, when hook registration moves from `cboot.py` hardcode into codex data and BL-29's re-platforming (PostToolUse, whose stdout IS injected) lands with it; adding a 15th hook script before that would touch the hardcoded registry, the hook-count assertions (test-safe T13), and chooks in one step — too many variables for a prototype.

## Exit codes

`0` emitted · `2` usage/validation error (unknown profile, bad root, missing module) · `3` profile budget exceeded.

## Tests

```
python tests/test_govgen.py
```

Determinism, budget ceiling AND the exit-3 overrun refusal, root resolution (rooted / unrooted-warn / missing / filesystem-root-refused), CLI `--module` end-to-end against the install codex, module-name containment (traversal/absolute/empty refused), sentinel-forgery refusal, contract-entry grammar (comments, symmetric quotes, flow lists, scalars, trailing slashes, annotations), exact exit codes. Bytecode writing is disabled (`writes: []` holds even under test). Golden-per-profile snapshots join ctest at the build-time cutover.

## Roadmap (Phase B, BL-15)

Build-time cutover absorbs: the boot-core floor (authorship returns to codex; cboot splices govgen output into CLAUDE.md regions), `specs/.base.md` (becomes a govgen source), `/bundle` step 4 (bundle profile), and `.claude/agents` definitions. `boot-inject.py` is then deleted and SessionStart shrinks to a freshness check. Prerequisite: BL-16 (cboot atomic writes).
