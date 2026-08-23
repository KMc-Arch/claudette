---
version: 1
---

# ~outbox

Handoffs **from this project to another actor**. Pull-staged: the recipient reads its own
subfolder here; nothing is written across the fence into the recipient's tree.

    ~outbox/<recipient>/<ITEM>.md          # one file per item (single file — the claim is an atomic rename)
    ~outbox/<recipient>/inflight/<ITEM>.md # claimed by the recipient; a crash leaves it here (orphan)

`~`-prefixed folders are visible (not `.`-internal, not `_`-invisible). Tracking follows the
location's ignore rules: under `Testing/**` these are git-tracked fixtures (committed in 66d277d);
a real child project's mailboxes follow that child repo's own `.gitignore`.
Convention established 2026-08-09 (`~majel/~outbox`); item metadata spec added 2026-08-15 for Heartbeat.

## Recipients

| recipient | who reads it |
|---|---|
| `hb` | Heartbeat — nightly unattended runner (`^/^/.hb-heartbeat/`). Only **approved** items go here. |
| `<project-slug>` | a sibling project's session picks it up on its next boot |

## Item file — frontmatter spec

Every item is a markdown file with YAML frontmatter. Fields marked **req** are required for
`recipient: hb`; the runner rejects (moves to `~inbox/hb/<ITEM>/` as `terminus: rejected`) any item
whose required fields are missing or malformed — it never guesses.

```yaml
---
id: BL-07                        # req  stable id; filename must equal <id>.md; branch derives from it
recipient: hb                    # req  hb | <project-slug>
sender: claudette                # req  originating project name (roots.db name) — who approved/asked
project: .                       # req  repo the work applies to: "." (this project) or ^-relative path
priority: 5                      # req  0..9 — 9 = most urgent, 0 = idle filler; pop order = priority desc, then approved_at asc
status: approved                 # req  approved | rejected  (location — outbox vs inflight vs inbox — is authoritative; this is a human hint)
approved_by: KMc                 # req  human handle; hb never sets this
approved_at: 2026-08-15T22:00Z   # req  ISO 8601 UTC
source: .state/work/backlog.md#BL-07   # opt  where the item came from
attempts: 0                      # req  incremented by the orphan sweep; ≥ attempts_max → inbox as failed
attempts_max: 3                  # opt  default 3
model: sonnet                    # opt  worker model; default from config.json (sonnet)
time_cap_min: 90                 # opt  wall-clock cap for the worker; default from config.json
qa: mileqa                       # opt  exit predicate: mileqa | tests | none  (default mileqa)
pr: true                         # opt  push branch + `gh pr create` on completion (default true; never merges)
base: null                       # opt  pin a base commit; null = HEAD of the project's default branch at pop (runner records the SHA)
scope:                           # opt  path allowlist the worker must stay inside; empty = whole repo
  - .codex/start.md
depends_on: []                   # opt  item ids that must be in ~inbox as converged first (v1: informational only)
tags: []                         # opt  free-form
---
```

Body = the brief: what to do, why, acceptance criteria, anything the worker must know. Write it
for a cold reader with no memory of the conversation — the worker has none.

Priority semantics are one comparator in `hb.py::pop_order`; if 0-high/9-low ever feels more natural, flip it there.

## Lifecycle (recipient: hb)

    ~outbox/hb/<ITEM>.md ──atomic rename──► ~outbox/hb/inflight/<ITEM>.md ──► ~inbox/hb/<ITEM>/{outcome.md,context.md,state.md}

Orphan sweep (window open + close): anything in `inflight/` with no live runner → back to `~outbox/hb/` with
`attempts += 1`; at `attempts_max` it goes to `~inbox/hb/<ITEM>/` as `terminus: failed-repeatedly` instead.
