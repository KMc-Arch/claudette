# State Gravity

All `.state/` reads and writes default to the nearest `root: true` context — the session root's `.state/`, resolved from the launch directory (not live CWD; see `^` resolution). Deviations require the user to explicitly provide a path using `^` or `^/^` notation.

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

Enforced by `gravity-guard.sh` (PreToolUse hook) **for file-write tools only**. The hook is registered on the
`Write|Edit` matcher, so a `.state/` write outside `^` is blocked when it comes through `Write` or `Edit` — and is
**not seen at all** when it comes through `Bash` (`echo >`, `tee`, `sed -i`, an interpreter one-liner) or through
`NotebookEdit`, which that matcher does not match. Those paths rest on the directive alone. Recorded as a
single-layer gap in `^/.state/work/boundaries.md` (BDRY-10); the notebook half is BL-56.

Within-`^` gravity violations (e.g., parent session writing to child's `.state/` without explicit notation) are harder to detect and rely on the `session-compliance` reflexive module for post-hoc review.

**On the relationship to containment.** For the writes it *does* see, `gravity-guard`'s block set is a **subset** of `containment-guard`'s: a `.state/` write above `^` is above `^`, and containment already blocks everything above `^`. Gravity is therefore a **redundant, `.state`-specific layer** over containment for those paths, not an enforcement of anything containment misses — kept deliberately as defense-in-depth (a `.state`-specific message, and independent coverage if containment regresses), not because it reaches further. The one thing neither guard enforces is the *within-`^`* case above, which is the reflexive module's job, not a hook's.
