---
version: 1
---

# ~outbox

Handoffs **from this project to another actor**. Pull-staged: the recipient reads its own
subfolder here; nothing is written across the fence into the recipient's tree.

    ~outbox/<recipient>/<ITEM>.md          # one file per item (single file — the claim is an atomic rename)
    ~outbox/<recipient>/inflight/<ITEM>.md # claimed by the recipient; a crash leaves it here (orphan)

`~`-prefixed folders are visible (not `.`-internal, not `_`-invisible) and never git-tracked.
Convention established 2026-08-09 (`~majel/~outbox`); item metadata spec added 2026-08-15 for Heartbeat.

## Recipients

| recipient | who reads it |
|---|---|
| `hb` | Heartbeat — nightly unattended runner (`^/^/.hb-heartbeat/`). Only **approved** items go here. |
| `<project-slug>` | a sibling project's session picks it up on its next boot |

## Item file — frontmatter spec

Every item is a markdown file with YAML frontmatter + a markdown brief. **Do not hand-author it —
run `/hb-send`**, which vets the attributes and writes the file via the deterministic `hb.py send`
writer (the single owner of this format). The plumbing block (`recipient` … `attempts`) is set by the
writer, never by hand: `recipient: hb` is auto-derived from this folder and can never disagree with
it. Fields marked **req** must be present and well-formed or the runner rejects the item (moves it to
`~inbox/hb/<ITEM>/` as `terminus: rejected`) — it never guesses.

```yaml
---
# ── plumbing (writer-set; do not hand-edit) ──────────────────────────
id: BL-07                        # req  stable id; filename must equal <id>.md; branch derives from it
recipient: hb                    # req  auto-derived from the ~outbox/hb/ folder — never hand-set
sender: claudette                # req  originating project name (roots.db name) — who approved/asked
project: .                       # req  repo the work applies to: "." (this project) or ^-relative path
priority: 5                      # req  0..9 — 9 = most urgent, 0 = idle filler; pop order = priority desc, then approved_at asc
status: approved                 # req  approved  (location — outbox vs inflight vs inbox — is authoritative; this is a human hint)
approved_by: KMc                 # req  human handle; hb never sets this
approved_at: 2026-08-15T22:00Z   # req  ISO 8601 UTC
source: .state/work/backlog.md#BL-07   # opt  where the item came from
attempts: 0                      # req  incremented by the orphan sweep; ≥ attempts_max → inbox as failed
attempts_max: 3                  # opt  default 3
# ── contract — what & done ───────────────────────────────────────────
objective: <one bounded outcome> # opt* one line; the deliverable, sized to fit the cap (/hb-send requires it)
acceptance:                      # opt* list  criteria the worker self-checks under `qa` (/hb-send requires it)
  - <a self-checkable "done">
qa: mileqa                       # opt  exit predicate: mileqa | tests | none  (default from config)
# ── boundaries — may touch / may decide ──────────────────────────────
read_scope: []                   # opt  context allowlist — ADVISORY only in v1 (Read is not guard-enforced)
write_scope:                     # opt  modify/publish allowlist — STRUCTURAL: off-scope commits are not pushed (scope_breach). Empty = whole repo. (`scope:` is the accepted pre-split alias)
  - .codex/start.md
autonomy: bounded                # opt  worker decision envelope: strict | bounded | loose | god  (default from config)
forbid: []                       # opt  hard prohibitions; the denylist `loose`/`god` respect
pre_auth: []                     # opt  named out-of-contract moves the sender pre-approves ("may add dep X")
depends_on: []                   # opt  item ids that must be in ~inbox as converged first (v1: informational only)
# ── execution — how it runs ──────────────────────────────────────────
model: sonnet                    # opt  worker model; default from config
time_cap_min: 90                 # opt  wall-clock cap; may LOWER config item_cap_min, never raise it
base: null                       # opt  pin a base commit; null = HEAD of the project's default branch at pop
pr: true                         # opt  RUNNER pushes the branch + `gh pr create` on an expected terminus (never merges); the worker has no credentials
tags: []                         # opt  free-form
---
```

`opt*` = optional to the runtime parser but required by `/hb-send`'s solvency bar (see
`^/^/.codex/explicit/hb-send/start.md`): the parser only needs enough to pop safely (a missing
`autonomy` defaults to `bounded`); the *planner* is what enforces that an item is fit for an
unattended worker.

Body = the brief: what to do, why, how the worker knows it is done, anything it must know. Write it
for a cold reader with no memory of the conversation — the worker has none.

**Autonomy** governs a fork the worker meets mid-attempt that the brief did not settle. `bounded`
(default) lets it resolve forks *inside the contract* (write_scope, no interface/schema/dep change, no
objective change) and halt on anything crossing it (`terminus: blocked-on-decision`); `strict` halts
on any real fork; `loose` allows anything not in `forbid`; `god` allows all decisions (structural
fence still holds). Every autonomous call is recorded in the worker's commit history and its outcome
`## Decisions` ledger. See `^/^/.hb-heartbeat/prompt-worker.md`.

Priority semantics are one comparator in `hb.py::pop_order`; if 0-high/9-low ever feels more natural, flip it there.

## Lifecycle (recipient: hb)

    ~outbox/hb/<ITEM>.md ──atomic rename──► ~outbox/hb/inflight/<ITEM>.md ──► ~inbox/hb/<ITEM>/{outcome.md,context.md,state.md}

A sidecar `inflight/<ITEM>.pid` (pid + process start time) marks the live runner. Orphan sweep (window open + close):
anything in `inflight/` whose sidecar pid is dead → back to `~outbox/hb/` with `attempts += 1`; at `attempts_max` it
goes to `~inbox/hb/<ITEM>/` as `terminus: failed-repeatedly` instead. Invalid frontmatter → `~inbox/hb/<ITEM>/` as
`terminus: rejected` (never guessed).
