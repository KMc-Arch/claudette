---
version: 1
short-desc: Restore session context from a prior pause
reads:
  - "^/.state/pauses/"
writes: []
---

# unpause

Restore session context from a prior pause.

## Usage

`unpause` — list recent pauses and select one to restore

## Procedure

1. **List** the 3 most recent folders in `^/.state/pauses/` (by folder name, descending).
2. **Ask** the user which to resume from.
3. **Read** both files (`context.md` and `state.md`) from the selected pause.
4. **Re-establish context** — internalize the session state as if you had been working on it.
5. **Output** a structured summary:

```
**Resumed: YYYYMMDD.N**
- **Context:** [what we were doing]
- **State:** [files touched, current status]
- **Pending:** [next actions or "none"]
```
