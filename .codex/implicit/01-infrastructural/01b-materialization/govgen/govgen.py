#!/usr/bin/env python3
"""govgen.py — governance resolver: emits the exactly-right governance
payload for an actor class (prototype: `subagent` profile only).

The dispatcher runs this at dispatch time and embeds the emitted preamble in
the Agent prompt. Gravity and containment arrive RESOLVED (concrete paths),
not semantic (`^` notation) — a blind subagent needs no resolution rules to
comply. Deterministic: identical sources + arguments produce identical
output; the sentinel version hash covers the template, the profile table,
and this script, so any generator change mints a new version and stale
preambles are detectable.

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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").lstrip("﻿")


def parse_frontmatter(text: str) -> dict:
    """Flat `key: value` pairs plus block lists (`key:` followed by `- item`
    lines). Values keep their quotes stripped; `true`/`false` become bools."""
    if not text.startswith("---"):
        return {}
    m = re.search(r"(?m)^---[ \t]*$", text[3:])
    if not m:
        return {}
    fm: dict = {}
    list_key = None
    for line in text[3:3 + m.start()].splitlines():
        item = re.match(r"\s*-\s+(.*)$", line)
        if item and list_key:
            fm[list_key].append(item.group(1).strip().strip('"').strip("'"))
            continue
        if ":" not in line:
            list_key = None
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value == "":
            list_key = key
            fm[key] = []
        else:
            list_key = None
            fm[key] = {"true": True, "false": False}.get(value.lower(), value)
    return fm


def resolve_root(arg: str) -> Path:
    """Absolute path, or ^/-prefixed resolved against CLAUDE_PROJECT_DIR
    (cwd fallback). Must be an existing directory."""
    if arg.startswith("^/"):
        base = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        root = (Path(base) / arg[2:]).resolve()
    else:
        root = Path(arg).resolve()
    if not root.is_dir():
        print(f"govgen: root is not a directory: {root}", file=sys.stderr)
        raise SystemExit(2)
    return root


def root_warning(root: Path) -> str | None:
    claude_md = root / "CLAUDE.md"
    if claude_md.is_file():
        fm = parse_frontmatter(_read(claude_md))
        if fm.get("root") is True or fm.get("apex-root") is True:
            return None
    return (f"govgen: WARNING — {root.as_posix()} has no root: true CLAUDE.md; "
            "the fence still applies, but `^` binding is dispatcher-declared only.")


def contract_block(codex_dir: Path, name: str, root: Path) -> str:
    """I/O contract line from the module's declared reads:/writes: frontmatter.
    `./` resolves to the module dir, `^/` to the dispatch root."""
    start_md = codex_dir / "explicit" / name / "start.md"
    if not start_md.is_file():
        print(f"govgen: no such explicit module: {name} ({start_md})", file=sys.stderr)
        raise SystemExit(2)
    fm = parse_frontmatter(_read(start_md))

    def resolve(paths):
        out = []
        for p in paths if isinstance(paths, list) else []:
            if p.startswith("./"):
                out.append((start_md.parent / p[2:]).as_posix())
            elif p.startswith("^/"):
                out.append((root / p[2:]).as_posix())
            else:
                out.append(p)
        return ", ".join(out) if out else "(none declared)"

    return (f"Module contract ({name}) — declared reads: {resolve(fm.get('reads'))}; "
            f"declared writes: {resolve(fm.get('writes'))}. "
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
    contract = contract_block(codex_dir, module, root) if module else ""
    payload = template.format(
        version=version_hash(template),
        root=root.as_posix(),
        state_dir=(root / ".state").as_posix(),
        contract=contract,
    )
    size = len(payload.encode("utf-8"))
    if size > profile["budget"]:
        print(f"govgen: payload {size} B exceeds '{profile_name}' budget "
              f"{profile['budget']} B — refusing to emit (budget = admission test).",
              file=sys.stderr)
        raise SystemExit(3)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="govgen", add_help=True)
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("--root", required=True)
    parser.add_argument("--module", default=None)
    args = parser.parse_args(argv)

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
