---
version: 1
short-desc: Persist session knowledge to durable state
reads:
  - "^/.state/"
writes:
  - "^/.state/memory/"
  - "^/.state/work/"
---

# milestone

Canonize the current session's accumulated knowledge into durable `.state/` files. Unlike `pause` (which snapshots ephemeral context for resumption), milestone persists what the session *decided, learned, and discovered* into the structured state tree.

A milestone says: "this session produced durable knowledge — write it to the record."

## Usage

`milestone` — flush session knowledge to `.state/`

## Procedure

Walk the `.state/` subdirectory index. For each applicable subdirectory, evaluate what the session produced and persist it.

### 1. memory/

Survey the session for knowledge that should be durable:

| Check | Action |
|---|---|
| Decisions made? | Add to `decisions.md` (or create individual decision files per project convention). Use `DECISION:` signal prefix for decisions that constrain future work. |
| User profile details learned? | Create or update `user` type memory file. |
| Feedback received? | Create `feedback` type memory file (correction or confirmation). |
| Project context changed? | Create or update `project` type memory file. |
| External references discovered? | Create `reference` type memory file. |
| Preferences expressed? | Create `preferences` type memory file. |

Then:
- Update `MEMORY.md` index for any new or renamed files.
- Rewrite `state-abstract.md` from scratch — synthesize all memory files, active work items, and this session's contributions into a single orientation document. A reader of the abstract alone must understand the full project state.

### 2. work/

Survey the session for trackable items:

| Check | Target file |
|---|---|
| New work items discovered? | `backlog.md` (BL- prefix) |
| Platform constraints hit? | `platform.md` (PLAT- prefix) |
| Architecture debt identified? | `architecture.md` (ARCH- prefix) |
| Boundary gaps found? | `boundaries.md` (BDRY- prefix) |
| Enhancement ideas raised? | `enhancements.md` (ENH- prefix) |
| Status changes on existing items? | Update in place |
| Items resolved this session? | Delete (git preserves history) |

Follow the entry schema in `work/start.md` for all new entries.

### 3. plans/ (read-only)

Note any active plan files by name. Do not create or modify plan files — Claude Code manages their lifecycle. If a plan was completed this session, mention it in the milestone summary.

### 4. tests/, traces/, pauses/, bundles/ — skip

These subdirectories are produced by other commands and system processes. Milestone does not write to them.

### 5. prefs.json — skip unless explicitly discussed

Preference changes are rare and deliberate. Only update if the session produced an explicit preference decision.

## Output

After flushing, output a structured summary:

```
**Milestone captured**
- **Memory:** [count] files written/updated, state-abstract refreshed
- **Work:** [count] items added/updated/resolved
- **Plans:** [active plan names, or "none"]
- **Skipped:** [any subdirectory where nothing needed flushing, and why]
```

## Idempotency

Running milestone twice in the same session should be safe. The second run finds nothing new to flush and reports "nothing to persist." Memory files and work items are updated in place, not duplicated.

## Relationship to other commands

| Command | Purpose | Writes to |
|---|---|---|
| `milestone` | Persist durable knowledge | `memory/`, `work/` |
| `pause` | Snapshot ephemeral session context | `pauses/` |
| `audit` | Verify project conformance | `tests/audits/` |
