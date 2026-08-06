---
version: 2
runtime: sh
reads:
  - "^/.codex/settings.json"
  - "<cwd>/CLAUDE.md and ancestors (root: true probe, anchor for the 📁 field)"
  - "~/.claude/settings.json (effort, thinking)"
writes: []
---

# Statusline

Boot-time status bar configuration. Materializes the Claude Code status line that displays session context in the terminal.

## Platform Integration

This module is a shell script — an acknowledged exception to the Python-only runtime constraint (design constraint #6). The status bar is a platform/terminal integration, not a codex operation. Shell is the native tool for reading environment variables and printing formatted strings.

## Reference Chain

```
.claude/settings.json          → references .codex/settings.json (codex-authoritative)
.codex/settings.json           → references this module's settings.json ($ref)
./settings.json                → contains the command path to statusline.sh
./statusline.sh                → the script that generates status bar output
```

## Settings

`settings.json` (sibling file) defines the Claude Code `statusline` configuration:
- `command` — path to `statusline.sh`, relative to project root

## Script

`statusline.sh` is invoked by Claude Code to generate the status bar content. It reads environment variables provided by Claude Code and prints formatted output to stdout.

## Location Display

Location is two fields. `🏠` names `^` — always present, since it is the one thing on the bar that does not move. `📁` is the path from `^` down to `cwd`, in real folder names.

```
🏠claudette | 📁claudette              at ^
🏠claudette | 📁.state/work            inside ^
🏠claudette | 📁zMisc/demo             inside ^, past a root: true boundary   (yellow 🏠)
🏠roughneck | 📁claudette              cwd has left ^ altogether              (orange 🏠)
```

Both fields are always present. At `^` they name the same folder; that repetition is the signal that `cwd` has not moved.

### What `^` resolves to

`workspace.project_dir` — the session's launch directory, which is what `gravity-guard.sh` and `boot-inject.py` also resolve `^` to (via `CLAUDE_PROJECT_DIR`). The bar and the guards therefore always agree on where `^` is. Fallbacks: no project dir in the payload → nearest declared root; nothing there either → `cwd` itself.

Neither the `^` nor the `^/^` literal is printed. The notation is the resolution rule, not the display — the bar stays readable to someone who doesn't hold it in their head.

### Root boundaries colour `🏠`, they don't move `📁`

The nearest `root: true` / `apex-root: true` ancestor is still resolved — walk up from `cwd` (inclusive, 12 levels), first `CLAUDE.md` declaring it in **frontmatter**. Body text is not scanned, so a doc discussing `root: true` in prose is not mistaken for a root.

That result tints `🏠` rather than re-anchoring `📁`:

| Where `cwd` is | `🏠` |
|---|---|
| At `^`, or beneath it under no other root | gray |
| Beneath `^` but past a `root: true` boundary — a child project | **yellow** |
| Outside `^` entirely | **orange** — `📁` is naming another project's folder, anchored on whatever root `cwd` sits under |

Re-anchoring `📁` on the nearest root was the obvious alternative and is wrong: it renders `demo` for `zMisc/demo`, hiding the traversal, and it makes the bar's `^` disagree with the guards'. Colour carries the same fact without either cost.

Paths longer than 32 characters middle-truncate to `<first>/…/<leaf>`, keeping both informative ends.
