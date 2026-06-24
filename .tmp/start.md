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

Purge-eligible: `purge` sweeps `.tmp/` contents — `sandbox/` in default scope, and loose buffers under `purge all` (with a freshness guard so recently-touched buffers are not clobbered). This `start.md` and any `_`-prefixed items are never removed.
