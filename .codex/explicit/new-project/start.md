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
4. Fills the empty `name:` field in the copied CLAUDE.md with the user-provided name verbatim, and — with `--description` — writes the one-line description into the body, above the `Read .state/start.md` line.
5. Flags — non-blockingly — if the parent is a root whose own `name:` doesn't already end with ` Group`, prompting a parent rename.
6. Materializes the new child via the shared per-child path (`child_propagate.propagate_one`) — writes its `.claude/settings.json`, `.claude/settings.local.json` (autoMemoryDirectory + perms), skill shims, and `.state/prefs-resolved.json`, derived from the apex's settings (incl. hand-maintained local perms in `settings.local.json`), skill shims, and resolved prefs — so the child boots standalone without waiting for a full apex boot. This is the same engine used by full boot and `cboot --project`; nothing about per-child materialization is duplicated here. If the apex context is absent (apex never booted), it warns — run `cboot --project <folder>` later.

Folder structure (see `.codex/specs/child-project.md` for contents):

```
<folder>/
    CLAUDE.md                   # root: true, name: <name>, codex: ^/^/.codex
    ~inbox/, ~outbox/           # Exchange Surfaces mailboxes (each with a start.md)
    .state/
        start.md, prefs.json
        memory/, work/, tests/, traces/
```

Every child is scaffolded with `~inbox/` and `~outbox/` per the apex **Exchange Surfaces** rule (boot-core `CLAUDE.md`): inbound drops addressed to the project, and outbound handoffs to other actors. They ship as part of `^/^/.templates/child/`, so no bespoke step creates them.

## Execution

**Before running the script**, get a one-line description of what the project is about. If the creation request already gives the purpose, use it; otherwise ask the user.

Write the description — and the name, if it contains a word starting with `_` or begins with `-` — to scratch files under `^/.tmp/` with the Write tool, one per project (e.g. `^/.tmp/new-project-description-<folder>.txt`; `/purge` sweeps `.tmp/`). Then run the script by its **absolute** path — from a child session the relative path does not exist:

```
python3 '<apex>/.codex/explicit/new-project/bootstrap-child.py' --description-file '<that file>' --project-root '<^ as an absolute path>' -- '<name>'
```

`--description-file` and `--name-file` keep the text out of the shell entirely: no quoting to get wrong, and no word starting with `_` for the visibility guard to block. `--description='<one line>'` also works for short plain text (single quotes, any `'` written as `'\''`). Put the name last, after `--`, so a name starting with `-` is not read as an option. Quote `--project-root` too (roots can contain spaces).

The description must go in at scaffold time. Once a `CLAUDE.md` exists, its body is immutable to Claude (`claude-md-immutability-guard.sh`), so it cannot be added with an Edit afterwards. If the user declines to give one, scaffold without it; adding it later is a human edit. Before copying anything, the script refuses:
- a name with a line break, BOM, control character or `---`, or one whose folder name would exceed 100 characters;
- a description that is empty (from a file), more than one line, over 300 characters, or holds a BOM, control or invisible formatting character;
- a template CLAUDE.md with non-LF line breaks, or one that already fills `name:`.

It notes a name Claude could not write itself (one starting with `[ ] { } & * ! | > % @` or a backtick, over 200 characters, or with a format character): any later rename by Claude, such as adding ` Group`, must drop that.

## Post-Creation

If the script flagged a parent-rename opportunity, surface it and offer to update the parent's `name:` with a ` Group` suffix. Non-blocking — the user may choose to keep the parent as a non-group. `name:` is an agent-editable frontmatter key, so the Edit is normally permitted. Add or change only the `name:` line itself. The guard refuses the Edit when the parent's CLAUDE.md has CRLF line endings, a BOM, an indented or quoted `name:` line, or a `---` inside a frontmatter line, or when the new value breaks the `name:` grammar (see `01a-resolution/frontmatter.md`). In those cases the rename is a human edit: tell the user the exact line to set.

## Spec

See `.codex/specs/child-project.md` — full Naming Convention, required structure, codex inheritance, state gravity, and bundle behavior.
