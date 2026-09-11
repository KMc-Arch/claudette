# Frontmatter

YAML frontmatter in CLAUDE.md and `start.md` files is **structurally authoritative**. Any reader — including meta-readers, auditors, and transient agents treating the document as artifact — MUST process frontmatter to correctly interpret the document.

Frontmatter declares what the document **is**; the body declares what to **do**.

---

## `^` — Context Root Resolution

`^` resolves to the directory of the nearest ancestor (inclusive) CLAUDE.md that declares `root: true` in its frontmatter.

### Algorithm

1. Start at the session's launch directory (`$CLAUDE_PROJECT_DIR`), captured once at session start. Do not re-derive from the live working directory, which may change during the session.
2. Look for `CLAUDE.md` in the current directory.
3. If found, parse its YAML frontmatter.
4. If frontmatter contains `root: true` (or `apex-root: true`, which implies `root: true`), this directory is `^`.
5. If not found or no `root: true`, move to the parent directory and repeat.
6. If the filesystem root is reached without finding `root: true`, `^` is undefined — error state. **Enforcement contexts fall back to the launch directory instead of erroring** (`containment-guard.sh`, `gravity-guard.sh`): a guard with no ceiling would have to allow everything, and the launch dir fences *tighter* than any root above it would. That fallback is the only sanctioned deviation from the error state.

### What counts as a declaration

`root:`/`apex-root:` is read from the **leading** frontmatter block only — a block that starts at byte 0 (after an optional UTF-8 BOM) and is closed by a `---` line. A `root: true` in the body, or in a block that is never closed, is not a declaration.

The value may be bare or quoted, in any case, and may carry a trailing `# comment`: `true`, `True`, `TRUE`, `"true"`, `yes`, `on` all declare a root. `false` does not. Line endings may be LF or CRLF.

**Enforcement** resolvers (the containment and gravity guards) may be **more** permissive than this grammar but never less. Under-recognising a declaration walks the resolver *past* a real root to a looser ceiling, which for an enforcement context is a containment failure; over-recognising only fences tighter. For the same reason, a CLAUDE.md that exists but cannot be decided — unreadable, non-regular, a dangling or looping symlink, an unterminated block — makes an enforcement context fence **at** that directory rather than walk past it.

**Display-only** resolvers (e.g. the statusline's `🏠` tint) are exempt from the "never less" rule: under-recognising a root only mis-colours a hint, never loosens a boundary. They may implement a narrower subset, and say so where they do.

### Symlinks — resolved **as referenced**, never followed

Path containment compares paths **as referenced**: `.` and `..` are collapsed *textually* (so traversal is caught), but a symlink is **never** followed. A symlink inside `^` is therefore an **authorised extension of the project** — a write *through* it is in-project by reference, even when the link's real target is a parent's `.state/`, a sibling, or outside the tree entirely. This is a deliberate authorisation model: placing a symlink in a project is a human act of extending it. It depends on the **ABSOLUTE HOLD that keeps symlink construction human-only** (root `CLAUDE.md` boot-core) — if the agent could create symlinks, it could authorise its own egress.

The flip side is intrinsic and accepted: an in-`^` symlink pointing **out** of `^` is an egress path, and containment does **not** block it. Egress is delegated to **environment isolation** (BL-61, the unattended lane) and surfaced by `symlink-egress-scan.sh`. The guards are a **referenced-namespace** boundary, not an egress boundary — do not claim otherwise.

`..` is not a symlink: `normpath` collapses it, so `^/a/../../etc` resolves textually outside `^` and is blocked. Only symlinks get the as-referenced treatment.

This binds **every** resolver: none calls `realpath` / `os.path.realpath` on a write target or on the `^` walk. (Reading a CLAUDE.md marker still follows a link to fetch its content — that is I/O to *detect a root*, not the containment *decision*.)

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

0. Start at the same place `^` does — the session's launch directory (`$CLAUDE_PROJECT_DIR`), captured once at session start — and use the same declaration grammar. `^/^` is computed once per session, like `^`.
1. Walking up from there, if any ancestor (inclusive) CLAUDE.md declares `apex-root: true`, the **nearest** such directory is `^/^`. No further traversal.
2. Otherwise, `^/^` is the outermost (highest in directory tree) CLAUDE.md with `root: true`.
3. When only one `root: true` exists on the path, `^/^` and `^` resolve identically.
4. Two `apex-root: true` declarations on the same ancestor path is an error.
5. If the filesystem root is reached with no declaration of either kind, `^/^` is undefined — error state, same as `^`. Enforcement contexts take the same launch-dir fallback.

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

## Who May Change a CLAUDE.md

Enforced by `claude-md-immutability-guard.sh` (PreToolUse, Write/Edit) on **every** `CLAUDE.md` at any depth — the name matched case-insensitively (a trailing dot or space, or a `:stream` suffix, is ignored, since Windows opens the same file for those), plus a hardlink to it in the same directory. A parent session editing a child's `CLAUDE.md` is held to the same rule as the child's own session. Paths are taken as referenced: a symlink is its own file, and a hardlink in another directory is not detected — creating either needs Bash or a human. An existing `CLAUDE.md` must be addressed by its exact on-disk spelling: on a case-insensitive filesystem the tool's write-then-rename would otherwise change the file's name.

- **The body, the fences, and every key not in the table below are human-maintained.** `root:` and `apex-root:` set the containment ceiling `^` — the containment guard re-reads them on every write, so a flipped `root:` would widen a session's fence to its parent. `codex:` selects which governance and hooks a project runs under.
- **Agent-editable keys.** Claude may add, change, move or remove a line `<key>: <value>` at column 0 inside the leading block, for these keys only:

  | Key | Value | Purpose |
  |---|---|---|
  | `name` | 1–8 blanks, then one line of printable text (max 200 chars) that does not start with any of `[ ] { } & * ! \| > % @` or a backtick and does not contain `---`. Taken literally to the end of the line — no `#` comment stripping. | display name — `/new-project` offers to add ` Group` to a parent |
  | `orchestrator` | `true` \| `false` | orchestrator designation — **reserved: no reader consumes it yet** |

  A line moved past a protected line is re-checked like a changed one. If the file also has an indented, quoted or re-cased line for the same key, readers disagree on which line wins, so that key is human-only in that file. To remove a key, include its line break in `old_string` — see the next point.
- **Judged by the result** — the file as it will be after the tool runs — never where the edit lands. Where Claude Code's Edit tool transforms text, every result it could produce is checked: an empty `new_string` also deletes the line break after the match, so both the result with that line break and the one without it must pass.
- **Plain LF only.** A `CLAUDE.md` containing a CR, a BOM, or any other line-break character (VT, FF, FS/GS/RS, NEL, U+2028, U+2029) is human-maintained in full, and no edit may introduce one. The Edit tool rewrites line endings across a file, and those characters make readers disagree on where the block ends. A frontmatter block that ends past 64 KiB is refused too: the containment guard reads only that much.
- **Fails closed** on anything the guard cannot vet: no leading block, non-UTF-8, an `old_string` not found verbatim, a path it cannot stat cleanly (only a clean not-found counts as absent), device-namespace (`\\.\` / `\\?\`), drive-relative and `/proc` paths, a drive path under a POSIX interpreter, a Windows path too long to vet.
- **Creating** a `CLAUDE.md` that does not exist yet is allowed (scaffolding: `/new-project`, `/bundle`, `/rebuild`). It cannot widen the containment fence — a new marker can only add a root, which fences tighter. But its body is **not** confined to future sessions: Claude Code loads a `CLAUDE.md` into the running session when it reads a file in that folder (not for the agent that just wrote it, but for subagents, for the main thread after compaction, and for any other session), every existing project below it picks it up through the upward CLAUDE.md walk, and one with `apex-root: true` between the apex and a child moves where that child resolves `^/^`, and so its codex. Most such files are also git-ignored at the apex, so they need not show in a diff.
- The grammar is **line-oriented** (`key: value` per line); no reader in the codex parses frontmatter as full YAML, so inserting an agent-editable line cannot change another key's meaning. A reader that adopts full YAML must revisit this.
- To make a key agent-editable, add it to `ALLOWED` and `VALUE` in the guard and to this table.
- **Not covered:** Bash writes (BDRY-10); and two Edits issued in parallel, which are each vetted against the same starting file, so their composition is not seen.

---

## Rules for Readers

1. **Always parse frontmatter first.** Before interpreting any body content, extract and process YAML frontmatter.
2. **Frontmatter is metadata, body is directives.** Do not treat frontmatter keys as behavioral instructions — they are structural declarations.
3. **Scope the rebinding.** A `root: true` rebinding applies only within the scope of that project. It does not alter the reader's own root.
4. **Innermost wins.** If multiple `root: true` declarations exist on a path, the innermost (deepest) one governs for that scope.
5. **Unknown keys are ignored.** Only reserved keys have defined semantics. Other keys may be present for module-specific purposes.
