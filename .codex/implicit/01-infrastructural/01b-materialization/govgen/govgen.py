#!/usr/bin/env python3
"""govgen.py — governance resolver: emits the exactly-right governance
payload for an actor class (prototype: `subagent` profile only).

The dispatcher runs this at dispatch time and embeds the emitted preamble in
the Agent prompt. Gravity and containment arrive RESOLVED (concrete paths),
not semantic (`^` notation) — a blind subagent needs no resolution rules to
comply. Deterministic: identical sources + arguments produce identical
output. The sentinel version hash covers the template, the profile table,
and this script — it versions the GENERATOR, not the per-dispatch payload.

Emission is fail-closed: content that would break the preamble frame (line
or paragraph separators, sentinel-colliding text), a contract entry or
annotation token that escapes its containment base, backslash separators,
an unparseable module frontmatter, or a payload over the profile budget is
refused loudly (exit 2 / exit 3), never trimmed, escaped, or silently
degraded. Entries needing an apex when none is known fall back to
`as-declared:` — semantic notation is never half-resolved.

Usage:
    python govgen.py subagent --root <path> [--module <name>]

Exit codes: 0 emitted; 2 usage/validation error; 3 profile budget exceeded.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent

# budget: hard byte ceiling for the emitted payload — the region admission
# test, mechanized. Exceeding it is a failure (exit 3), never a silent trim.
PROFILES = {
    "subagent": {"template": "sub-preamble.md", "budget": 2000},
}

_MODULE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
# frame-breaking characters: LF, CR, VT, FF, NEL, LS, PS
_BREAK_CHARS = "\n\r\x0b\x0c\x85  "


def _die(msg: str, code: int):
    print(f"govgen: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").lstrip("﻿")


def _apex() -> Path | None:
    cpd = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(cpd).resolve() if cpd else None


def _strip_comment(v: str) -> str:
    """Drop a YAML inline comment (`#` at start or after whitespace, outside
    quotes). A quote only OPENS at a token boundary (start / space / comma /
    `[`), so an interior apostrophe in a plain scalar does not defeat
    stripping while quoted elements — including inside flow lists — protect
    their `#` and `,` content."""
    v = v.rstrip()
    q = None
    for i, ch in enumerate(v):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'" and (i == 0 or v[i - 1] in " \t,["):
            q = ch
        elif ch == "#" and (i == 0 or v[i - 1] in " \t"):
            return v[:i].rstrip()
    return v


def _unquote(v: str) -> str:
    """Symmetric quote strip: only when the SAME quote wraps the whole value."""
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _split_flow(inner: str) -> list[str]:
    """Split flow-list innards on commas, quote-aware. An unterminated quote
    degrades to a SINGLE preserved item (never fragmented garbage)."""
    parts, buf, q = [], [], None
    for ch in inner:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if q is not None:
        return [_unquote(inner.strip())]
    parts.append("".join(buf))
    return [_unquote(p.strip()) for p in parts if p.strip()]


def _scalar(v: str):
    v = _unquote(_strip_comment(v).strip())
    return {"true": True, "false": False}.get(v.lower(), v)


def parse_frontmatter(text: str) -> dict:
    """Flat `key: value` pairs, block lists (`- item` lines), and flow lists
    (`key: [a, b]` / `key: []`, quote-aware split). Blank and full-line
    comment lines inside a block list are skipped WITHOUT ending the list
    (matching YAML), never silently truncating declarations."""
    if not text or not text.startswith("---"):
        return {}
    m = re.search(r"(?m)^---[ \t]*$", text[3:])
    if not m:
        return {}
    fm: dict = {}
    list_key = None
    for line in text[3:3 + m.start()].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue  # blank/comment lines are inert — they do not end a block list
        item = re.match(r"\s*-\s+(.*)$", line)
        if item and list_key is not None:
            fm[list_key].append(_unquote(_strip_comment(item.group(1)).strip()))
            continue
        if ":" not in line:
            list_key = None
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = _strip_comment(value.strip())
        if value == "":
            list_key = key
            fm[key] = []
        elif value.startswith("[") and value.endswith("]"):
            list_key = None
            inner = value[1:-1].strip()
            fm[key] = _split_flow(inner) if inner else []
        else:
            list_key = None
            fm[key] = _scalar(value)
    return fm


def _payload_safe(s: str, what: str) -> str:
    """Refuse content that would break the preamble frame. Fail-closed."""
    if any(ch in s for ch in _BREAK_CHARS):
        _die(f"{what} contains a line/paragraph separator — refusing to emit", 2)
    if "GOV-PREAMBLE" in s or s.lstrip().startswith("==="):
        _die(f"{what} collides with the sentinel frame — refusing to emit", 2)
    return s


def resolve_root(arg: str) -> Path:
    """Absolute path, ^/-prefixed (resolved against CLAUDE_PROJECT_DIR, cwd
    fallback), or cwd-relative. Empty/whitespace and the filesystem root are
    refused; a root outside CLAUDE_PROJECT_DIR warns but proceeds."""
    if not arg or not arg.strip():
        _die("--root requires a non-empty path", 2)
    if arg.startswith("^/"):
        base = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        root = (Path(base) / arg[2:]).resolve()
    else:
        root = Path(arg).resolve()
    if not root.is_dir():
        _die(f"root is not a directory: {root}", 2)
    if root == Path(root.anchor):
        _die("the filesystem root is not a valid dispatch root", 2)
    apex = _apex()
    if apex is not None:
        try:
            root.relative_to(apex)
        except ValueError:
            print(f"govgen: WARNING — root {root.as_posix()} lies outside "
                  f"CLAUDE_PROJECT_DIR ({apex.as_posix()}); fence emitted as given.",
                  file=sys.stderr)
    return root


def root_warning(root: Path) -> str | None:
    claude_md = root / "CLAUDE.md"
    try:
        if claude_md.is_file():
            fm = parse_frontmatter(_read(claude_md))
            if fm.get("root") is True or fm.get("apex-root") is True:
                return None
    except (OSError, UnicodeDecodeError) as exc:
        return (f"govgen: WARNING — {claude_md.as_posix()} could not be read "
                f"({type(exc).__name__}); treating root as undeclared.")
    return (f"govgen: WARNING — {root.as_posix()} has no root: true CLAUDE.md; "
            "the fence still applies, but `^` binding is dispatcher-declared only.")


def _join_contained(base: Path, rest: str, entry: str) -> str:
    """Join rest onto base, normalize, and refuse escapes — textual for
    not-yet-existing paths, physical (symlink-resolved) for existing ones.
    A contract entry resolving outside its containment base contradicts the
    fence and is an authoring error, never something to launder into the
    payload."""
    trail = "/" if (rest.endswith("/") or rest == "") else ""
    joined = Path(os.path.normpath(str(base / rest))) if rest else base
    try:
        joined.relative_to(base)
    except ValueError:
        _die(f"contract entry {entry!r} escapes its containment base "
             f"({base.as_posix()}) — refusing to emit", 2)
    if joined.exists():
        try:
            joined.resolve().relative_to(base.resolve())
        except ValueError:
            _die(f"contract entry {entry!r} physically escapes its containment "
                 f"base via a symlink — refusing to emit", 2)
        except OSError:
            pass  # unreadable resolution: keep the textual verdict
    return joined.as_posix() + (trail if not joined.as_posix().endswith("/") else "")


def _resolve_caret(token: str, mod_dir: Path, root: Path, apex: Path | None, entry: str) -> str | None:
    """Resolve one ^-notation token (head or annotation) to a concrete path.
    Returns None when the token is not ^-notation. Same containment refusals
    everywhere — annotations get no laundering privileges."""
    if token == "^" or token in ("^/",):
        return root.as_posix() + "/" if token == "^/" else root.as_posix()
    if token in ("^/^", "^/^/") or token.startswith("^/^/"):
        rest = token[4:] if token.startswith("^/^/") else ""
        return _join_contained(apex, rest, entry) if apex is not None else None
    if token.startswith("^/"):
        return _join_contained(root, token[2:], entry)
    return None


def _resolve_note(note: str, mod_dir: Path, root: Path, apex: Path | None, entry: str) -> str:
    """Annotations ride along verbatim, except ^-notation tokens inside them
    resolve exactly like heads (same containment refusals) — no semantic
    tokens and no laundered escapes reach a blind subagent."""
    out = []
    for raw in note.split(" "):
        core = raw.strip("().,;:")
        if core and core[0] == "^":
            resolved = _resolve_caret(core, mod_dir, root, apex, entry)
            if resolved is not None:
                raw = raw.replace(core, resolved, 1)
        out.append(raw)
    return " ".join(out)


def _resolve_entry(entry: str, mod_dir: Path, root: Path, apex: Path | None) -> str:
    """One declared I/O entry → resolved text. Head token (split at first
    whitespace of any kind) resolves by prefix: `./` module-relative, `^/`
    dispatch-root-relative, `^/^/` apex-relative; trailing slash preserved
    as a directory marker; `..` and symlink escapes refused; backslash
    separators refused (not in the grammar). When the entry needs an apex
    and none is known, the WHOLE entry falls back to `as-declared:` —
    heads and annotations behave identically. Unprefixed entries are
    emitted unresolved, labeled as-declared."""
    if "\\" in entry:
        _die(f"contract entry {entry!r} contains a backslash separator — not in the grammar, refusing", 2)
    if apex is None and "^/^" in entry:
        return f"as-declared: {entry}"
    parts = re.split(r"\s+", entry.strip(), maxsplit=1)
    head, note = parts[0], (parts[1] if len(parts) > 1 else "")
    if head == "./":
        resolved = mod_dir.as_posix() + "/"
    elif head.startswith("./"):
        resolved = _join_contained(mod_dir, head[2:], entry)
    else:
        resolved = _resolve_caret(head, mod_dir, root, apex, entry)
        if resolved is None:
            return f"as-declared: {entry}"
    note = _resolve_note(note, mod_dir, root, apex, entry) if note else ""
    return resolved + (f" {note}" if note else "")


def contract_block(codex_dir: Path, name: str, root: Path, apex: Path | None = None) -> str:
    """I/O contract line from the module's declared reads:/writes:
    frontmatter. Module name is contained to .codex/explicit/; unparseable
    frontmatter and non-list/string declaration types are refused."""
    if not _MODULE_NAME_RE.fullmatch(name or ""):
        _die(f"invalid module name: {name!r} (letters/digits/._- only, no separators)", 2)
    start_md = codex_dir / "explicit" / name / "start.md"
    if not start_md.is_file():
        _die(f"no such explicit module: {name} ({start_md})", 2)
    fm = parse_frontmatter(_read(start_md))
    if not fm:
        _die(f"module {name}: frontmatter missing or unparseable — refusing to emit a contract", 2)
    mod_dir = start_md.parent

    def resolve(key):
        paths = fm.get(key)
        if paths is None:
            paths = []
        elif isinstance(paths, str):
            paths = [paths]
        elif not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            _die(f"module {name}: '{key}:' has an unsupported declaration type "
                 f"({type(paths).__name__}) — refusing to emit a contract", 2)
        entries = [_payload_safe(_resolve_entry(p, mod_dir, root, apex), f"contract entry {p!r}")
                   for p in paths if p.strip()]
        return ", ".join(entries) if entries else "(none declared)"

    safe_name = _payload_safe(name, "module name")
    return (f"Module contract ({safe_name}) — declared reads: {resolve('reads')}; "
            f"declared writes: {resolve('writes')}. "
            "Writes outside the declaration violate the module contract.\n")


def version_hash(template_text: str) -> str:
    h = hashlib.sha256()
    h.update(template_text.encode("utf-8"))
    h.update(repr(sorted((k, sorted(v.items())) for k, v in PROFILES.items())).encode())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()[:8]


def emit(profile_name: str, root: Path, module: str | None) -> str:
    profile = PROFILES[profile_name]
    template = _read(MODULE_DIR / profile["template"])
    codex_dir = MODULE_DIR.parents[2].parent  # …/.codex
    contract = contract_block(codex_dir, module, root, apex=_apex()) if module else ""
    payload = template.format(
        version=version_hash(template),
        root=_payload_safe(root.as_posix(), "root path"),
        state_dir=_payload_safe((root / ".state").as_posix(), "state dir"),
        contract=contract,
    )
    size = len(payload.encode("utf-8"))
    if size > profile["budget"]:
        _die(f"payload {size} B exceeds '{profile_name}' budget {profile['budget']} B "
             "— refusing to emit (budget = admission test).", 3)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="govgen", add_help=True)
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("--root", required=True)
    parser.add_argument("--module", default=None)
    args = parser.parse_args(argv)
    if args.module is not None and not args.module.strip():
        _die("--module requires a non-empty name", 2)

    root = resolve_root(args.root)
    warning = root_warning(root)
    if warning:
        print(warning, file=sys.stderr)
    sys.stdout.write(emit(args.profile, root, args.module))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # loud, typed failure — never a half-emitted payload
        print(f"govgen: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
