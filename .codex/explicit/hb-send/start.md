---
version: 1
short-desc: Plan a backlog item (or a bundle) into a Heartbeat outbox item — the waking-hours gate between backlog and hb-ready
reads:
  - "^/.state/work/backlog.md"
  - "^/^/.hb-heartbeat/"
writes:
  - "^/~outbox/hb/"
---

# hb-send

The **planner** for Heartbeat: turn a raw backlog line (or a bundle of them) into ONE *definitionally
solvent* work-order and drop it in this project's `~outbox/hb/`. The item's existence in that folder
IS the flag — there is no separate "I have work" signal. Run this in **waking hours**, from inside the
target project (its `^`); you are the human gate, so nothing lands unless you confirm it.

The deterministic writer is `hb.py send` (single owner of the item format). This command owns the
*content* and the *gate*; it hands a validated spec to that writer. Never hand-write an outbox item.

## What "definitionally solvent" means

An item is solvent when **a no-memory worker on a fresh clone could take it to a self-checkable
"done" with zero decisions left that it has no rule for.** Not "no decisions" — see autonomy below.

## Protocol

1. **Confirm the root.** `^` must be the project the work applies to (run from inside it). The item
   lands in `^/~outbox/hb/`. Read `^/.state/work/backlog.md`.

2. **Take the id(s).** Ask which backlog item, or accept a bundle. A bundle becomes ONE item only if
   the lines compose into a single coherent deliverable that fits one night — otherwise send them
   separately. Pick the id (bundle → the lead id, and list the rest in the brief).

3. **Layer 1 — mechanical checks (fail closed; do not proceed on a miss):**
   - each id exists in `^/.state/work/backlog.md`
   - not already queued (`~outbox/hb/<id>.md` or `.../inflight/<id>.md`) and not already delivered
     (a merged/closed PR for it) — `hb.py send` also refuses an already-queued id
   - every path you will put in `read_scope`/`write_scope` exists in the repo (`hb.py send` re-checks
     and refuses on a miss — a dead pointer means an insolvent item)
   - the repo is clean and its default branch resolves

4. **Layer 2 — interrogate the solvency gaps (this is the planner's real work; ask me, fill them):**
   - **objective** — one bounded outcome that fits the ~90-min cap. Too big → split or narrow.
   - **acceptance** — criteria the worker can self-check under its `qa` predicate (mileqa "converged"
     / tests green). No target → not solvent.
   - **write_scope** — the path allowlist it may modify (structurally enforced: off-scope commits are
     not pushed). Push toward narrow; whole-repo is a smell.
   - **open decisions** — any "A or B" embedded in the item: resolve it NOW, or hand it to autonomy
     (below). Foreseeable forks get pre-decided here; the envelope only governs the unforeseen.

5. **Set the autonomy envelope** (`autonomy`, default `bounded`) — how the worker treats a fork it
   meets mid-attempt (only the *unforeseen* ones; foreseeable forks you already settled in step 4):

   | level | the worker may… |
   |---|---|
   | `strict` | halt on ANY fork with >1 reasonable answer — wake me for everything |
   | `bounded` | resolve forks INSIDE the contract (write_scope, no interface/schema/dep change, no objective change); halt on anything crossing it |
   | `loose` | make any decision NOT in `forbid` — completion beats perfection |
   | `god` | make ANY decision, incl. redefining the path/objective — "seeing it done at all" is the value; use only in a disposable/low-blast-radius project |

   - `loose`/`god` are **denylist-shaped**: they lean on **`forbid`** to bite. `hb.py send` warns if
     you set them with an empty forbid list. Add `forbid` entries, or step down to `bounded`.
   - `god` is not "no guardrails": the structural fence (no creds, scrub, write_scope, cap, human PR
     review) still holds. It is safe only because the *project* is disposable — say so to yourself
     before you set it.
   - `pre_auth` — name any specific out-of-contract moves you want to permit ("may add dependency X",
     "may touch `Y` outside write_scope"). These punch holes for the foreseeable.

6. **Draft the cold-reader brief** (the md body). Write it for a worker with NO memory of this
   conversation and NO ability to ask: what to do, why, how to know it is done, live pointers only
   (files/functions that exist), and — for a bundle — the full list. The overnight worker gets this
   brief with full-repo context you have now and it will not; this is the one moment to write it well.

7. **Refuse if a Layer-2 gap cannot be filled now** — do NOT half-send. Tell me what's missing and
   stop. The invariant is that the worker never meets an item it has no rule for.

8. **Show me the full item** (frontmatter + brief) and get an explicit confirm. Then write the spec
   to a scratch file inside `^/^/.hb-heartbeat/state/` and place it deterministically:

   ```
   python3 ^/^/.hb-heartbeat/hb.py send <ID> --spec <scratch>.yaml --project <^ abs path>
   ```

   (Omit `--project` only when `^` is the apex itself.) The writer composes plumbing (id, recipient=hb
   auto-derived, sender, approved_by/at, status), validates, self-checks by re-parsing, and prints the
   placed path. Remove the scratch file. Report the path and the autonomy level set.

## Spec keys (what the writer accepts)

`hb.py send --spec FILE` reads a YAML mapping of: `objective`, `acceptance`, `priority` (0–9),
`model`, `qa` (mileqa|tests|none), `pr`, `time_cap_min`, `base`, `read_scope`, `write_scope`,
`autonomy`, `forbid`, `pre_auth`, `depends_on`, `tags`, `attempts_max`, and `brief` (the md body; or
pass `--body FILE`). Plumbing keys are NOT accepted — the writer owns them; an unknown key is refused.

See `^/^/.hb-heartbeat/templates/~outbox/start.md` for the full on-disk item schema, and
`^/^/.hb-heartbeat/start.md` / `spec.md` for how the runner consumes it.
