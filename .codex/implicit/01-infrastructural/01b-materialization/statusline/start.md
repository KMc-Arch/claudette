---
version: 6
runtime: sh
reads:
  - "the Claude Code status payload on stdin (model, cwd, workspace.project_dir, effort.level, thinking.enabled, rate_limits.five_hour, context_window, transcript_path); plus $COLUMNS from the environment"
  - "the transcript file named by transcript_path (context-window fill + last user message)"
  - "<cwd>/CLAUDE.md and ancestors (root: true probe — tints 🏠; also the fallback/left-^ anchor for 📁)"
  - "the nearest ProjectMetaBase.db walking up from cwd (sqlite: core_projects, trans_runs, core_context_files — the project-info segment)"
  - "the git repo at cwd (branch + porcelain status, when cwd is not gitignored)"
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

Left to right: **model** · **effort** (`⚡lo`/`⚡md`/`⚡hi`/`⚡xh`/`⚡mx`) · **thinking** (`💭on`/`💭off`) · **location** (`🏠`/`📁`, detailed below) · **project-info** (from `ProjectMetaBase.db`, detailed below; absent when no db is found) · **git** (`🔀branch (status)`, omitted when `cwd` is gitignored) · **context bar** (`N% of Mk tokens`; a `~` prefix marks the estimated baseline shown before real token data arrives) · **5h quota bar** (`⏳ N% (reset countdown)`).

The **project-info** segment appears when a `ProjectMetaBase.db` is found walking up (≤5 levels) from `cwd` and `cwd` sits under a `type/project` folder: it renders `project_id [phase]` (the project's status/last-run phase), a `+N new` badge for unanalyzed context files, `[unregistered]` for a folder not yet in the db, or an `N active projects` summary at the db root. This is a project-discovery integration, not core status-bar machinery.

Every field is read from the stdin payload — including `effort.level` and `thinking.enabled`, which therefore reflect the session's **current** state rather than whatever is configured in `settings.json`. That is deliberate: configured values drift from reality (a mid-session `/model`, effort toggle, or thinking change), and stdin does not.

The two budget bars share one renderer (`_render_bar`) so the context window and the 5-hour rate-limit window read as one visual family rather than lookalikes; the quota bar's reset countdown uses `_fmt_secs` (the context bar has no countdown). The quota bar is **absent** before the first response and for accounts with no 5-hour window (no `rate_limits.five_hour` in the payload) — the bar just ends after the context segment.

## Second row — 💬 last user message

A second line (multi-line status lines are officially supported; each printed line is a row) shows `💬 <the user's last typed prompt>`. It renders the prompt's first non-empty line, then appends each following non-empty line (joined by `⏎`) until the terminal width runs out; a first line that alone overruns is hard-truncated with `...` (ASCII). Width is `$COLUMNS`, which Claude Code sets to the live terminal size before running the script (`tput cols` cannot work — stdout is captured, not attached to the terminal); `$COLUMNS` is validated as an integer before use, and the budget reserves the `💬 ` prefix plus a column. Fallback when `COLUMNS` is unset: the plain-text width of row 1. The budget is measured in **characters**, not display columns, so a prompt of wide glyphs (CJK/emoji) can still overrun and wrap one row — a known limitation (backlogged; the row does not wrap for ASCII prompts). Before printing, the message has C0/C1 control bytes stripped (so a prompt carrying raw ESC cannot rewrite row 1) and is emitted with `printf '%s\n'`, not `echo` (immune to `xpg_echo` backslash interpretation on Git-Bash). Both the row and the context bar are computed from the transcript in one `_transcript_data` pass.

The extraction has two non-obvious properties, each earning its own red-first proof (see the module's git history for the proof transcript paths):

- **Whitelist, not blacklist.** Claude Code writes far more than human prompts as `type:"user"` — task-notifications, hook/`isMeta` payloads, tool results, `sdk` and `auto-continuation` entries. The row keeps only entries whose `origin.kind == "human"` (or, for one legacy shape, `promptSource == "typed"`) and drops `isMeta` / `isSidechain` / `toolUseResult`. A blacklist has to chase every new kind as Claude Code adds them; the whitelist does not. Slash commands vary (verified on 2.1.251): a **skill command** (e.g. `/mileqa`) *is* tagged `origin.kind == "human"`, its content the raw `<command-name>…</command-name>` + `<command-args>` XML — so it is kept and unwrapped to the command-name text plus args (e.g. `/mileqa …`, the slash coming from the tag content, not added by the code); some **built-ins** (e.g. `/model`) record with no `origin` and are skipped, so the row holds the previous real prompt. Older transcripts also tagged commands `human` as that XML.
- **Line-by-line parse, not `jq -s`.** `jq -s` aborts the entire parse on a single malformed line, and transcripts on this 9p mount can carry runs of NUL bytes mid-file. When that happened, the 💬 row vanished **and** the context bar silently fell back to its fake baseline (~10% of the default 200k window; ~2% of a 1M window). `jq -nR '[inputs | fromjson? // empty]'` drops only the bad line and is benchmarked free. A companion hazard is guarded the same way: each `usage` token is coerced with `tonumber? // 0`, so a valid-JSON entry carrying a **string** token count cannot abort the shared program and re-blank both outputs.

Held for a later pass (scoped 2026-08-31, not yet built): an optional third functional-status row — KMc has not yet chosen its contents (free stdin fields vs. claudette-state behind a TTL cache).

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
