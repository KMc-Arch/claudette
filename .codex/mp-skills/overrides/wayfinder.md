---
version: 3
---

# wayfinder overrides

The tracker is local markdown under `^/.state/plans/<effort>/` (see `common.md`). This maps
wayfinder's tracker vocabulary onto it.

| Wayfinder term | Here |
|---|---|
| Map issue, label `wayfinder:map` | `^/.state/plans/<effort>/map.md` (the map body per SKILL.md), plus a `start.md` in the effort folder pointing at it |
| Child ticket | `^/.state/plans/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body |
| `wayfinder:<type>` label | a `Type:` line: `research` / `prototype` / `grilling` / `task` |
| Claim (assign) | `Status: claimed`, saved **before** any work |
| Resolution comment + close | append `## Answer`, set `Status: resolved`, then add a gist + link line to the map's Decisions so far |
| Native blocking | a `Blocked by: NN, NN` line; a ticket is unblocked when every listed file is `resolved` |
| Frontier query | scan `issues/` for files that are not resolved, unblocked and unclaimed; lowest number wins |
| Rule out of scope (close) | `Status: out-of-scope`, plus one line in the map's Out of scope section |
| Research on a `research/<name>` branch | a findings file per `common.md`; no branch |
| "Call the Skill tool with grilling / domain-modeling / research / prototype" | read those skills by path from `/mnt/claudette/.codex/mp-skills/skills/` (plus their overrides) |

**Refer by name:** a ticket's name is its first-line title. Link the file path inside the name.

**After the destination is reached:** decisions live in their tickets while the effort is live. At
the end, promote any lasting design decision into `^/.state/memory/decisions/` with a link back to
its ticket, so the durable record stays in one known place.

## Asking the operator: numbered questions, lettered veto list

A ticket session often puts questions to the operator and, in the same message, lists what it
will record unless the operator vetoes it. Label both, so every reply can point at an item
("Q2: yes. Veto C."):

- **Questions** keep grilling's form: `❓ **Q1** - **<title>**: …`, with the recommended answer
  on a `➡️` line.
- **The veto list is lettered, never plain bullets.** Lead with `Recording unless you veto:`,
  then one item per line as `**A** - <what gets recorded, and where>`, then `**B**`, `**C**`, and
  so on. Keep each item on its own rendered line (a `- ` marker before the letter, or a blank
  line between items), so the terminal doesn't run them together.

Letters restart in each message. An item carried into a later message is re-listed under its new
letter. A reply that doesn't veto a letter accepts it; a vetoed item is not recorded; a veto that
comes with an amendment records the amended item.

When the final message still carries questions or a veto list, they come **before** the
read-out, which stays last.

## Session read-out

Every map session — charting or working — ends with one read-out, and it is the **last thing in
the final message**. Shape: a lead, then exactly one stats table, then the prompts. Never a table
per prompt, and the prompts never restate the table.

**The lead**, in this order:

1. **Outcome** — what this session changed, by name (the ticket resolved, or the map charted),
   how it was verified, and where the record stands (committed, pushed, or uncommitted).
2. **What was decided** — the gist as bullets, consistent with the line appended to the map's
   Decisions so far.
3. **What verification changed** — only if a review or check changed the record; omit otherwise.
4. **Handed on** — anything deferred that the operator may want to settle now instead, with a
   one-line why.

**The stats table**, counted from the issue files at read-out time, never from memory:

| Tickets | Session | Lifetime | Detail |
|---|---|---|---|
| Resolved | | | the resolved tickets, by name |
| Open | | | claimed/in-progress count as open; name the unblocked ones |
| Closed | | | every non-resolved closure (out of scope, merged, deleted) in one row |
| Added | | | tickets created after charting |
| **Total** | | | footer: charted + added |

"Session" counts only this session's changes. The Lifetime total needs the charted count, and a
deleted ticket leaves no file to count, so **charting records it on the map**: a
`Charted: <N> tickets (<date>)` line in the map's Notes, written in the charting session. On a
map charted before this rule, backfill that line from the charting record (e.g. the charting
commit) before the first read-out.

**The prompts**, after the table: one fenced, ready-to-paste post-`/clear` prompt per
**frontier ticket only** (open, unblocked, unclaimed — a ticket another session has claimed gets
none), each under a bold label of number, name, and a few words on the question, so the operator
picks by interest at a glance. **Last**, the map's reusable prompt, which names no ticket and
lets the session take the next frontier ticket itself:

```
use /mnt/claudette/.codex/mp-skills/skills/wayfinder — work the map at ^/.state/plans/<effort>/map.md
```

It never changes for a map, because the map's Notes carry the standing instructions. If the
operator runs frontier tickets in parallel, sessions start a few seconds apart: a claim is only a
file edit.

**Write the read-out in the operator's language:** ticket names and the artifacts' own section
headings, never skill-internal metaphor the operator doesn't use (the map section is "Not yet
specified", not "fog").
