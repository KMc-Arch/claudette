---
version: 1
---

# roots-register

The single writer of durable identity and claim rows. `roots_register` (the
`root_id` identity spine), `agent_registry` (the SCD2 @name claim ledger), and
the `agent_optin` decision are written HERE and nowhere else — save the one-time
schema bootstrap in `cboot._migrate_to_v1`, which writes these tables directly as
it mints the spine and re-keys the legacy rows (the module cannot write a spine
that does not yet exist). That runs once per db, guarded by `PRAGMA user_version`;
every mutation after it goes through the module. See the module docstring for the
transaction contract (execute, never commit — the caller commits) and the identity
rules (`root_id` is minted once and never reused; a relink preserves it and
re-slugs the transcript store).

Called by boot's first-touch prompt (`cboot` — WP-E) and the `/roots` reconfigure
command (WP-F); `/move-project` will call it too once it lands on this branch.
None of them may carry its own INSERT/UPDATE of those tables — a second copy of
claim-mutation is the divergence bug the shared `agent-ownership` and
`transcript-slug` modules also exist to prevent.

Imports, never reimplements: `agent-ownership` for name derivation
(`derive_agent_name` / `suffixed` / `desuffix` / `reserved_names`, re-exported
here) and `transcript-slug` for `project_slug` (the store re-slug in `relink`).
