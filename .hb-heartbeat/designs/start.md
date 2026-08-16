---
version: 1
---

# designs

The drawn statement of what Heartbeat is. Drawn in the drawio standard — the notation, the editing
discipline and the layout conventions all live in `^/^/drawio/foundation/`; nothing about them is
repeated here.

| file | what it is |
|---|---|
| `heartbeat-01.drawio` | seven pages: deployment · actors and acts · one night end to end · the flag and the queue · the records · controls and the boundary · designed then built |

## Standing rules for this folder

- **The file is the design, not a picture of it.** Read the XML; do not read a render or a summary of
  it, and do not judge how it looks from a script.
- **This file has been opened by a person.** Full emission was legal exactly once, when it did not
  exist. Every later change is surgical and keyed off the cell `id`; geometry, waypoints and edge
  anchors belong to the human from here on.
- **Cut a new number** (`heartbeat-02.drawio`) when a state is worth re-opening beside the old one.
  Keep the old file whole.
- **Compression stays off.**

## Where the drawing stops

The drawing is the source of truth for the *design*. Once the thing is running, the host is the truth
about what is *actually so* — the versions on page 1 especially. When the two disagree, the drawing
states the intent and loses the fact.

## Relation to the prose

`../spec.md` is the original build contract, `../plan.md` records every ratified deviation from it,
and `^/.state/tests/mileqa/20260815-2225/` holds the review that closed the build. The pages here say
the same system in one register rather than three, and are the fastest way in; where a page and
`plan.md` disagree, `plan.md` is the decision of record and the page is stale.
