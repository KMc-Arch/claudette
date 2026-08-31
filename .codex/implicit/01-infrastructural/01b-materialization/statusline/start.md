---
version: 3
runtime: sh
reads:
  - "the Claude Code status payload on stdin (model, cwd, workspace.project_dir, effort.level, thinking.enabled, rate_limits.five_hour, context_window, transcript_path)"
  - "the transcript file named by transcript_path (context-window fill)"
  - "<cwd>/CLAUDE.md and ancestors (root: true probe, anchor for the 📁 field)"
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

`statusline.sh` is invoked by Claude Code to generate the status bar content. It reads a JSON status payload on **stdin** (not environment variables, and no longer `settings.json`) and prints one formatted line to stdout.

## Bar contents

Left to right: **model** · **effort** (`⚡lo`/`⚡md`/`⚡hi`) · **thinking** (`💭on`) · **location** (`🏠`/`📁`, detailed below) · **git** (`🔀branch (status)`, omitted when `cwd` is gitignored) · **context bar** (`~N% of Mk tokens`) · **5h quota bar** (`⏳ N% (reset countdown)`).

Every field is read from the stdin payload — including `effort.level` and `thinking.enabled`, which therefore reflect the session's **current** state rather than whatever is configured in `settings.json`. That is deliberate: configured values drift from reality (a mid-session `/model`, effort toggle, or thinking change), and stdin does not.

The two budget bars share one renderer (`_render_bar`) so the context window and the 5-hour rate-limit window read as one visual family rather than lookalikes; both countdowns use `_fmt_secs`. The quota bar is **absent** before the first response and for accounts with no 5-hour window (no `rate_limits.five_hour` in the payload) — the bar just ends after the context segment.

## Location Display

Location is two fields. `🏠` names the session's **launch directory** — which is `^` only when the session was launched at a root (the common case); it is always present, since it is the one thing on the bar that does not move. `📁` is the path from the launch directory down to `cwd`, in real folder names. (See *What the bar anchors to* below for why this is the launch dir and not the guards' walked-up `^`.)

```
🏠claudette | 📁claudette              at the launch dir
🏠claudette | 📁.state/work            inside it
🏠claudette | 📁zMisc/demo             inside it, past a root: true boundary   (yellow 🏠)
🏠claudette | 📁roughneck              cwd has left the launch dir altogether  (orange 🏠)
```

Both fields are always present. At the launch dir they name the same folder; that repetition is the signal that `cwd` has not moved.

### What the bar anchors to

`^` itself is defined in one place only — `01a-resolution/frontmatter.md` — and since BL-35 the enforcement guards implement it: they walk **up** from `$CLAUDE_PROJECT_DIR` to the nearest declared root.

The bar does **not** anchor on that. `📁` is anchored on `workspace.project_dir`, the raw launch directory, and `🏠` prints that same directory's name. The walked-up root is resolved but never printed — it only tints `🏠` (see the colour table below). So when the session is launched from a non-root subdirectory, the guards fence *above* what the bar displays, and no field on the bar names the guards' ceiling. (`boot-inject.py` also still loads governance from the raw launch dir — see BL-38.) Fallbacks for the anchor: no project dir in the payload → nearest declared root; nothing there either → `cwd` itself.

Neither the `^` nor the `^/^` literal is printed. The notation is the resolution rule, not the display — the bar stays readable to someone who doesn't hold it in their head.

### Root boundaries colour `🏠`, they don't move `📁`

The nearest `root: true` / `apex-root: true` ancestor is still resolved — walk up from `cwd` (inclusive, to the filesystem root), first `CLAUDE.md` declaring it in **frontmatter**. Body text is not scanned, so a doc discussing `root: true` in prose is not mistaken for a root.

That result tints `🏠` rather than re-anchoring `📁`:

| Where `cwd` is | `🏠` |
|---|---|
| At `^`, or beneath it under no other root | gray |
| The nearest declared root is not the launch dir — `cwd` crossed into a child project, **or** the session was launched below a root and the guards' ceiling sits above `🏠` | **yellow** |
| Outside `^` entirely | **orange** — `📁` is naming another project's folder, anchored on whatever root `cwd` sits under |

Re-anchoring `📁` on the nearest root was the obvious alternative and is wrong: it renders `demo` for `zMisc/demo`, hiding the traversal. Colour carries the same fact without that cost.

Paths longer than 32 characters middle-truncate to `<first>/…/<leaf>`, keeping both informative ends.
