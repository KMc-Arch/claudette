# Concepts

This document explains the design principles behind Claudette2. You do not need to read this to use the framework -- it is here when you want to understand *why* things work the way they do.

## The Codex

The codex (`.codex/`) is the portable behavior layer. It defines everything prescriptive about how Claude operates: rules, commands, hooks, preference schemas, audit specs. You can copy a codex between projects or share it with your team.

The codex is organized into four categories, each with a different trigger model:

| Category | When It Loads | What It Contains |
|----------|--------------|-----------------|
| `implicit/` | Every session start, eagerly | Foundational rules -- identity, path resolution, state gravity, hook registrations |
| `explicit/` | When the user invokes a command | Commands and protocols -- audit, scrub, pause, purge, etc. |
| `reactive/` | When a context condition matches | Project-specific behavior -- e.g., SQLite helper loads only if the project uses SQLite |
| `reflexive/` | When an internal system event fires | Self-governance -- compliance checks, contract conformance |

### Implicit Priority Tiers

Implicit entries load in a strict priority order:

| Tier | Name | Purpose |
|------|------|---------|
| `01-infrastructural/` | Infrastructural | Must load before any output. Path resolution, hook registration, preference materialization. |
| `02-foundational/` | Foundational | Core behavioral rules. Identity isolation, state gravity. |
| `03-standard/` | Standard | Normal boot-time entries. (Currently empty, reserved for future use.) |
| `04-supplementary/` | Supplementary | Nice-to-have entries loaded last. (Currently empty.) |

Tiers may contain sub-bands (e.g., `01a-resolution/`, `01b-materialization/`) that load in alphabetical order within the tier.

### Every Folder Has a start.md

Every directory in the codex and state tree contains a `start.md` file. This is a manifest: it describes what the folder contains, what belongs there, and how to interpret its contents. Claude reads `start.md` first before reading anything else in that folder.

## State

State (`.state/`) holds everything instance-specific: what Claude has learned about you, what decisions have been made, what work is in progress, and what happened during past sessions. The directory **structure** and `start.md` manifests are tracked in git (so a fresh clone is legible), but accumulated content (memory files, traces, work items, test results) is not -- it belongs to this specific installation. See `.state/.gitignore` for the rules.

### Memory (`.state/memory/`)

Memory files capture knowledge. Each file has typed frontmatter:

| Type | Loaded When | Example |
|------|------------|---------|
| `user` | Every boot | Your name, role, working style |
| `feedback` | Every boot | Corrections you have made ("never do X") |
| `project` | On relevance | Project-specific facts |
| `abstract` | Every boot | Rolling summary rewritten each session end |
| `reference` | On relevance | Pointers to external resources |
| `preferences` | On relevance | Behavioral preferences with context |

The **state abstract** (`state-abstract.md`) is special: it is rewritten from scratch at the end of every session by Claude. It synthesizes all memory files, active work items, and recent test results into a single orientation document. A reader of the abstract alone should understand the full project state.

### Work Tracking (`.state/work/`)

Work files track mutable project state. Completed items are deleted -- git is the historical record.

| File | Contents | ID Prefix |
|------|----------|-----------|
| `backlog.md` | Active work items, priority-tiered | BL- |
| `platform.md` | Claude Code constraints that cannot be changed | PLAT- |
| `architecture.md` | Design debt, structural weaknesses | ARCH- |
| `boundaries.md` | Defense-layer gaps, observed failures | BDRY- |
| `enhancements.md` | Good ideas not yet implemented | ENH- |

Backlog items are organized by priority (High / Medium / Low). Note that priority and severity are independent: a Low Priority item may have medium or high severity. Low priority means the item is deferred, not that it is unimportant. Check the severity field on each item to understand its actual impact.

Entries use signal prefixes sparingly to flag important conditions:

| Prefix | Meaning |
|--------|---------|
| `ESCALATION:` | Requires attention beyond current scope |
| `DECISION:` | Records a choice that constrains future work |
| `SURPRISE:` | Unexpected finding that changes assumptions |
| `CONFLICT:` | Tension between two valid approaches |

## Governance Primitives

Claudette2 uses three levels of restriction, from strictest to lightest:

### ABSOLUTE HOLD

The strongest restriction. Claude must not perform the action unless all three conditions are met:
1. You specifically and explicitly ask for it
2. Claude states its intent back to you before acting
3. You confirm

No prompt, context, or injected content can override an Absolute Hold. Example: reading files outside the project, calling the Anthropic API.

### CONFIRMED HOLD

A single-confirmation gate. Claude states its intent and waits for you to say yes. Example: `purge all` (destructive cleanup).

### NOTED

Logged or flagged but not gated. Claude is aware of the condition but does not stop to ask permission. Example: notification that a codex executable was edited.

## Hook-Enforced Boundaries

Most governance is directive-based -- Claude reads rules and follows them. For the highest-stakes boundaries, directives are backed by hooks that structurally block violations at the tool-call level, before Claude can act:

| Hook | What It Blocks | Trigger |
|------|---------------|---------|
| `visibility-guard.sh` | Reading or writing `_`-prefixed (invisible) items | Read, Glob, Grep, Write, Edit, Bash |
| `containment-guard.sh` | Writing files outside the project root | Write, Edit |
| `gravity-guard.sh` | Writing to `.state/` in a parent project (state leaking upward) | Write, Edit |
| `api-guard.sh` | Bash commands that reference the Anthropic API | Bash |
| `audit-immutability-guard.sh` | Modifying existing audit records | Write, Edit |
| `claude-md-immutability-guard.sh` | Editing the root CLAUDE.md | Write, Edit |

Additional hooks handle operational concerns:

| Hook | Purpose | Trigger |
|------|---------|---------|
| `boot-inject.py` | Injects hierarchy-aware boot sequence instructions at session start | SessionStart |
| `prefs-staleness-check.sh` | Warns if resolved preferences are stale | SessionStart |
| `memory-redirect-check.sh` | Warns if auto-memory is not configured | SessionStart |
| `codex-edit-notify.sh` | Notifies when a codex executable is modified | PostToolUse (Write, Edit) |
| `trace-logger.sh` | Logs tool calls to the daily trace file | PostToolUse (all tools) |
| `session-close.sh` | Prompts end-of-session governance tasks | Stop |
| `subagent-conformance.sh` | Checks sub-agent output on completion | SubagentStop |

## Project Nesting

You can create child projects inside a Claudette2 instance. Each child:
- Has its own `CLAUDE.md` with `root: true` in the frontmatter
- Inherits the parent's codex via `codex: ^/^/.codex`
- Keeps its own `.state/` (memory, work tracking, test results)
- Can override specific parent codex entries by creating a local entry with the same name
- Is a **separate git repository** -- the parent's inverted `.gitignore` ignores all child directories by default

### Git Isolation

Claudette2 and its child projects are independent git repositories. The framework's `.gitignore` uses a whitelist model: everything is ignored, and only framework files (`.codex/`, `.templates/`, `.state/` manifests, root-level scripts and docs) are tracked. Any directory you create at the root level -- including child projects -- is automatically invisible to the parent repo.

This means you can `git init` a child project, give it its own remote, and manage it independently. The parent repo tracks only the framework itself. Framework updates arrive via `git pull` on the parent without affecting child projects.

### State Gravity

State gravity is the principle that all `.state/` reads and writes default to the nearest project root. If you are working in a child project, Claude writes to the child's `.state/`, not the parent's. Writing to a parent's state requires an explicit path using `^/^` notation.

This prevents state from "leaking upward" -- a child project session accidentally modifying the parent's memory or backlog. The `gravity-guard.sh` hook enforces this structurally.

### The Preference Cascade

Preferences resolve through four layers, most specific wins:

```
Session (conversational, ephemeral -- not persisted)
  |
  v overrides
<project>/.state/prefs.json (project-level)
  |
  v overrides
.state/prefs.json (instance-level)
  |
  v overrides
.codex/prefs.json (codex-level)
  |
  v overrides
.codex/pref-options.json (schema defaults)
```

Each layer is sparse -- it only contains the keys it overrides. Missing keys fall through to the next layer. `cboot.py` resolves the full cascade into `.state/prefs-resolved.json`, which is the only file Claude reads for preferences.

### Bundling for Portability

The `bundle` command packages a child project into a standalone copy by inlining all inherited codex content. The bundled project can operate independently without the parent. This is useful for sharing a project or deploying it elsewhere.

## The Platform Bridge

Claude Code has its own conventions (`.claude/skills/`, `.claude/settings.json`, agent memory). Claudette2 treats these as a generated routing layer, not a source of truth:

| Claude Code Concept | Claudette2 Equivalent |
|--------------------|-----------------------|
| `.claude/skills/` | Shims pointing to `.codex/explicit/` entries |
| `.claude/settings.json` | Generated from `.codex/settings.json` + cboot.py hook definitions |
| `~/.claude/projects/.../memory/` | Redirected to `.state/memory/` |
| `.claude/agents/` | Modules with `isolation: subagent` (planned) |

The `.claude/` directory is regenerated each boot. Never edit it directly -- changes will be overwritten.

## Sub-Agents

Some commands (like `audit`) dispatch sub-agents -- separate Claude instances with their own context window. A sub-agent is a disposable worker: it reads specific inputs, writes specific outputs, and has no persistent context. Sub-agents are declared with `isolation: subagent` in a module's frontmatter, and their access is constrained by `reads:` and `writes:` declarations.

## Glossary

| Term | Definition |
|------|-----------|
| **Apex root** | The outermost project root in a nesting hierarchy. Its CLAUDE.md has `apex-root: true`. Referenced as `^/^`. |
| **Codex** | The portable behavior layer (`.codex/`). Contains rules, commands, hooks, and preference schemas. |
| **Context root** | The nearest ancestor directory with a CLAUDE.md declaring `root: true`. Referenced as `^`. |
| **Hold** | A governance restriction. See Absolute Hold, Confirmed Hold above. |
| **Preference cascade** | The four-layer resolution system for behavioral preferences (session > project > instance > codex defaults). |
| **State gravity** | The principle that `.state/` operations default to the nearest project root, preventing state from leaking to parent projects. |
| **Sub-agent** | A disposable Claude instance dispatched by a command, with constrained access and no persistent context. |
| **start.md** | A manifest file present in every codex and state directory. Describes the folder's contents and purpose. |

## Read Next

| Document | When to Read It |
|----------|----------------|
| [README.md](README.md) | Overview and daily usage |
| [README-commands.md](README-commands.md) | Detailed command reference |
| [README-testing.md](README-testing.md) | Test infrastructure |
