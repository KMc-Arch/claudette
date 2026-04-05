# Plan Format

All plans use progressive-disclosure format with three layers. Each layer is self-contained at its resolution — the user reads deeper only where needed.

---

## Layers

### Layer 1 — Executive Summary

1–2 sentences: what, why, approach. Sufficient to approve or reject the direction.

Follow immediately with **Assumptions**: list every significant judgment call you're making (architectural choices, ambiguous requirements, trade-offs). State what you chose and why in one line each. These are decisions for the user to veto, not open questions for them to answer.

### Layer 2 — Section Map

Numbered phases/sections, each with:
- One-line summary
- Complexity weight: **light** / **moderate** / **heavy**
- Estimated diff size
- Impacted folders

End with a short **Risks / Open Questions** list.

### Layer 3 — Full Detail

Expand each section from the map into implementation bullets with specific file paths and changes. Maintain the same order and numbering as the map.

---

## Formatting

Separate each layer with a `---` divider.

---

## Scaling

The format is a ceiling, not a floor. For light plans (single-file, single-phase), Layer 2 can be one line and Layer 3 can be omitted entirely. The key invariant is: **assumptions always appear at Layer 1**, so wrong calls get corrected before detail work begins.
