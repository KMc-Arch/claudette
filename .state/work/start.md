---
version: 1
---

# Work

Work tracking captures all mutable project state — distinct from memory (knowledge) and tests (verification records). Completed items are deleted, not marked done — git is the record.

---

## Files

| File | Contents |
|---|---|
| `backlog.md` | Active work items, priority-tiered |
| `platform.md` | Claude Code constraints that can't be changed |
| `architecture.md` | Design debt, structural weaknesses |
| `boundaries.md` | Defense-layer gaps, observed failures |
| `enhancements.md` | Good ideas not yet implemented |

---

## Entry Schema

```markdown
### [ID] Title

**Severity:** critical | high | medium | low
**Status:** open | mitigated | resolved
**Root cause:** <description>
**Mitigation:** <description or "none">

<body>
```

**ID format:** category prefix + sequential number.

| Prefix | File |
|---|---|
| `BL-` | backlog |
| `PLAT-` | platform |
| `ARCH-` | architecture |
| `BDRY-` | boundaries |
| `ENH-` | enhancements |

**Status lifecycle:** open → mitigated → resolved. Resolved items are deleted (git preserves history).

---

## Signal Prefixes

See `.state/start.md` for the canonical taxonomy. In work context:
- `ESCALATION:` — issue exceeds current project scope; route to `^/^`
- `DECISION:` — a constraint was chosen; downstream items may be affected
- `SURPRISE:` — finding contradicts prior assumptions
- `CONFLICT:` — two valid approaches in tension; needs resolution
