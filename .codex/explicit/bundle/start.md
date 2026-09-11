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

1. Copy the full project tree into the output folder — excluding `.state/bundles/` (a bundle must never recursively copy prior bundles or its own in-progress output), `.state/traces/`, and `.claude/` (all per the Rules below), and the project's own root `CLAUDE.md` — top level only (e.g. `rsync -a --exclude=/CLAUDE.md <src>/ <dst>/` — the trailing `/` on the source matters: without it the exclude misses and the file is copied); nested projects' `CLAUDE.md` files are copied as-is. Steps 3–5 create the root one. If the output folder already holds a `CLAUDE.md` (a reused folder, or a first attempt that went wrong), start a new bundle folder rather than replace it.
2. Copy `^/^/.codex/` into the bundled project's own `.codex/` — but where the child has local same-name overrides, keep the child's version (see Codex Override Resolution below; a blind parent copy would clobber the override this step must preserve).
3. **Assemble the bundled root CLAUDE.md in memory (steps 3–5), then stage and rename it (end of step 5).** `claude-md-immutability-guard.sh` stops Claude's Write/Edit from creating a CLAUDE.md or changing an existing one's body or `root:`/`codex:` lines, so the text is written under another name and renamed into place — the one sanctioned route, and only inside this command's own output folder. Start from the source project's CLAUDE.md text and change `root: true` → `apex-root: true`.
4. **Materialize the boot-core:** copy the apex `CLAUDE.md` region between `<!-- boot-core:begin` and `<!-- boot-core:end -->` (markers included) into the bundled CLAUDE.md text, after its hand-authored content. A bundle leaves the ancestor walk, so this is the only delivery path for the region's sections: Governance Primitives, Naming Conventions, Exchange Surfaces, and the Instance State read mandate. Also carry over the apex CLAUDE.md's conditional injection-failure backstop line (the sentinel paragraph, which sits OUTSIDE the region), extracting both from the apex CLAUDE.md only (marker literals appear as prose elsewhere). NOTE: until a cboot-equivalent assembles the bundle's `.claude/settings.json` (step 8 is minimal today — see Open), the bundled boot-inject hook is present but NOT armed, so no boot payload ever arrives and the backstop fires every session — it is the bundle's PRIMARY governance-recovery path, not its layer-2. Skip either copy (with a warning in the bundle report) only if already present.
5. **Remove the `codex:` line** from the bundled CLAUDE.md text entirely. Then write the assembled text to `CLAUDE.md.staged` in the bundle folder with the Write tool, and rename it without clobbering: `python3 -c 'import os,sys; d=sys.argv[2]; assert not os.path.lexists(d), d + " exists"; os.rename(sys.argv[1], d)' <bundle>/CLAUDE.md.staged <bundle>/CLAUDE.md` (Python's rename, not `mv`: hot-tree renames on this mount can leave ghost entries). An apex root with a local `.codex/` resolves it natively (that is `resolve_codex`'s no-ref path); any literal ref such as `codex: .codex` is unresolvable and triggers a governance WARNING at every session start of the bundle.
6. Coalesce `^/^` **path references** in codex entries (not the bundled `CLAUDE.md`, which steps 3–5 created) to `^` — but NOT prose that *defines or contrasts* the notations (the naming table, State Gravity, the frontmatter spec, this step's own text). A blind global replacement corrupts the governance text — proven 2026-08-01: it produced "using `^` or `^` notation", inverted the State Gravity rule, and made `apex-root` and `root` rows collide. Coalesce only inside path-shaped occurrences (`^/^/...`), and skip the known definition files.
7. Populate `.codex/prefs.json` from the resolved cascade at bundle time (flattened snapshot).
8. Generate `.claude/settings.json` from `.codex/settings.json` — **at bundle time, apex-side**, along with `.claude/skills/` shims and a `.state/prefs-resolved.json` snapshot. The artifact ships these OUTPUTS pre-baked and carries NO build machinery (DECISION 2026-08-01: bundle is categorically decoupled from cboot — see BL-26). Baked hook commands use destination-independent `$CLAUDE_PROJECT_DIR/...` form, never apex-absolute paths.
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
