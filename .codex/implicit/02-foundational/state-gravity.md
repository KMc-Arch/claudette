# State Gravity

All `.state/` reads and writes default to the nearest `root: true` context — the current working folder's `.state/`. Deviations require the user to explicitly provide a path using `^` or `^/^` notation.

---

## Rules

1. **Default is local.** When writing memory, work items, test outputs, or any `.state/` content, target the `.state/` directory of the nearest `root: true` context.
2. **Explicit notation required for parent access.** Writing to `^/^/.state/` (or any ancestor `.state/`) requires the user to provide the `^/^` path explicitly. Do not infer "this belongs in the parent" — if the user wants it in the parent, they'll say so.
3. **Backlog routing follows gravity.** The backlog routing directive ("write to the lowest-level `root: true` project's backlog") is a specific application of this rule.

---

## Relationship to Path Containment

- **Path containment** is the fence — don't go outside `^`.
- **State gravity** is the default — within `^`, state operations target the nearest `root: true` context's `.state/`.

A session can be within `^` but still violate state gravity by writing to a parent's `.state/` without explicit path notation. Path containment wouldn't catch this — state gravity does.

---

## Verification

Structurally enforced by `gravity-guard.sh` (PreToolUse hook). Writes to `.state/` paths outside `^` are blocked at the tool level.

Within-`^` gravity violations (e.g., parent session writing to child's `.state/` without explicit notation) are harder to detect and rely on the `session-compliance` reflexive module for post-hoc review.
