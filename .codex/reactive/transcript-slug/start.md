---
version: 1
---

# transcript-slug

The single implementation of Claude Code's transcript-store slug — the name of
`~/.claude/projects/<slug>/` for a given project root. See the module docstring
for the derivation and why it is shared.

Loaded by `purge` (locate a store), the `/roots` relink (rename a store when a
root moves out of band, same `root_id`), and `/move-project` (migrate on an
in-session move). None of them may carry a copy of the rule — a second copy is
the divergence bug that the shared `agent-ownership` module also exists to
prevent.
