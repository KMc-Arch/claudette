---
version: 1
---

# archive

Retired `.state/` artifacts, parked here instead of deleted so their history stays
recoverable. Entries are moved in by convention (e.g. the `/purge` and `/roots`
flows) under a dated, self-describing subfolder name — for example
`roots-purge-20260911/`.

- **Not authority.** Nothing here is read by boot or by live tooling; it is a
  holding area, not an input. Treat contents as historical snapshots, true as of
  the date in the folder name.
- **Naming.** `<what>-<YYYYMMDD>[/...]`, one subfolder per archived event.
- **Lifecycle.** Safe to prune when genuinely no longer needed; keep by default.
  Being `.`-prefixed elsewhere is what exempts a dir from this manifest, but
  `.state/archive/` is checked as a plain top-level `.state/` subdir, so it keeps
  this `start.md`.
