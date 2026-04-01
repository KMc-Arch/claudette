---
version: 1
---

# Memory

Memory files capture knowledge — who, why, what we know. Distinct from work (what's tracked) and tests (verification records).

---

## Type Taxonomy

Each memory file carries typed frontmatter:

```yaml
---
name: <descriptive name>
description: <one-line summary — used for relevance matching without loading full file>
type: <user | feedback | project | reference | preferences | abstract>
updated: <YYYY-MM-DD>
---
```

### Retrieval Semantics

| Type | When loaded | When written |
|---|---|---|
| `user` | Boot (always) | When user details emerge |
| `feedback` | Boot (always) | When user corrects or confirms approach |
| `project` | On relevance match | When project context changes |
| `reference` | On relevance match | When external resource locations are learned |
| `preferences` | On relevance match | When behavioral preferences emerge |
| `abstract` | Boot (always) | Session close (rewritten from scratch) |

### Body Templates

**user** — structured profile. Sections for identity, collaboration style, preferences.

**feedback** — lead with the rule, then `**Why:**` (the reason) and `**How to apply:**` (when/where it kicks in).

**project** — lead with the fact or decision, then `**Why:**` and `**How to apply:**`.

**reference** — pointer to external resource with its purpose and when to consult it.

**preferences** — behavioral preference with context for why it matters.

**abstract** — rolling synthesis. See "Rolling Abstract" below.

---

## Self-Sufficiency Rule

Every memory file must stand alone. Never write "see [filename]" — state the finding. The file must be interpretable without reading any source material.

---

## Rolling Abstract

`state-abstract.md` (type: `abstract`) is rewritten from scratch each session close. It synthesizes all memory files, active work items, and recent test results into a single orientation document.

- A reader of `state-abstract.md` alone, with no access to source files, must understand the full project state
- The abstract is a **synthesis of** memory files, not a **replacement for** them — facts must exist in a typed memory file before they appear in the abstract
- The abstract references memory files as its sources

---

## Decision Archival

Active `decisions.md` carries only current (non-archived) decisions. Archived decisions rotate to `decisions-archive-YYYYMMDD-YYYYMMDD.md` where the date range encodes the earliest and latest decision dates in that file. Multiple archive files may exist. Loaded on demand, not at boot.

---

## Signal Prefixes

See `.state/start.md` for the canonical taxonomy. In memory context:
- `SURPRISE:` — recorded fact contradicts a prior assumption; flag for re-evaluation
- `DECISION:` — a design choice was made; downstream memory files may need updating

---

## Memory Index

<!-- Live index of all memory files. One line per file with description.
     Designed to survive context window truncation.
     Update this section when memory files are added, renamed, or removed. -->

See [MEMORY.md](MEMORY.md) for the full index.
