---
version: 3
short-desc: Package a child project as a standalone portable copy
reads:
  - "^/"
  - "^/^/.codex/"
  - "^/^/CLAUDE.md"
writes:
  - "^/.state/bundles/"
---

# bundle

Create a portable, self-contained copy of a child project by resolving all external references to the parent into inlined content. The bundled project can operate independently without the parent claudette2 instance.

## Usage

`bundle` — bundle the current child project
`bundle <project>` — bundle a specific child project

## Output Location

`^/.state/bundles/YYYYMMDD-HHMM-<project>/` — timestamped to enable multiple bundles. Lives under `.state/` for state gravity compliance.

## What Bundle Does

1. Copy the full project tree into the output folder — excluding `.state/bundles/` (a bundle must never recursively copy prior bundles or its own in-progress output), `.state/traces/`, and `.claude/` (all per the Rules below).
2. Copy `^/^/.codex/` into the bundled project's own `.codex/` — but where the child has local same-name overrides, keep the child's version (see Codex Override Resolution below; a blind parent copy would clobber the override this step must preserve).
3. Update CLAUDE.md: `root: true` → `apex-root: true`.
4. **Materialize the boot-core:** copy the apex `CLAUDE.md` region between `<!-- boot-core:begin` and `<!-- boot-core:end -->` (markers included) into the bundled project's CLAUDE.md, after its hand-authored content. A bundle leaves the ancestor walk, so this is the only delivery path for the region's three sections: Governance Primitives, Naming Conventions, and the Instance State read mandate. Also carry over the apex CLAUDE.md's conditional injection-failure backstop line (the sentinel paragraph, which sits OUTSIDE the region), extracting both from the apex CLAUDE.md only (marker literals appear as prose elsewhere). NOTE: until a cboot-equivalent assembles the bundle's `.claude/settings.json` (step 8 is minimal today — see Open), the bundled boot-inject hook is present but NOT armed, so no boot payload ever arrives and the backstop fires every session — it is the bundle's PRIMARY governance-recovery path, not its layer-2. Skip either copy (with a warning in the bundle report) only if already present.
5. **Remove the `codex:` line** from the bundled CLAUDE.md entirely. An apex root with a local `.codex/` resolves it natively (that is `resolve_codex`'s no-ref path); any literal ref such as `codex: .codex` is unresolvable and triggers a governance WARNING at every session start of the bundle.
6. Coalesce `^/^` **path references** in codex entries to `^` — but NOT prose that *defines or contrasts* the notations (the naming table, State Gravity, the frontmatter spec, this step's own text). A blind global replacement corrupts the governance text — proven 2026-08-01: it produced "using `^` or `^` notation", inverted the State Gravity rule, and made `apex-root` and `root` rows collide. Coalesce only inside path-shaped occurrences (`^/^/...`), and skip the known definition files.
7. Populate `.codex/prefs.json` from the resolved cascade at bundle time (flattened snapshot).
8. Generate `.claude/settings.json` from `.codex/settings.json`.
9. Resolve `start.md` chain references so the bundled project is self-interpreting.
10. Copy root-level reference docs the codex points at (currently `README-concepts.md`, cited by `.codex/start.md` for full primitive definitions) — otherwise the bundle's eager boot chain contains dangling references.

## Rules

- The source project is **never modified**. Bundle operates on a copy.
- `.state/memory/` is included (project knowledge is part of the bundle).
- `.state/work/` is included (project state is part of the bundle).
- `.state/traces/` is excluded (session-specific, not portable).
- `.claude/` transient artifacts are excluded (session state is not portable).
- The bundle is a point-in-time snapshot, not a sync mechanism.

## Codex Override Resolution

If the child project has local `.codex/` entries that override parent entries (same-name, innermost wins), the bundle includes the **child's version** — the override is baked in. The parent's overridden entries are not included.

## Open

The inlining algorithm for edge cases (nested `^/^` references within inlined content, `start.md` chain flattening across levels, preference cascade snapshot vs. live resolution) is not yet fully specified.
