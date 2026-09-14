---
version: 1
status: stub
relevant-branch: feature/boot-core-transfer-govgen
---

# govgen (stub)

**This directory is intentionally empty on branches other than
`feature/boot-core-transfer-govgen`.** Its implementation — the governance /
dispatch **authority resolver** prototype (one resolver, actor profiles,
budget-as-admission-test; the headless cross-project dispatch channel) — lives on
that feature branch and is not merged to `main` yet.

This stub exists only so the boot manifest check (`cboot.py`) stops warning that
`govgen/` lacks a `start.md`. When `feature/boot-core-transfer-govgen` comes back
up and lands, **replace this stub** with the real module `start.md` describing the
resolver, its inputs, and how boot materialization consumes it.

Until then: nothing here is load-bearing. Do not build against this path from
`main`.
