# Path Containment

Sessions are scoped to `^` — the nearest `root: true` context. Do not access paths outside `^` unless the user explicitly provides a path that traverses beyond it.

---

## Rules

1. **Default scope is `^`.** All file operations (read, write, glob, grep, list) default to paths within `^`.
2. **No upward traversal without explicit notation.** Do not access `^/^` or any ancestor path unless the user provides a path using `^/^` notation or an absolute path outside `^`.
3. **No lateral traversal.** Do not access sibling projects at the same level as `^`. Each `root: true` project is an isolated context.
4. **Tool-level enforcement.** Structurally enforced by `containment-guard.sh` (PreToolUse hook). Writes outside `^` are blocked at the tool level. Reads are directive-enforced (lower stakes than writes).

---

## Relationship to State Gravity

Path containment and state gravity are complementary:
- **Path containment** is the fence — don't go outside `^`.
- **State gravity** is the default — within `^`, state operations target the nearest `root: true` context's `.state/`.

A session can be within `^` but still violate state gravity by writing to a parent's `.state/` without explicit path notation. Path containment alone does not prevent this — state gravity provides the inner boundary.

---

## Exceptions

- The user may explicitly instruct access to paths outside `^` using absolute paths or `^/^` notation.
- `.codex/` entries loaded via ancestor walk (Claude Code platform behavior) are read from outside `^` by the platform, not by the session. This is not a containment violation.
