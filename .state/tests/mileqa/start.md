---
version: 1
---

# mileqa reports

Run records produced by `/mileqa` (`.codex/explicit/mileqa/start.md`). Each run is a timestamped, point-in-time QA record — not edited retroactively.

## Folder Structure

```
YYYYMMDD-HHMM/
    <round/coda findings, fix summaries, verify passes — shape varies per run>
```

Run subdirectories are report data and do not carry their own `start.md` (test-safe T30a).
