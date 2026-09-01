---
version: 1
---

# roots-register

The single writer of durable identity and claim rows. `roots_register` (the
`root_id` identity spine), `agent_registry` (the SCD2 @name claim ledger), and
the `agent_optin` decision are written HERE and nowhere else. See the module
docstring for the transaction contract (execute, never commit — the caller
commits) and the identity rules (`root_id` is minted once and never reused; a
relink preserves it and re-slugs the transcript store).

Called by boot's first-touch prompt (`cboot` — WP-E), the `/roots` reconfigure
command (WP-F), and `/move-project`. None of them may carry its own INSERT/UPDATE
of those tables — a second copy of claim-mutation is the divergence bug the
shared `agent-ownership` and `transcript-slug` modules also exist to prevent.

Imports, never reimplements: `agent-ownership` for name derivation
(`derive_agent_name` / `suffixed` / `RESERVED_NAMES`, re-exported here) and
`transcript-slug` for `project_slug` (the store re-slug in `relink`).
