# Claudette

<<<<<<< HEAD
Claudette is a governance framework for Claude Code. It replaces hand-managed CLAUDE.md files with structurally enforced rules, persistent state across sessions, and a modular command system.

## Why Claudette Exists

Claude Code ships hooks, CLAUDE.md hierarchy, skills, and commands -- but no pre-built governance. Claudette assembles these primitives into a tested system:

**Structural enforcement.** 13 hook scripts execute at the tool-call level and block violations before Claude acts -- file containment, visibility guards, state gravity between parent/child projects, API access restrictions, audit immutability. Shell-level gates, not directives.

**Persistent state.** Memory, work tracking (backlog, architecture debt, boundary gaps), session traces, and structured pause/unpause. All in `.state/`, persisted in your project across sessions.

**Multi-project isolation.** Child projects inherit the parent's rules automatically, each as its own git repo with its own state. A gravity guard hook prevents child sessions from writing to parent state.

**Self-testing.** 4-tier verification: `ctest.py` (bootstrap outputs), `chooks.py` (hook behavior via mock JSON), `test-safe` (60 structural checks inside a Claude session), `test-burn` (end-to-end command exercise).
=======
Claudette is a governance framework for Claude Code. It gives you enforced rules, persistent memory across sessions, and built-in commands for common workflows -- all without requiring you to hand-manage a sprawling CLAUDE.md file.

If you have used Claude Code before, you know the pattern: write a CLAUDE.md with instructions, hope Claude follows them, lose context when a session ends. Claudette replaces that with a modular system where rules are structurally enforced by hooks, state persists cleanly across sessions, and projects can nest inside each other.
>>>>>>> 339f92461233b490f01173e54cd978ffb08036ac

## Quick Start

```
git clone https://github.com/KMc-Arch/claudette.git my-project
cd my-project
python cboot.py --argsForClaude
```

Three commands. `cboot.py` scaffolds directories, generates settings, configures memory, registers hooks, and launches Claude Code. See [README-setup.md](README-setup.md) for prerequisites, first-boot details, and troubleshooting.

## Your First Session

After boot, Claude already knows its rules. Just work:

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

The next day, start a new session and say "unpause" -- Claude reads the pause files and picks up where you left off. Memory persists automatically between sessions without pausing.

## What You Get

### Three folders

| Folder | What It Holds | Tracked in Git? |
|--------|--------------|-----------------|
| `.codex/` | Rules, commands, hooks, preference schemas, audit specs | Yes -- this is the framework |
| `.state/` | Memory, work tracking, test results, session traces | Structure only -- `start.md` manifests are tracked, accumulated content is not |
| `.claude/` | Generated settings, skill shims, session files | No -- regenerated each boot |

### 10 commands

| Command | What It Does | Modifies State? |
|---------|-------------|-----------------|
| **test-safe** | 60 read-only structural checks. Safe to run anytime. | No (writes a log only) |
| **test-burn** | DESTRUCTIVE end-to-end functional tests -- modifies instance state. | Yes |
| **scrub** | Scan for secrets and PII before pushing code. | No |
| **audit** | Run quality specs against a project. Dispatches sub-agents. | Writes findings |
| **new-project** | Scaffold a child project with standard structure. | Creates directory |
| **pause** | Save session context for later resumption. | Writes pause files |
| **unpause** | Restore a previously paused session. | No |
| **purge** | Clean transient files. `purge all` is destructive (requires confirmation). | Yes |
| **bundle** | Package a child project into a standalone copy. | Writes bundle |
| **rebuild** | Restructure a project based on audit findings. Multi-phase, interactive. | Yes |

See [README-commands.md](README-commands.md) for detailed usage, parameters, and workflow examples.

### 13 enforcement hooks

| Hook | What It Blocks |
|------|---------------|
| `visibility-guard` | Reading or writing `_`-prefixed (invisible) items |
| `containment-guard` | Writing files outside the project root |
| `gravity-guard` | Writing to `.state/` in a parent project |
| `api-guard` | Bash commands referencing the Anthropic API |
| `audit-immutability-guard` | Modifying existing audit records |
| `claude-md-immutability-guard` | Editing the root CLAUDE.md |
| `boot-inject` | _(not a guard)_ Injects boot instructions at session start |
| `prefs-staleness-check` | _(not a guard)_ Warns if preferences are stale |
| `memory-redirect-check` | _(not a guard)_ Warns if auto-memory is misconfigured |
| `codex-edit-notify` | _(not a guard)_ Notifies when codex executables are modified |
| `trace-logger` | _(not a guard)_ Logs tool calls to daily trace file |
| `session-close` | _(not a guard)_ Prompts end-of-session governance tasks |
| `subagent-conformance` | _(not a guard)_ Checks sub-agent output on completion |

Every hook has behavioral tests in `chooks.py`. See [README-testing.md](README-testing.md).

## Git Model

Claudette is distributed as a git repository. Child projects created inside it are **separate git repositories** -- not submodules, subtrees, or nested tracked content. The `.gitignore` uses an inverted whitelist model: everything is ignored by default, only framework files are tracked. Create child projects freely -- they are invisible to the parent repo, and framework updates arrive via `git pull`.

## Conventions

| Symbol | Meaning |
|--------|---------|
| `^` | Project root (nearest CLAUDE.md with `root: true`). Use in conversation: "Read `^/.state/memory/user.md`" |
| `^/^` | Apex root (outermost project root). Use in child projects to reference the parent. |
| `.` prefix | Claude-internal folders. Claude owns and manages them. |
| `_` prefix | Invisible to Claude. Hook-enforced. Use for private notes, drafts, anything Claude should not see. |

## Read Next

| Document | When to Read It |
|----------|----------------|
| [README-setup.md](README-setup.md) | First time setting up, or something went wrong during boot |
| [README-concepts.md](README-concepts.md) | How governance, memory, project nesting, and the preference cascade work |
| [README-commands.md](README-commands.md) | Detailed command reference with parameters and workflows |
| [README-testing.md](README-testing.md) | The 4-tier test infrastructure and how to verify your installation |
