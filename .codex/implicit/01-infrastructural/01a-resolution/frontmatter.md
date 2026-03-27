# Frontmatter

YAML frontmatter in CLAUDE.md and `start.md` files is **structurally authoritative**. Any reader — including meta-readers, auditors, and transient agents treating the document as artifact — MUST process frontmatter to correctly interpret the document.

Frontmatter declares what the document **is**; the body declares what to **do**.

---

## `^` — Context Root Resolution

`^` resolves to the directory of the nearest ancestor (inclusive) CLAUDE.md that declares `root: true` in its frontmatter.

### Algorithm

1. Start at the current working directory.
2. Look for `CLAUDE.md` in the current directory.
3. If found, parse its YAML frontmatter.
4. If frontmatter contains `root: true` (or `apex-root: true`, which implies `root: true`), this directory is `^`.
5. If not found or no `root: true`, move to the parent directory and repeat.
6. If the filesystem root is reached without finding `root: true`, `^` is undefined — error state.

### Scoped Rebinding

When a reader crosses into a directory whose CLAUDE.md declares `root: true`, `^` rebinds to that directory **for the scope of interpreting that project**. The reader's own `^` is unaffected — this creates a namespaced binding, not a global reassignment.

```
claudette/          # CLAUDE.md with apex-root: true → ^ = claudette/
  ProjectA/         # CLAUDE.md with root: true → ^ = ProjectA/ (when scoped here)
  ProjectB/         # CLAUDE.md with root: true → ^ = ProjectB/ (when scoped here)
```

An auditor launched from `claudette/` enters `ProjectA/`, encounters `root: true`, and rebinds `^` to `ProjectA/` for the duration of that inspection. Path references like `^/.state/` in ProjectA's CLAUDE.md resolve to `ProjectA/.state/`, not `claudette/.state/`.

---

## `^/^` — Apex Root Resolution

`^/^` resolves to the directory of the **outermost** ancestor CLAUDE.md that declares `root: true`, or to a CLAUDE.md declaring `apex-root: true` (which stops traversal immediately).

### Algorithm

1. If any ancestor CLAUDE.md declares `apex-root: true`, that directory is `^/^`. No further traversal.
2. Otherwise, `^/^` is the outermost (highest in directory tree) CLAUDE.md with `root: true`.
3. When only one `root: true` exists on the path, `^/^` and `^` resolve identically.
4. Two `apex-root: true` declarations on the same ancestor path is an error.

`^/^` is a single opaque token, not a composed path traversal.

### When to Use

Use `^/^` in child project contexts when referencing artifacts owned by the apex project — codex entries, scripts, backlog. Typical use is in discourse (backlog items, handoff notes), not in runtime paths.

### Bundle Behavior

On `bundle`, `^/^` coalesces to `^`. The bundled project becomes its own apex, so the distinction dissolves.

---

## Reserved Frontmatter Keys

See `.codex/start.md` for the full table. The keys processed during resolution:

- `root: true` — declares a context root, rebinds `^`
- `apex-root: true` — declares the ceiling, implies `root: true`, rebinds `^/^`
- `codex: "<path>"` — declares inherited codex source (child projects)
- `trigger: "<condition>"` — activation condition for reactive and reflexive entries

---

## Rules for Readers

1. **Always parse frontmatter first.** Before interpreting any body content, extract and process YAML frontmatter.
2. **Frontmatter is metadata, body is directives.** Do not treat frontmatter keys as behavioral instructions — they are structural declarations.
3. **Scope the rebinding.** A `root: true` rebinding applies only within the scope of that project. It does not alter the reader's own root.
4. **Innermost wins.** If multiple `root: true` declarations exist on a path, the innermost (deepest) one governs for that scope.
5. **Unknown keys are ignored.** Only reserved keys have defined semantics. Other keys may be present for module-specific purposes.
