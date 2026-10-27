---
version: 1
short-desc: Engage a session-wide read-only hold; lift with /read-only done
writes:
  - "^/.claude/skills/read-only/"
---

# read-only

Declare **this session** read-only: engage a session-wide CONFIRMED HOLD on every mutative
operation until the user lifts it with `/read-only done`. Use it when this session is a
**secondary / subordinate** one against the filesystem — an observer, reviewer, or assistant session
running alongside a **primary** session that owns the write authority over the same tree. `/read-only`
is what makes that safe: it pins this session into read-only so it cannot collide with the primary's
work. The hold is a *session mode*, not a per-file setting: it stays on across the whole session —
surviving context compaction via a re-injection hook — until explicitly cleared.

> This deliberately relies on **two sessions sharing one tree** (a primary + a subordinated
> secondary), which is the exception to the one-active-session-per-root norm ([[feedback_single_session_per_root]]).
> That is exactly why the hold is **session-scoped** (see the flag below): only *this* session is
> subordinated; the primary, with a different session id, is never affected.

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
- **State & memory:** any write under `^/.state/` (backlog, memory, traces, plans, …). This command
  writes exactly one thing — its own flag below.
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

## Session-scoped flag + how it survives compaction

The active state is recorded on disk, keyed to **this session**, so it (a) identifies which session
is subordinated and (b) can be re-injected after a context summary.

- **Path:** `^/.claude/skills/read-only/read-only-<sid>.flag`.
  - `<sid>` = **this session's id**: the UUID segment of your scratchpad directory path
    (`…/<UUID>/scratchpad`), which equals the harness `session_id`. If you cannot determine `<sid>`,
    **do NOT write a flag** — report that engage failed. A flag with the wrong/absent id would never
    match and the hold would silently fail to persist.
  - `.claude/` is git-ignored and instance-local; `cboot`'s shim generation does not delete files
    here, so the flag survives boot/resume. `mkdir -p` the directory if needed (infrastructure — do
    not ask).
  - **Contents:** the session id, an ISO-8601 `engaged_at` timestamp, and the declaration text.
- **On engage:** write the flag, then report.
- **On `/read-only done`:** remove **only this session's** flag (`read-only-<sid>.flag`), then report
  the lift. If it is absent, report that this session was not under the hold. Never touch another
  session's flag.
- **Compaction survival is the hook, not the flag alone.** `read-only-reinject.py` runs on every
  `SessionStart` (startup, resume, clear, compact, fork), reads the `session_id` from the hook
  payload, and if `read-only-<session_id>.flag` exists re-injects the hold into the fresh context.
  The flag persists on disk; the hook re-hydrates it. A brand-new session (`startup`) gets a new id,
  matches no flag, and is read-write — correct.
  - **Compaction coverage is documented; one link is not.** This hook *is* the hooks guide's own
    "re-inject context after compaction" pattern — a `SessionStart` `compact` matcher whose stdout is
    added to the post-compaction context, run "after every compaction." Automatic compaction (the
    silent context-window-fill kind) is documented to "work the same way as `/compact`" and to run
    `SessionStart(compact)` hooks, so **auto and manual are both covered**. `PostCompact` is *not* a
    context-injection channel and `PreCompact` fires too early, so `SessionStart(compact)` is the only
    supported route (a per-action `PreToolUse` enforcing hook was deliberately **not** built). The one
    thing the docs do **not** state is whether `session_id` is stable across a compaction; compaction
    continues the same session (and `compact` is distinct from `resume`/`fork`), so it almost
    certainly is — but if it ever changed, this hook's `session_id` match would miss and the hold
    would silently fail to re-inject. Confirm empirically once: engage `/read-only`, run `/compact`,
    verify the reminder returns.

## Reporting

Report on every invocation:
- `/read-only` → engaged (or already-engaged, with `engaged_at`), what is held, how to lift.
- `/read-only done` → lifted, mutations re-enabled (or: was not engaged).
- `/read-only status` → current state and, if engaged, since when.

## Interaction with other governance

This hold is **additive** — it never relaxes any standing hold. Existing ABSOLUTE / CONFIRMED HOLDs
(symlink creation, CLAUDE.md edits, guard-workarounds, `/move-project` execution, `purge all`, …)
remain in force on top of it. The strictest applicable rule always wins.
