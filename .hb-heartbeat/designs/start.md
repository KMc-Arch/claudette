---
version: 1
---

# designs

The drawn statement of what Heartbeat is. Drawn in the drawio standard — the notation, the editing
discipline and the layout conventions all live in `^/^/drawio/foundation/`; nothing about them is
repeated here.

| file | what it is |
|---|---|
| `heartbeat-03.drawio` | **current.** Pages 2 and 4 redrawn; the rest repaired. Lints clean. |
| `heartbeat-02.drawio` | labels cut to verbs. Still unreadable as a graph: lines pass behind boxes, independent runs sit 14px apart, and nothing marks a crossing. |
| `heartbeat-01.drawio` | first cut. Kept whole. Its edge labels are sentences, which drawio renders unwrapped at the line's midpoint — so they run over the shapes at both ends. Legible as a record, not as a diagram. |

Drawn against the standard as of `drawio@a30a4de` — theme-adaptive, so it reads in either app theme.
When the standard revises a device, this file is re-passed to match rather than left on the old one.

## Standing rules for this folder

- **The file is the design, not a picture of it.** Read the XML; do not read a render or a summary of
  it, and do not judge how it looks from a script.
- **This file has been opened by a person.** Full emission was legal exactly once, when it did not
  exist. Every later change is surgical and keyed off the cell `id`; geometry, waypoints and edge
  anchors belong to the human from here on.
- **Cut a new number** (`heartbeat-02.drawio`) when a state is worth re-opening beside the old one.
  Keep the old file whole.
- **Compression stays off.**
- **Lint before you cut a version.** `python3 lint.py heartbeat-0N.drawio` — six geometry rules, each of
  them written because a cold reader holding only a PNG failed at it. Zero, or it is not publishable.
- **Ownership is drawn, not stated.** What a doer makes goes inside its lane; containment takes no edge.
  Page 2 went from 25 edges to 12 by doing this, and the "column" its own note referred to became a thing
  a reader can actually see.
- **Edges converging on, or diverging from, one shape may merge** — a shared trunk is the intended
  reading. The labels then belong on the distinct segments, near the ends that tell the edges apart,
  never on the trunk: a label on a trunk is ambiguous between its edges and its opaque backing erases
  all of them at once. (Operator ruling, 2026-08-19.)
- **An edge label is a verb, not a sentence.** One to three words, ~17 characters, and under ten where
  the line runs through a gutter. drawio draws the label unwrapped at the path's midpoint with nothing
  behind it, so anything longer lies across whatever the midpoint happens to be over. Prose belongs in
  the box at the end of the arrow — where it is already half-said, and where it wraps.
- **Where a mark already reads, drop the label.** ER ends state their own cardinality; a derivation
  arrow states provenance. A word on top of them is a second copy that can drift.
- **Independent lines need 24px, not 14.** Measured from four cold reads: at print scale a 14px stagger
  reads as one stroke. This is stricter than the standard's 12-16px drafting figure.
- **Mark every crossing** (`jumpStyle=arc`): with no jump, a crossing and a corner are the same picture.
- **Check it, don't eyeball it.** The failure is invisible in the XML and obvious in a print: place a
  label rectangle at each edge's path midpoint and test it against every shape. Zero collisions before
  a version is cut.

## Where the drawing stops

The drawing is the source of truth for the *design*. Once the thing is running, the host is the truth
about what is *actually so* — the versions on page 1 especially. When the two disagree, the drawing
states the intent and loses the fact.

## Relation to the prose

`../spec.md` is the original build contract, `../plan.md` records every ratified deviation from it,
and `^/.state/tests/mileqa/20260815-2225/` holds the review that closed the build. The pages here say
the same system in one register rather than three, and are the fastest way in; where a page and
`plan.md` disagree, `plan.md` is the decision of record and the page is stale.
