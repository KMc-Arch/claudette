---
version: 1
---

# 01a — Resolution

Interpretation directives. These establish how to resolve symbols, paths, and scope boundaries. They must be internalized before any executable module runs — everything downstream depends on these definitions being active.

## Entries

| File | Purpose |
|---|---|
| `frontmatter.md` | `^` and `^/^` resolution, reserved frontmatter keys, reader rules |
| `path-containment.md` | Session scope boundaries |
