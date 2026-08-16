# Heartbeat (HB) — Build Specification

Nightly unattended backlog execution for `claudette`.

Status: ORIGINAL DESIGN CONTRACT (2026-08-15). Built 2026-08-15/16 — see `plan.md` §0 for every ratified deviation (notably D3: push + PR are ALLOWED and done by the runner, so I2 and §3's 'no PR creation' are superseded; D4/D13: paths moved to `.hb-heartbeat/` and per-project `~outbox/~inbox`). Where this file and `plan.md` disagree, `plan.md` wins.

---

## 1. Purpose

Wake on a schedule during a defined nightly window. If permitted, launch one
orchestrator that pops a single approved backlog item, works it to a defined
terminus in an ephemeral sandbox, and writes an outcome message for human
review the following day. Repeat until the window closes or quota is
insufficient.

## 2. Invariants

These are absolute. Any implementation that violates one is wrong.

| # | Invariant |
|---|-----------|
| I1 | **Branch only.** No orchestrator path produces a commit on a default branch. |
| I2 | **Local only.** No push, no remote write, no network mutation of any repo. |
| I3 | **No auto-merge.** Every path terminates in a human-reviewable diff. |
| I4 | **Sandbox state is never real.** Nothing from the sandbox clone becomes canonical except via the message channel and the human-approved branch pull. |
| I5 | **Approved items only.** The orchestrator never touches a raw backlog item. |
| I6 | **One orchestrator at a time.** Serial by design, not by accident. |
| I7 | **The LLM is never the need-detector.** All triggering is deterministic. |

## 3. Non-goals (v1)

- Parallel orchestrators
- Nested orchestration (depth lives in the queue, not the call stack)
- Automated merge, push, or PR creation
- Cross-night learning outside the message channel
- Sentinel-file ingestion (see §12 — deferred, not cancelled)

---

## 4. Components

```
┌─────────────────┐
│ Window Detector │  deterministic; issues + revokes the go-flag
└────────┬────────┘
         │ writes/removes
         ▼
    ┌─────────┐        ┌───────────┐
    │ go-flag │◄───────│ Heartbeat │  tick: flag check only
    └────┬────┘ mutate └─────┬─────┘
         │                   │ spawns
         │                   ▼
         │            ┌──────────────┐
         └───────────►│ Orchestrator │  quota gate → pop → work → terminus
            annotate  └──────┬───────┘
                             │
                     ┌───────┴────────┐
                     ▼                ▼
              ┌────────────┐   ┌─────────────┐
              │  Sandbox   │   │   Inbox     │
              │ (ephemeral)│   │ (for human) │
              └────────────┘   └─────────────┘
```

### 4.1 Scheduling substrate

**Windows Task Scheduler.** Not a daemon.

Rationale: a long-lived process on a laptop that sleeps and roams is a
reliability tarpit. Task Scheduler handles restart, missed-run, and wake
semantics. `checkWinTasks` already exists in the framework for stale-task
detection and should cover the HB task.

Two registered tasks:

| Task | Cadence | Action |
|------|---------|--------|
| `hb-window` | Twice daily (open, close) | Run window detector |
| `hb-tick` | Every N minutes (default 5) | Run heartbeat tick |

---

## 5. The go-flag

A single file. It is the permission token. **No flag, no orchestration.**

Path: `.state/hb/GO`

### 5.1 States

| State | Representation | Meaning |
|-------|----------------|---------|
| **Absent** | file does not exist | No permission. Tick sleeps. |
| **Go** | file exists, `status: go` | Permission granted, nothing running. |
| **In-flight** | file exists, `status: inflight` + PID + transcript slot | An orchestrator holds the token. |

There is no fourth state. Exhaustion and window-close both mean *absent*.

### 5.2 Schema

```yaml
status: go | inflight
issued_at: <ISO8601>          # written by detector at window open
window_closes_at: <ISO8601>   # written by detector at window open
# --- fields below present only when status: inflight ---
claimed_at: <ISO8601>         # written by heartbeat, pre-spawn
pid: <int>                    # written by heartbeat, pre-spawn
transcript_path: <path|null>  # written by orchestrator session, post-boot
item_id: <string|null>        # written by orchestrator, post-pop
```

### 5.3 Transitions

| From | To | Actor | Trigger |
|------|----|-------|---------|
| absent | go | detector | window open |
| go | inflight | **heartbeat** | tick decides to spawn (atomic, pre-spawn) |
| inflight | inflight+transcript | **orchestrator** | session boot fills the blank |
| inflight | go | **orchestrator** | reached an expected terminus |
| inflight | absent | **orchestrator** | quota exhausted |
| go \| inflight | absent | detector | window close |
| any | absent | **human** | manual kill switch |

### 5.4 Critical ordering

**The heartbeat claims. The orchestrator annotates.**

The mutation `go → inflight` must be atomic and must happen *before* the
orchestrator process is spawned. If the orchestrator claimed the flag itself,
tick N+1 could fire in the gap between spawn and claim and launch a second
orchestrator.

Use an atomic filesystem operation for the claim (rename/move, or exclusive
create of a temp then rename). Not read-then-write.

### 5.5 The transcript blank as diagnostic

`transcript_path: null` on an `inflight` flag means the orchestrator died
before its session came up. That is a distinct bug class from dying mid-item.
Preserve the distinction; do not populate it with a placeholder.

### 5.6 Kill switch

Deleting `.state/hb/GO` stops everything at the next tick. This is the
emergency brake. **Document it prominently in the README** — it is non-obvious
that removing a file is the abort mechanism.

### 5.7 Write permission

The orchestrator's ability to write the go-flag must be constrained to the two
transitions in §5.3. It must never be able to create the flag from absent, or
extend `window_closes_at`. Otherwise it can grant itself permission.

Place the flag under a path covered by the existing containment/gravity guards
and verify the guard resolves correctly from inside the sandbox root.

---

## 6. Window detector

Deterministic. No model call. Runs twice nightly via Task Scheduler.

### 6.1 At window open

1. Confirm no `GO` file exists. If one does, log an error (previous close
   failed) and overwrite.
2. Write `GO` with `status: go`, `issued_at`, `window_closes_at`.

### 6.2 At window close

1. If `GO` absent — normal, log quiet.
2. If `GO` is `status: go` — normal end of night, remove.
3. If `GO` is `status: inflight` — **corpse sweep**, see §6.3.

### 6.3 Corpse sweep

An `inflight` flag at window close means an orchestrator died dirty.

1. Check PID liveness. **If the process is alive, do not kill it silently** —
   this is the window-close-vs-in-flight-item decision (see §12, open).
2. If dead: log **loudly**. Not a debug line. This must be visible in the
   morning inbox as a distinct message type, because a corpse-swept night is
   otherwise indistinguishable from a quiet one.
3. Emit the corpse record: PID, `claimed_at`, `transcript_path` (or the
   null-blank signal), `item_id`.
4. Return `item_id` to the outbox (see §8.4).
5. Remove `GO`.

---

## 7. Heartbeat tick

**The tick reads the flag and nothing else.** It never reads quota, never
calls a model, never inspects the backlog. Cheapest possible check.

```
tick():
  flag = read(.state/hb/GO)

  if flag is absent:
      exit 0                                  # quiet, no log

  if flag.status == inflight:
      if pid_alive(flag.pid): exit 0          # running, normal
      else: log_corpse(flag); exit 0          # dead; leave for close sweep
                                              # (do NOT relaunch mid-night)

  if flag.status == go:
      claim = atomic_mutate_to_inflight(flag, pid=<reserved>)
      if claim failed: exit 0                 # lost the race, another tick won
      spawn_orchestrator(claim)
      exit 0
```

### 7.1 Why the tick must check the flag

If the tick spawned unconditionally and let the orchestrator decide, every
tick would boot a Claude Code session, load ~20k tokens of repo context, read
quota, and exit. You would burn remaining headroom discovering you have none.
The flag check is the thing that makes exhaustion cheap.

### 7.2 Dead-PID handling

A dead PID on an `inflight` flag mid-window is *not* automatically recovered.
Rationale: the failure is unexplained, and relaunching into an unknown cause
risks repeating it all night. Log it; let the close sweep clean up.

*(This is a deliberate conservatism for v1. Revisit after observing real
failure rates.)*

---

## 8. Job channel

Take-as-lease. **The atomic move is the claim.** There is no separate claim
marker, no lock, no `claimed: true` field.

### 8.1 Layout

```
.state/hb/
  GO
  outbox/        # approved items awaiting work
  inflight/      # taken, being worked
  inbox/         # outcomes awaiting human review
  diag/          # unexpected-failure records
```

### 8.2 Lifecycle

```
outbox/<item>.md ──atomic move──► inflight/<item>.md ──► inbox/<item>-outcome.md
```

Move is the claim. A crash between move and completion leaves the item in
`inflight/` — that is the orphan case, handled by §8.4.

### 8.3 Pop semantics

- Pop **one** item, highest priority.
- Pop only from `outbox/` (approved items — see §9).
- The move to `inflight/` is the single write to live state. Everything else
  the orchestrator does happens in the sandbox.

### 8.4 Orphan sweep

At window open and at window close, scan `inflight/`. Any item present with
no live PID holding it is an orphan.

- Return it to `outbox/`, incremented `attempts: N`.
- If `attempts` exceeds a threshold (default 3), move to `inbox/` as a
  failed-repeatedly outcome instead. An item that has failed three nights is
  a bug report, not a backlog item.

### 8.5 Outcome message

Every terminus writes exactly one outcome message to `inbox/`. Reuse the
`pause` file format — it is already a designed schema for structured session
context. Do not invent a new one.

Required content:

| Field | Notes |
|-------|-------|
| `item_id` | |
| `branch` | **Must be derivable from `item_id`.** Otherwise morning review means matching diffs to messages by hand. |
| `terminus` | Which terminus was reached (see §10.2) |
| `qa_result` | `converged` \| `exhausted` — **distinct outcomes.** Both exit mileqa; only one is a good diff. A branch alone does not tell the reviewer which happened. |
| `base_commit` | The pinned commit branched from |
| `files_touched` | |
| `attempts` | |
| `summary` | What was done and why it stopped |

### 8.6 Inbox consumption

**The inbox is read by a human.** It is not read by the next night's
orchestrator. This is deliberate — closing the loop with no human in it is
the thing the whole design exists to prevent.

---

## 9. Planner (prerequisite)

The nightly harness only ever touches **approved** items. Raw backlog is
noisy and under-specified; an unattended agent will do the easy wrong things
first.

- Raw backlog items pass through a planner to become approved features.
- Approval is a flag you set (`auto: ok` or equivalent) during waking hours.
- Only approved items enter `outbox/`.
- One-liners do not become features without bundling. This is also what keeps
  heavy QA (§10.3) from being wasted on trivia.

**The planner is out of scope for HB v1** but is a hard dependency for the
`outbox/` to be non-empty. Build order: planner first, or hand-approve one
item for night one.

---

## 10. Orchestrator

A **flat dispatcher.** Not a layer of intent translation.

### 10.1 Sequence

```
1.  boot session in sandbox
2.  fill transcript_path blank on GO flag
3.  read quota (§11)
4.  if insufficient → §11.3 exhaustion path, STOP
5.  pop one approved item from outbox/ (atomic move to inflight/)
6.  write item_id to GO flag
7.  provision sandbox (§10.4)
8.  plan → build → test, loop
9.  exit via /mileqa (§10.3)
10. write outcome message to inbox/
11. move item out of inflight/
12. un-mutate GO flag: inflight → go
13. exit
```

Next tick sees `go`, repeats. Depth lives in the queue: an item needing
decomposition emits **more jobs to the outbox**, it does not spawn a private
hierarchy.

### 10.2 Terminus contract

**The orchestrator's only control-flow question is: did I reach an expected
terminus?**

It does not evaluate the quality of what happened inside. Sub-agent outcomes
(planners, builders, testers) are payload, not control flow.

| Terminus | Expected? | Flag action |
|----------|-----------|-------------|
| mileqa converged | yes | `inflight → go` |
| mileqa exhausted | yes | `inflight → go` |
| iteration cap hit | yes | `inflight → go` |
| **quota exhausted** | **NO** — see §11.3 | `inflight → absent` |
| anything else | no | leave corpse; sweep handles |

Do not enumerate outcome types in the control path beyond this table. QA
exhaustion is a legitimate terminus with a bad payload — the payload
distinction belongs in the outcome message (§8.5), not the flag logic.

### 10.3 Exit rule: `/mileqa`

`/mileqa` is the exit predicate. It converges or exhausts; both terminate.

Requirements:
- Confirm the shipped version has a hard round bound. "Repeat until clean"
  without a bound is an infinite loop with a credit card.
- mileqa commits to a feature branch — that is a second write path alongside
  the outbox. Branch name must be derivable from `item_id` (§8.5).
- Consider a cheap pre-gate (tests pass + diff small) before invoking the
  full panel, to avoid heavy QA on light items.

### 10.4 Sandbox

- **Fresh pull per item**, distinct location from the live instance.
- Branch from a **pinned base commit**, not a moving HEAD.
- Real backlog is available **read-only**.
- Sandbox `.state/` mutates freely and is **discarded**. The only sanctioned
  channel out is the outbox→inbox message and the branch itself.
- The nightly run is therefore amnesiac across nights except through the
  queue. **This is an intentional constraint**, not an oversight.
- Consider `git worktree` over `clone` — same isolation, cheaper, native
  branch semantics. `bundle` is also already a framework primitive.

### 10.5 Branch hygiene

- Branch names derivable from `item_id`.
- Expire unmerged nightly branches after N days (default 5). Otherwise you
  accumulate diffs against a repo that has moved.

### 10.6 Disposal

| Review outcome | Action |
|----------------|--------|
| Good | Pull branch to live instance. **Normal merge, done awake.** Never automated. |
| Bad | Prune the branch, or return the item to backlog for a fix in a later round. |

Either path: sandbox state never becomes real.

---

## 11. Quota gating

### 11.1 Source

Claude Code pipes `rate_limits` on stdin to the statusLine command
(v1.2.80+, Pro/Max subscriptions only):

```json
{
  "rate_limits": {
    "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
    "seven_day": { "used_percentage": 41.2, "resets_at": 1738857600 }
  }
}
```

**No API call. No OAuth token handling.** The statusLine script is already
running on every turn of every session — make it a telemetry sink that writes
`rate_limits` to a known file on each invocation.

Path: `.state/hb/quota.json` — plus a write timestamp, so a reader can
distinguish "stale but valid" from "Claude Code hasn't run in days."

### 11.2 Read point

**Every orchestrator reads quota before pop.** The heartbeat does not.

The orchestrator is a live session, so its own statusLine has already fired
before it reads — the staleness problem does not arise on this path.

Gate on both windows:

- `five_hour` — the binding constraint on a single night. Your own evening
  usage eats it before midnight. Do not overlook it in favour of `seven_day`.
- `seven_day` — **this is the all-models bar.** If the orchestrator is
  Sonnet-heavy, the per-model Sonnet weekly cap can bind while `seven_day`
  still looks healthy. Not available on stdin. Accept this blind spot in v1
  rather than take on the undocumented usage endpoint.

Also check `resets_at` against now: if in the past, the reading is void.

### 11.3 Exhaustion is UNEXPECTED

The pre-pop check cleared and we hit the wall anyway. **That is a measurement
failure, not a terminus.** The sizing heuristic was wrong.

Handled ≠ expected. Designed-for ≠ expected.

Consequences:

1. Remove the `GO` flag (`inflight → absent`).
2. Write a **diagnostic** to `diag/`. Loud, not silent recovery.
3. The diagnostic must be a **dumb file write with no model call** — the
   process that noticed is precisely the one that has no quota to act with.
   Everything it writes must be already in hand:
   - the reading that cleared the gate
   - the reading (or error) at the point it blew
   - `item_id`
   - timestamp
4. If it is dead enough that even that write fails, the corpse state (§6.3)
   is the fallback signal.

Without this, you get quiet short nights and no indication the gate is
mis-sized.

### 11.4 Sizing reference

Anthropic does not publish token quotas; multipliers only. Third-party
estimates put Max 20x near ~40 Opus hours or ~480 Sonnet hours weekly. Treat
as directional. Model routing matters: on Max, Sonnet and Opus draw from
separate buckets — a Sonnet-dominant orchestrator with Opus only at the
plan/QA bookends stretches the allowance considerably.

Source of truth is `Settings → Usage`, not any estimate.

---

## 12. Open items

Carried deliberately, not forgotten:

| # | Item |
|---|------|
| O1 | **Window close vs in-flight orchestrator.** Kill mid-item, or let it finish and revoke after? Not decided. |
| O2 | **Sentinel-file ingestion.** The original trigger concept — projects drop a dirty-bit file. Deferred, not cancelled. Needs reconciling with backlog-pop as a second ingestion path. |
| O3 | **Sandbox→live branch return mechanism.** Sandbox as a git remote of live, or shared bare repo. Unspecified. |
| O4 | **Item N conflicting with item N-1.** Fresh pull per item means item 2 cannot see item 1's unapproved branch — correct, but they can produce conflicting diffs reviewed blind. |
| O5 | **Positive "ran and did nothing" signal.** A week of no runs currently looks identical to a week of quiet nights. |
| O6 | **Which of the three `.state/` queues to feed from.** Backlog, architecture debt, boundary gaps. Debt may pay best unattended and interrupt least. |

---

## 13. Rollout

**Slow start. Count-capped before quota-bound.**

| Phase | Scope |
|-------|-------|
| **Night 1** | One hand-approved item. No planner. Cap at 1 regardless of quota. |
| **Nights 2–5** | Cap at 2 items. Observe corpse rate, orphan rate, diff quality. |
| **Then** | Switch to quota-bound throughput (check pre each pop, run until the gate says stop). |
| **Later** | Planner online; `outbox/` fed automatically from approved items. |

Rationale: if the sandbox provisioning or the pop-marking is subtly wrong,
quota-bound means waking to a dozen broken branches and a spent week's
headroom, instead of one bad diff.

### 13.1 Pre-flight checks before night 1

- `remote-guard` tested **adversarially** — it is the only thing between you
  and a 3am push, and the only guard whose failure is externally visible.
- Containment/gravity guard resolves the sandbox root correctly (verify where
  the clone's `root: true` marker puts it).
- statusLine telemetry sink writing `quota.json` and being read correctly.
- Task Scheduler entries registered and visible to `checkWinTasks`.
- Kill switch documented in README.

---

## 14. Prior art

The job channel is maildir. Atomic-move-as-claim, outbox/inbox, take-don't-
mark — this is a rediscovery of a well-trodden design. That is a good sign:
the failure modes are catalogued and the answers exist. Read them rather than
rediscover them.
