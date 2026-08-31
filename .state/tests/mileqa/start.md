---
version: 1
---

# mileqa

Pre-milestone holistic QA run reports. Each `/mileqa` run produces a
timestamped folder holding the round-by-round blind multi-agent findings and the
convergence summary.

## Folder Structure

```
YYYYMMDD-HHMM/
    round-N.md      # per-round findings from the blind panel
    summary.md      # convergence verdict (CLEAN, or the open escalations)
    <coda>.md       # coda / verification registers as a run produces them
    sb/             # (optional) disposable full-tree clone staged for isolated
                    # testing — gitignored (see ^/.state/.gitignore)
```

Run subdirectories (`YYYYMMDD-HHMM/`) are report data and are **not** required to
carry their own `start.md`; this every-folder manifest covers the convention.
Reports are point-in-time records — read them as of their run date, not as
current state.
