---
version: 3
short-desc: Scaffold a new child project from template
runtime: python
reads:
  - "^/.codex/specs/child-project.md"
  - "^/^/.templates/child/"
  - "^/^/.claude/settings.json"
  - "^/^/.claude/settings.local.json"
  - "^/^/.claude/skills/"
  - "^/^/.state/prefs-resolved.json"
writes:
  - "^/<folder>/"
---

# new-project

Create a new child project following the Child Project Spec.

## Usage

`new-project <name>` — create a child project with the given canonical name.

`<name>` is what goes into the CLAUDE.md `name:` frontmatter field. User-authoritative: digits, casing, and punctuation are preserved verbatim. Quote the name if it contains spaces.

The folder name is **derived** from `<name>` per the Naming Convention in `.codex/specs/child-project.md`.

## What It Creates

Runs `bootstrap-child.py` which:

1. Derives the folder name from `<name>` (transliterate → lowercase → strip trailing ` Group` → space-to-hyphen → cleanup).
2. Resolves folder collisions with a numeric suffix (case-insensitive check, `max(N)+1` over existing versioned siblings).
3. Copies the apex `^/^/.templates/child/` tree into the resolved folder. Template is always resolved from the apex (`apex-root: true` ancestor), not from `--project-root`, so nested children work.
4. Fills the empty `name:` field in the copied CLAUDE.md with the user-provided name verbatim.
5. Flags — non-blockingly — if the parent is a root whose own `name:` doesn't already end with ` Group`, prompting a parent rename.
6. Materializes the new child via the shared per-child path (`child_propagate.propagate_one`) — writes its `.claude/settings.json`, `.claude/settings.local.json` (autoMemoryDirectory + perms), skill shims, and `.state/prefs-resolved.json`, derived from the apex's settings (incl. hand-maintained local perms in `settings.local.json`), skill shims, and resolved prefs — so the child boots standalone without waiting for a full apex boot. This is the same engine used by full boot and `cboot --project`; nothing about per-child materialization is duplicated here. If the apex context is absent (apex never booted), it warns — run `cboot --project <folder>` later.

Folder structure (see `.codex/specs/child-project.md` for contents):

```
<folder>/
    CLAUDE.md                   # root: true, name: <name>, codex: ^/^/.codex
    .state/
        start.md, prefs.json
        memory/, work/, tests/, traces/
```

## Execution

```
python .codex/explicit/new-project/bootstrap-child.py "<name>" --project-root ^
```

## Post-Creation

After scaffolding, ask the user what the project is about. Write a one-line description to the project's `CLAUDE.md` body, above the `Read .state/start.md` line. If the user provided the purpose with the creation request, write it directly without prompting.

If the script flagged a parent-rename opportunity, surface it and offer to update the parent's `name:` with a ` Group` suffix. Non-blocking — the user may choose to keep the parent as a non-group.

## Spec

See `.codex/specs/child-project.md` — full Naming Convention, required structure, codex inheritance, state gravity, and bundle behavior.
