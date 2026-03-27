# Claudette2

Claudette2 is a governance framework for Claude Code. It gives you enforced rules, persistent memory across sessions, and built-in commands for common workflows -- all without requiring you to hand-manage a sprawling CLAUDE.md file.

If you have used Claude Code before, you know the pattern: write a CLAUDE.md with instructions, hope Claude follows them, lose context when a session ends. Claudette2 replaces that with a modular system where rules are structurally enforced by hooks, state persists cleanly across sessions, and projects can nest inside each other.

## Quick Start

**Prerequisites:** Python 3.9+, Claude Code CLI installed and authenticated (`claude` available on your PATH).

```
git clone <repo-url> my-project
cd my-project
python cboot.py
```

That is the entire boot sequence. `cboot.py` validates your installation, creates directories, generates settings, configures memory, and then launches Claude Code. You will see a bootstrap report in your terminal before the Claude session begins:

```
  [OK]   Pre-flight: CLAUDE.md exists
  [OK]   Pre-flight: .codex/start.md exists
  [OK]   Pre-flight: .state/start.md exists
  [OK]   Scaffolding: 13 directories verified (0 created)
  [OK]   Skill shims: 10 commands registered in .claude/skills/
  [OK]   Pref-resolve: 2 preferences resolved
  [OK]   Settings assembly: .claude/settings.json generated from codex
  [OK]   Auto-memory: already correct (.state/memory)
  [OK]   Hook coverage: all 13 hooks have tests in chooks.py
  ...
  15/15 passed
```

If anything fails, the report tells you what and why. See [README-setup.md](README-setup.md) for detailed first-boot guidance.

## Verify Your Installation

Before your first real session, run the verification scripts to confirm everything is wired up:

```
python ctest.py       # validates bootstrap outputs (milliseconds, no LLM)
python chooks.py      # tests all 13 hook scripts (seconds, no LLM)
```

Both scripts exit 0 on success. See [README-testing.md](README-testing.md) for the full test infrastructure.

## Your First Session

After boot, Claude already knows its rules. You do not need to explain the framework. Just work:

```
You:    I'm starting a new web scraper project. Create a child project for it.
Claude: I'll create a child project called "web-scraper"...
        [runs new-project web-scraper]
        Created web-scraper/ with CLAUDE.md, .state/, memory, and work tracking.

You:    What commands do I have available?
Claude: You have 10 built-in commands: audit, bundle, new-project, pause, purge,
        rebuild, scrub, test-safe, test-burn, unpause. [describes each]

You:    Let's pause here so I can pick this up tomorrow.
Claude: [runs pause]
        Saved to .state/pauses/20260326.1 -- context and state captured.
```

The next day, start a new session and say "unpause" -- Claude reads the pause files and picks up where you left off. Memory (who you are, what decisions were made) persists automatically between sessions without pausing.

## Three Folders That Matter

Everything in Claudette2 lives in three hidden folders:

| Folder | What It Holds | Portable? |
|--------|--------------|-----------|
| `.codex/` | Rules, commands, hooks, preference schemas, audit specs | Yes -- copy between projects |
| `.state/` | Memory, work tracking, test results, session traces | Structure only -- `start.md` manifests are tracked, accumulated content is not |
| `.claude/` | Generated settings, skill shims, session files | No -- regenerated each boot |

You rarely need to edit these directly. Claude manages them, and `cboot.py` regenerates the generated parts each time you start a session.

## Commands

Invoke commands by name in conversation ("audit this project") or as slash commands (`/scrub full`):

| Command | What It Does | Modifies State? |
|---------|-------------|-----------------|
| **test-safe** | 60 read-only structural checks. Safe to run anytime. | No (writes a log only) |
| **test-burn** | DESTRUCTIVE end-to-end functional tests — modifies instance state. | Yes |
| **scrub** | Scan for secrets and PII before pushing code. | No |
| **audit** | Run quality specs against a project. Dispatches sub-agents. | Writes findings |
| **new-project** | Scaffold a child project with standard structure. | Creates directory |
| **pause** | Save session context for later resumption. | Writes pause files |
| **unpause** | Restore a previously paused session. | No |
| **purge** | Clean transient files. `purge all` is destructive (requires confirmation). | Yes |
| **bundle** | Package a child project into a standalone copy. | Writes bundle |
| **rebuild** | Restructure a project based on audit findings. Multi-phase, interactive. | Yes |

See [README-commands.md](README-commands.md) for detailed usage, parameters, and workflow examples.

## Git Model

Claudette2 is distributed as a git repository. Child projects created inside it are **separate git repositories** -- they are not submodules, subtrees, or nested tracked content. The framework's `.gitignore` uses an inverted whitelist model: everything is ignored by default, and only framework files (`.codex/`, `.templates/`, root-level `*.py` and `*.md`) are explicitly tracked.

This means:
- Clone the repo, and you have the complete framework
- Create child projects freely -- they are invisible to the parent repo
- Each child project can `git init` independently with its own remote
- Framework updates arrive via `git pull` on the parent

`.state/` is partially tracked: the directory tree and `start.md` manifests travel with the framework (so a fresh clone is immediately legible), but accumulated content (memory, traces, work items) stays local.

## The `^` Shorthand

In prompts to Claude and in documentation, `^` means "the project root" -- wherever the nearest CLAUDE.md with `root: true` lives. You can use it when talking to Claude:

- "Read `^/.state/memory/user.md`" -- read the user profile for this project
- "Check `^/.codex/explicit/`" -- look at the available commands
- `^/^` means "the outermost project root" (the apex). Useful in child projects to reference the parent: "Read `^/^/.codex/start.md`"

## The `_` and `.` Conventions

| Prefix | Meaning |
|--------|---------|
| `.` (dot) | Claude-internal folders. Claude owns and manages them. You can browse them. |
| `_` (underscore) | Invisible to Claude. Anything with a leading underscore is excluded from Claude's awareness entirely. Use this for private notes, drafts, or files you do not want Claude to see. |

## What Happens Automatically

You do not need to manage these -- they happen in the background:

- **Session start:** Hooks inject boot instructions, check preference freshness, verify memory routing
- **During work:** Hooks enforce boundaries (file containment, visibility rules, API access restrictions, audit immutability), log tool calls to trace files
- **Session end:** Claude updates the state abstract (a rolling summary), runs a compliance check, finalizes the session trace

To see what Claude did during a session, check `.state/traces/` for tool-call logs, `.state/tests/compliance/` for rule-adherence checks, and `.state/tests/boot/` for boot verification results.

## Read Next

| Document | When to Read It |
|----------|----------------|
| [README-setup.md](README-setup.md) | First time setting up, or something went wrong during boot |
| [README-concepts.md](README-concepts.md) | You want to understand how governance, memory, or nesting works |
| [README-commands.md](README-commands.md) | You need details on a specific command |
| [README-testing.md](README-testing.md) | You want to verify your installation or understand the test infrastructure |
