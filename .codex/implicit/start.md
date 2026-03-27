---
version: 1
---

# Implicit

Implicit entries load eagerly at session boot, in priority order. They establish the foundational interpretation rules that all other codex entries depend on.

## Priority Tiers

Tiers load sequentially — all entries in tier N must complete before tier N+1 begins.

| Tier | Name | Purpose |
|---|---|---|
| `01-infrastructural/` | infrastructural | Must load before ANY output. Boot-critical. |
| `02-foundational/` | foundational | Core rules. Load after 01. |
| `03-standard/` | standard | Normal boot entries. |
| `04-supplementary/` | supplementary | Loaded last. Nice-to-have. |

Sub-band ordering and intra-tier load order are defined in `.codex/start.md` under "Loading Rules."

## Safe-Mode Boot

Load only tiers 01 and 02, skip 03 and 04. Future protocol — not yet implemented.
