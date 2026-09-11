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

```
python .codex/explicit/new-project/bootstrap-child.py '<name>' --description '<one line>' --project-root ^
```

Pass the name and the description in **single quotes**, writing any `'` inside them as `'\''`. Double quotes let the shell run backtick and `$(...)` text and expand `$VAR` — and a mangled description cannot be repaired afterwards.

The description must go in at scaffold time. Once a `CLAUDE.md` exists, its body is immutable to Claude (`claude-md-immutability-guard.sh`), so it cannot be added with an Edit afterwards. If the user declines to give one, scaffold without `--description`; adding it later is a human edit. The script refuses a name containing a line break, and a name or description that cannot be encoded as UTF-8, before it copies anything.

## Post-Creation

If the script flagged a parent-rename opportunity, surface it and offer to update the parent's `name:` with a ` Group` suffix. Non-blocking — the user may choose to keep the parent as a non-group. `name:` is an agent-editable frontmatter key, so the Edit is normally permitted. Add or change only the `name:` line itself. The guard refuses the Edit when the parent's CLAUDE.md has CRLF line endings, a BOM, or an indented or quoted `name:` line, or when the new value breaks the `name:` grammar (see `01a-resolution/frontmatter.md`). In those cases the rename is a human edit: tell the user the exact line to set.

## Spec

See `.codex/specs/child-project.md` — full Naming Convention, required structure, codex inheritance, state gravity, and bundle behavior.
