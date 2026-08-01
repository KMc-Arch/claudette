---
version: 1
---

# Transient

`.tmp/` holds transient scratch for this `root: true` context. Everything here is **non-authoritative**, regenerable, and git-ignored (only this `start.md` is tracked). Nothing in `.tmp/` is a source of truth — if a value must survive, it belongs in `.state/` or git.

Writing scratch here is governed by the **transient-gravity** rule (`^/.codex/implicit/02-foundational/transient-gravity.md`): throwaway artifacts default to the nearest `root: true` context's `.tmp/`.

## Contents

Two genres live here:

- **I/O buffers** — short-lived text handed to git / `gh`: commit messages, PR-body drafts, checksum sidecars. Spent once the operation lands.
- **`sandbox/`** — disposable test rigs (e.g., throwaway project skeletons for exercising tooling).

## Lifecycle

Purge-eligible, but only under `purge all`: the **bare** `purge` sweeps nothing in
`.tmp/` — it merely **reports** `sandbox/` rigs (report-only, so live work is never
clobbered). `purge all` clears the **entire** `.tmp/` — loose buffers, `sandbox/`
rigs, and every subdir — with **no freshness guard** (explicit confirmation is its
guard). This `start.md` and any `_`-prefixed items are never removed, at any depth.
