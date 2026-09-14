---
version: 1
short-desc: Engage a session-wide read-only hold; lift with /read-only done
writes:
  - "^/.state/holds/"
---

# read-only

Declare **this session** read-only: engage a session-wide CONFIRMED HOLD on every mutative
operation until the user lifts it with `/read-only done`. Use it when this session is a
**secondary / subordinate** one against the filesystem — e.g. an observer or reviewer session on a
root a primary session already holds ([[feedback_single_session_per_root]] makes one-active-session
the design norm; this command is how a second session runs safely against the same tree). The hold
is a *session mode*, not a per-file setting: it stays on across the whole session, surviving context
compaction via a marker flag, until explicitly cleared.

## Usage

- `/read-only` — engage the hold (idempotent: if already engaged, just re-report state).
- `/read-only done` — lift the hold; re-enable mutations.
- `/read-only status` — report current state without changing it.

## The declaration

On engage, this is the state in force — report it to the user verbatim in substance:

> This session is secondary and/or subordinate against the filesystem. CONFIRMED HOLD against any
> & all mutative operations in this session, until & unless the user subsequently calls
> `/read-only done`. Report this state to the user on-invocation.

## What the hold covers

While engaged, treat as **held (must not perform)** every operation that changes state outside your
own reasoning:

- **Filesystem:** `Write`, `Edit`, `NotebookEdit`, and any Bash that writes, moves, renames,
  deletes, or changes modes/attrs — `>`/`>>`/`tee`, `mv`, `cp` (to a new path), `rm`, `mkdir`,
  `touch`, `sed -i`, `install`, `chmod`, `ln`, package installers, build steps that emit files.
- **Git:** `commit`, `push`, branch/tag create or delete, `reset`, `merge`, `rebase`, `stash`,
  `add`, `checkout -B`/`switch -c`. (Read-only git — `status`, `log`, `diff`, `show`, `blame` — is
  allowed.)
- **State & memory:** any write under `^/.state/` (backlog, memory, traces, plans, …) — **except**
  this command's own flag machinery below.
- **Outward-facing sends:** publishing an Artifact or writing its DB/assets, `SendMessage` /
  `SendUserFile` / `PushNotification` delivery, cron create/delete, MCP writes, any network
  POST/PUT/DELETE, Gmail/Calendar/Drive writes. (An outward *send* publishes — held.)
- **Subagents:** you MUST NOT dispatch a subagent to perform any of the above — that is laundering a
  held mutation (the apex "working around a guard" CONFIRMED HOLD applies). Read-only subagents
  (`Explore`, read-only research) are fine.

**Allowed freely** (non-mutative): `Read`, `Glob`, `Grep`, `ToolSearch`, `ListAgents`,
`AskUserQuestion`, `WebFetch`/`WebSearch` (read), read-only `Artifact` actions (`read`/`list`/
`status`), read-only Bash (`ls`, `cat`, `find` without `-delete`, read-only git), and planning.

If unsure whether an operation mutates, treat it as held and ask.

## The one-off exception (per-op confirmation)

This is a genuine **CONFIRMED HOLD** (apex governance), not a blanket black-hole. If the user gives a
**direct, specific** instruction to perform one mutation while the hold is engaged:

1. State your intent to perform that single operation back to the user.
2. Wait for a single confirmation.
3. Perform **only** that operation. The hold remains fully in force afterward.

Blanket or implied mutations ("clean this up", "go ahead") do **not** satisfy this — the instruction
must name the specific operation. The wholesale lift is only `/read-only done`.

## Marker flag (survives context compaction)

The active state is recorded on disk so it is re-derivable after a context summary and visible to
other tooling. This flag is the **sole write** this command performs while the hold is engaged.

- **Path:** `^/.state/holds/read-only.<sid>.flag`, where `<sid>` is this session's id (the UUID
  segment of the scratchpad path, or the Claude Code session id). Session-discriminated so a
  secondary read-only session never clears a different session's flag. `mkdir -p ^/.state/holds/`
  if needed (infrastructure — do not ask).
- **Contents:** the engaging session id, an ISO-8601 `engaged_at` timestamp, and the declaration
  text above.
- **On engage:** write the flag (creating the dir), then report.
- **On `/read-only done`:** remove **only this session's** flag, then report the lift. If the flag
  is absent, report that the session was not under the hold.
- **On resume / after compaction:** if you find a flag matching this session's id, the hold is in
  force — treat this file as authoritative and re-report on next relevant action. Also carry the
  hold as a top-priority session fact independent of the flag.

An orphaned flag from a crashed session is harmless; boot-time reaping of stale `holds/*.flag` is a
separate enhancement (backlog), not this command's job.

## Reporting

Report on every invocation:
- `/read-only` → engaged (or already-engaged, with `engaged_at`), what is held, how to lift.
- `/read-only done` → lifted, mutations re-enabled (or: was not engaged).
- `/read-only status` → current state and, if engaged, since when.

## Interaction with other governance

This hold is **additive** — it never relaxes any standing hold. Existing ABSOLUTE / CONFIRMED HOLDs
(symlink creation, CLAUDE.md edits, guard-workarounds, `/move-project` execution, `purge all`, …)
remain in force on top of it. The strictest applicable rule always wins.
