---
version: 4
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
3. Update the bundled root's CLAUDE.md: `root: true` → `apex-root: true`. The bundled root becomes `^/^` for every session in the bundle, including one launched at a nested root, because `^/^` stops at the nearest `apex-root: true` (frontmatter spec, `^/^` rule 1). A nested root (a folder below the bundled root whose CLAUDE.md declares `root: true`) keeps `root: true` and stays its own `^`. Never launch a session in a bundle while it sits inside another apex's tree, such as its output folder: two `apex-root: true` declarations on one ancestor path is an error (rule 4). Move it out first.
4. **Materialize the boot-core:** copy the apex `CLAUDE.md` region between `<!-- boot-core:begin` and `<!-- boot-core:end -->` (markers included) into the bundled project's CLAUDE.md, after its hand-authored content. A bundle leaves the ancestor walk, so this is the only delivery path for the region's three sections: Governance Primitives, Naming Conventions, and the Instance State read mandate. Also carry over the apex CLAUDE.md's conditional injection-failure backstop line (the sentinel paragraph, which sits OUTSIDE the region), extracting both from the apex CLAUDE.md only (marker literals appear as prose elsewhere). NOTE: until a cboot-equivalent assembles the bundle's `.claude/settings.json` (step 8 is minimal today — see Open), the bundled boot-inject hook is present but NOT armed, so no boot payload ever arrives and the backstop fires every session — it is the bundle's PRIMARY governance-recovery path, not its layer-2. Skip either copy (with a warning in the bundle report) only if already present.
5. **Remove the `codex:` line** from the bundled root's CLAUDE.md entirely. An apex root with a local `.codex/` resolves it natively (that is `resolve_codex`'s no-ref path); any literal ref such as `codex: .codex` is unresolvable and triggers a governance WARNING at every session start of the bundle. Nested roots keep their `codex: ^/^/.codex` line unchanged: in the bundle `^/^` is the bundled root, so it already names the bundle's own `.codex/`.
6. **Keep every `^/^` reference as it is.** In the bundle, `^/^` resolves to the bundled root, which is where the parent's codex now lives, so each reference still names what it named before. Never coalesce `^/^` to `^`: `^` is the session's own root, and once the bundle has a nested root, a rewritten reference sends a session launched there looking inside its own folder (for `.codex/`, say). A `^/^` reference to something the bundle does not carry (a sibling project, a file of the parent's own `.state/`) is listed in the bundle report, not rewritten. (This replaces the coalescing rule of version 3, which only held for a bundle with no nested root.)
7. Populate `.codex/prefs.json` from the resolved cascade at bundle time (flattened snapshot).
8. Generate `.claude/settings.json` from `.codex/settings.json` — **at bundle time, apex-side**, along with `.claude/skills/` shims and a `.state/prefs-resolved.json` snapshot. The artifact ships these OUTPUTS pre-baked and carries NO build machinery (DECISION 2026-08-01: bundle is categorically decoupled from cboot — see BL-26). Baked hook commands use destination-independent `$CLAUDE_PROJECT_DIR/...` form, never apex-absolute paths. **Nested roots get the same**: each nested root gets its own `.claude/settings.json`, whose hook commands reach the bundled root's codex as `$CLAUDE_PROJECT_DIR/` plus one `../` per level of nesting (`$CLAUDE_PROJECT_DIR/../.codex/...` one level down). A plain `$CLAUDE_PROJECT_DIR/.codex/...` there names a `.codex/` inside the nested root, which does not exist, so every hook at that root breaks: a bash hook exits 127, a non-blocking error, and its guard fails open; a Python hook exits 2 and blocks every call. Skill shims, read by the model rather than executed, point at `^/^/.codex/explicit/<name>/start.md` at every root.
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

The inlining algorithm for edge cases (`start.md` chain flattening across levels, preference cascade snapshot vs. live resolution) is not yet fully specified.

Step 1 copies nested roots with everything in them. A project whose nested roots must not travel (zdm's client folders: "a client is never bundled") has no exclusion mechanism yet.
