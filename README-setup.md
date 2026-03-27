# Setup Guide

This guide walks through installation, first boot, and common configuration tasks.

## Prerequisites

- **Python 3.9+** -- used by `cboot.py`, `ctest.py`, `chooks.py`, and several command scripts
- **Claude Code CLI** -- installed and authenticated. The `claude` command must be on your PATH.
- **Git** -- the project is a git repository and several features depend on git (scrub, traces, history tracking)
- **Bash on PATH** -- required for hook scripts. The test runner and Claude Code both invoke hooks via `bash <script>`, so the `bash` executable must be on your system PATH. On Windows, Git for Windows includes bash at `C:\Program Files\Git\bin\bash.exe` -- add that directory to your PATH if `bash --version` doesn't work from your terminal

## Installation

```
git clone <repo-url> my-project
cd my-project
```

That gives you the complete framework. No `npm install`, no `pip install`, no build step.

The repository uses an inverted `.gitignore` -- everything is ignored by default, and only framework files are whitelisted. Child projects you create inside this directory are automatically invisible to the parent repo and can be their own independent git repositories.

## Running cboot.py

`cboot.py` is **required** before your first session and should be re-run whenever the framework changes. Specifically:

- **First run after cloning** -- scaffolds directories, generates settings, configures memory routing
- **After `git pull`** -- a framework update may add hooks, commands, or change settings
- **After editing `.codex/`** -- new hooks or commands need registration
- **After `purge`** -- restores generated artifacts that were cleaned
- **After `test-burn`** -- restores artifacts exercised during testing

Running `cboot.py` when nothing has changed is harmless -- it validates and reports, creating only what's missing.

```
python cboot.py
```

`cboot.py` performs these steps in order:

1. **Pre-flight** -- verifies CLAUDE.md, `.codex/start.md`, and `.state/start.md` exist. Aborts if any are missing.
2. **Scaffolding** -- creates all `.state/` subdirectories (memory, work, tests, traces, pauses, bundles) and `.claude/skills/`.
3. **Structure check** -- counts hooks, commands, reactive/reflexive modules. Verifies every codex directory has a `start.md` manifest.
4. **Skill shims** -- generates `.claude/skills/<name>/SKILL.md` for each command in `.codex/explicit/`, so Claude Code recognizes them as slash commands.
5. **Preference resolution** -- merges the preference cascade (schema defaults, codex-level, instance-level) into a single `.state/prefs-resolved.json`.
6. **Settings assembly** -- builds `.claude/settings.json` from `.codex/settings.json`, registering all 13 hook scripts.
7. **Auto-memory configuration** -- sets `autoMemoryDirectory` in `.claude/settings.local.json` to point to `.state/memory/`. This redirects Claude Code's built-in auto-memory away from the default location (`~/.claude/projects/<hash>/memory/`) into the project's own state directory.
8. **Git hooks** -- if a pre-push hook script exists at `.codex/explicit/scrub/hooks/pre-push`, sets `core.hooksPath` to point there. (Note: this hook script does not exist yet in the current version. The scrub command works as a manual protocol. Automated pre-push enforcement is planned for a future release.)
9. **Trace marker** -- writes a session-start entry to today's trace file.
10. **Hook coverage** -- verifies every hook script has corresponding tests in `chooks.py`.
11. **Report** -- writes results to `.state/tests/boot/` and prints to terminal.
12. **Launch** -- starts `claude` with any arguments you passed through.

### Passing Arguments Through

Any arguments after `cboot.py` are forwarded to `claude`:

```
python cboot.py --resume              # resume last conversation
python cboot.py -p "run test-safe"    # run a prompt non-interactively
python cboot.py --model sonnet        # use a specific model
```

### What autoMemoryDirectory Does

Claude Code has a built-in auto-memory feature: when it learns something important about your project, it writes a markdown file to a memory directory. By default, this goes to `~/.claude/projects/<hash>/memory/`, which is outside your project and not version-controlled.

`cboot.py` redirects this to `.state/memory/` inside your project. This means:
- Memory files live alongside your project
- They are version-controlled (visible in git)
- Claude reads them at session start and picks up where it left off

This is configured via `.claude/settings.local.json`, which must use an absolute path (a Claude Code platform requirement -- relative paths silently fail). `cboot.py` handles this automatically.

## Verifying Your Installation

After the first boot, run the verification scripts:

```
python ctest.py       # 17 checks across 8 categories
python chooks.py      # behavioral tests for all 13 hooks
```

Both run in seconds with no LLM calls. If either reports failures, read the detail lines -- they explain what is wrong and where to look.

For a deeper check from inside a Claude session, run:

```
You: run test-safe
```

This performs 60 read-only structural checks from inside Claude's own context, including cross-reference integrity, frontmatter contracts, and auto-memory routing verification.

## Common Configuration Tasks

### Setting Preferences

Preferences control behavioral knobs (tone, emoji usage, verbosity). The schema is in `.codex/pref-options.json`. To override a default:

1. Edit `.state/prefs.json` (instance-level override) or `<project>/.state/prefs.json` (project-level override)
2. Add the key with a `value` and optional `context`:
   ```json
   {
     "tone": {
       "value": "direct",
       "context": "Team prefers concise responses"
     }
   }
   ```
3. Re-run `python cboot.py` to regenerate `prefs-resolved.json`

Preferences are resolved through a four-layer cascade: session (ephemeral) > project > instance > codex defaults. Most-specific wins.

### Creating a Child Project

From inside a Claude session:

```
You: new-project my-api
```

This creates `my-api/` with its own CLAUDE.md, `.state/`, memory, and work tracking. The child inherits the parent's codex (rules, commands, hooks) automatically through the `codex: ^/^/.codex` declaration in its CLAUDE.md.

### Adopting an Existing Project

To bring an existing project under Claudette2 governance:

1. Move or place the project folder inside the Claudette2 root. The parent's `.gitignore` automatically ignores it -- your project's own git history is unaffected.
2. The easiest path: from inside a Claude session, run `new-project <name>` to scaffold the standard structure, then move your existing files into the created folder
3. Alternatively, set it up manually:
   - Add frontmatter to the top of the project's CLAUDE.md (create one if it doesn't exist):
     ```yaml
     ---
     root: true
     codex: ^/^/.codex
     ---
     Read `.state/start.md`.
     ```
   - Create a `.state/` directory with `start.md`, `memory/`, and `work/` subdirectories (see `.templates/child/` for the expected structure)

The child project inherits all parent governance rules automatically. It keeps its own memory and work tracking separate from the parent.

### Adding Custom Rules

The codex (`.codex/`) has four categories:

- `implicit/` -- rules that load at every session start (foundational behavior)
- `explicit/` -- commands invoked by the user (lazy-loaded)
- `reactive/` -- rules triggered by project context (e.g., "if this project uses SQLite...")
- `reflexive/` -- self-governance rules triggered by system events

To add a custom rule, create a folder in the appropriate category with a `start.md` describing the rule. Re-run `cboot.py` to register it.

## Troubleshooting

**"claude command not found"** -- Claude Code CLI is not installed or not on your PATH. Install it and ensure `claude --version` works.

**Pre-flight failure** -- A critical file is missing. Check that CLAUDE.md, `.codex/start.md`, and `.state/start.md` all exist at the project root.

**Auto-memory leaking to default location** -- Run `python ctest.py` and check V10-V12. If `autoMemoryDirectory` is wrong, delete `.claude/settings.local.json` and re-run `python cboot.py`.

**Hooks not firing** -- Run `python chooks.py` to verify hook scripts work. Then check `.claude/settings.json` was generated (not hand-edited). If the `$comment` field does not contain "GENERATED", the file was manually modified and may be out of sync. Delete it and re-run `python cboot.py`.

**Preference changes not taking effect** -- Re-run `python cboot.py` to regenerate `prefs-resolved.json`. Claude reads only the resolved file, not the source files.

## Read Next

| Document | When to Read It |
|----------|----------------|
| [README.md](README.md) | Overview and daily usage |
| [README-concepts.md](README-concepts.md) | How governance, memory, and project nesting work |
| [README-testing.md](README-testing.md) | Full test infrastructure reference |
