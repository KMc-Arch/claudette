# Identity Isolation

Each project operates as an independent context. Do not import identity, preferences, context, or memory from other projects or global configuration unless explicitly instructed.

---

## Rules

1. **No cross-project context.** Do not reference knowledge about the user, their preferences, or their work from other projects. Each `root: true` boundary is an identity boundary.
2. **No global memory import.** Do not read from `~/.claude/` global memory or auto-memory paths. `.state/memory/` within the current `root: true` context is the only memory source.
3. **No tone/style leakage.** Behavioral preferences are set by the preference cascade for THIS context, not carried over from a prior session in a different project.
4. **Child projects inherit codex, not state.** A child project inherits governance rules from `^/^/.codex` but NOT memory, work tracking, or preferences from `^/^/.state/`. The child's `.state/` is its own.

---

## Exceptions

- The user may explicitly instruct cross-project context sharing (e.g., "use the same approach we used in ProjectX").
- Codex entries loaded via ancestor walk are shared governance, not shared identity — they define HOW to work, not WHAT is known.
- `^/^` path notation from the user is an explicit authorization to cross the boundary.
