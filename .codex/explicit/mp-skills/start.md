---
version: 1
short-desc: "Run a vendored mattpocock skill: /mp-skills <skill> [input]"
reads:
  - "^/^/.codex/mp-skills/"
writes:
  - "^/.state/plans/"
  - "^/.state/memory/"
  - "^/mp-skills/"
  - "^/.tmp/"
  - "^/~outbox/"
  - "^/.claude/settings.local.json"
  - "^/.claude/hooks/"
  - "^/ (whatever the dispatched skill writes, within its overrides)"
---

# mp-skills

Run one skill from the vendored `mattpocock/skills` library, from any project. The library and its
overrides exist once, at the apex (`^/^/.codex/mp-skills/`). Every project reads that one copy, so
there is one set of overrides to maintain. Nothing is copied into, or registered in, a project.

## Usage

```
/mp-skills <skill> [input]     run <skill>; the rest of the line is your input to it
/mp-skills                     list the available skills
```

Example: `/mp-skills wayfinder work the map at ^/.state/plans/<effort>/map.md`

## Protocol

1. Split the arguments. The first word is `<skill>`; everything after it is the user's input to the
   skill, handled as if they had typed it to that skill directly.
2. **No `<skill>`:** list the folders in `^/^/.codex/mp-skills/skills/`, each with the `description:`
   from its `SKILL.md` frontmatter, then stop.
3. **`<skill>` is not a folder there:** say so, name the closest matches, and stop. Never fall back to
   a registered or built-in skill with a similar name.
4. **Otherwise:** follow the **How to use** section of `^/^/.codex/mp-skills/start.md` for `<skill>`.
   That file is the only home of the read order, the precedence rules and the cross-reference rule;
   this entry only routes to it.

`^` stays this session's own project root throughout. Plans, glossary and decisions land in this
project's `.state/`, never the apex's (state gravity). Only the library itself is read from `^/^`.

If `^/^/.codex/mp-skills/` does not exist (for example, in a bundled copy that left the apex), say so
and stop.
