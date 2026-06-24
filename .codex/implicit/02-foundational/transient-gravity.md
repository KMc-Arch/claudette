# Transient Gravity

All scratch and transient artifacts default to `^/.tmp/` — the `.tmp/` directory of the nearest `root: true` context. Nothing written there is authoritative; it is throwaway by construction and may be purged at any time.

---

## Rules

1. **Default is `^/.tmp/`.** Throwaway artifacts — I/O buffers (commit messages, PR-body drafts, checksum sidecars), scratch output, and disposable test/sandbox rigs — go in the nearest `root: true` context's `.tmp/`, not at the project root and not scattered elsewhere.
2. **Local, like state gravity.** A child session writes to the child's own `^/.tmp/`, never the parent's. Reaching an ancestor's `.tmp/` requires explicit `^/^` notation.
3. **Non-authoritative.** Never treat anything in `.tmp/` as a source of truth. If a value must survive, it belongs in `.state/` (durable accumulation) or git (committed) — not `.tmp/`.

---

## Relationship to State Gravity

- **State gravity** governs *durable* accumulation → nearest `.state/`.
- **Transient gravity** governs *ephemeral* scratch → nearest `.tmp/`.

Together they leave nothing throwaway scattered at the project root: durable state goes to `.state/`, scratch goes to `.tmp/`. The directory's own charter is at `^/.tmp/start.md`.

---

## Verification

Not structurally enforced — there is no guard that classifies "transient" at write time, so compliance is conventional. `purge` is the backstop — it sweeps `.tmp/` contents and surfaces transient-looking artifacts found *outside* `.tmp/`.
