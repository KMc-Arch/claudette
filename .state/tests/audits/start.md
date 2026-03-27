---
version: 1
---

# Audits

Immutable point-in-time verification records. Each audit run produces a timestamped folder containing findings and a codex snapshot.

## Immutability Rule

Audit outputs are **never retroactively edited**. An audit is what it is until it is purged (and purge explicitly excludes audits from its default scope). Findings reflect what was observed under the rules that existed at the time.

## Folder Structure

```
YYYYMMDD-HHMM/
    codex-snapshot/     # Frozen copy of relevant codex state at run time
    <project>/
        <spec>.md       # One file per spec, named to match (e.g., architecture.md)
        decisions.md    # Post-hoc resolutions (created when needed, not preemptively)
```

## Codex Snapshot

Each run includes a `codex-snapshot/` subfolder capturing the codex entries that were active when the audit ran. This enables traceability — you can see exactly what rules were in effect when findings were produced.

## Post-Hoc Resolution

Since audit outputs are immutable, resolutions (false positives, acknowledgements, superseded findings) go in a companion `decisions.md` file within the audit folder. This preserves the original findings while recording what was learned after the fact.

## Timestamping

Folder names use `YYYYMMDD-HHMM` format (date + time, minute precision). This enables chronological sorting and side-by-side comparison across runs.
