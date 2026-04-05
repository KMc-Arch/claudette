#!/usr/bin/env python3
"""SessionStart hook: inject governance content into Claude's context.

Resolves the project hierarchy (apex root, codex inheritance, state gravity)
and emits governance file contents directly to stdout. The platform injects
this output into Claude's context as a system-reminder.

Replaces boot-inject.sh. Same hook slot, hierarchy-aware.

Environment:
    CLAUDE_PROJECT_DIR  set by Claude Code to the project root
"""

import os
import sys
from pathlib import Path


# -- Frontmatter parsing --------------------------------------------------


def parse_frontmatter(path):
    """Extract simple key: value pairs from YAML frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value.lower() == "true":
            value = True
        elif value.lower() == "false":
            value = False
        fm[key] = value
    return fm


# -- Hierarchy resolution --------------------------------------------------


def find_apex(start_dir):
    """Walk up to find the apex root (apex-root: true in CLAUDE.md).
    Falls back to the highest root: true if no apex-root is found.
    """
    current = start_dir.resolve()
    highest_root = None
    while True:
        claude_md = current / "CLAUDE.md"
        if claude_md.exists():
            fm = parse_frontmatter(claude_md)
            if fm.get("apex-root") is True:
                return current
            if fm.get("root") is True:
                highest_root = current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return highest_root


def resolve_codex(project_dir, fm):
    """Resolve the effective codex directory for this project.

    Apex roots and projects with local .codex/: use local.
    Children with codex: ^/^/.codex: resolve to apex's .codex/.
    """
    codex_ref = fm.get("codex", "")

    if not codex_ref:
        local = project_dir / ".codex"
        return local if local.is_dir() else None

    if "^/^" in codex_ref:
        apex = find_apex(project_dir)
        if apex:
            relative = codex_ref.replace("^/^/", "", 1)
            resolved = apex / relative
            if resolved.is_dir():
                return resolved

    local = project_dir / ".codex"
    return local if local.is_dir() else None


def find_memory_file(project_dir, filename):
    """Find a memory file, checking local .state/memory/ first,
    then walking up through root: true ancestors.
    """
    local = project_dir / ".state" / "memory" / filename
    if local.is_file():
        return local, "local"

    current = project_dir.parent
    while current != current.parent:
        claude_md = current / "CLAUDE.md"
        if claude_md.exists():
            fm = parse_frontmatter(claude_md)
            if fm.get("root") is True or fm.get("apex-root") is True:
                candidate = current / ".state" / "memory" / filename
                if candidate.is_file():
                    return candidate, "inherited"
        current = current.parent

    return None, None


# -- Content emission ------------------------------------------------------


def emit_file(path):
    """Print file content with its full filepath as header. Returns True if emitted."""
    if not path or not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8").rstrip()
    except (OSError, UnicodeDecodeError):
        return False
    if not content:
        return False
    print(f"======== {path.as_posix()} ========")
    print(content)
    print()
    return True


def build_explicit_index(codex_dir):
    """Build sorted list of explicit command names."""
    explicit_dir = codex_dir / "explicit"
    if not explicit_dir.is_dir():
        return []
    return sorted(
        d.name for d in explicit_dir.iterdir()
        if d.is_dir() and not d.name.startswith(("_", "."))
    )


# -- Main ------------------------------------------------------------------


def main():
    # Force UTF-8 stdout on Windows (start.md contains Unicode)
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    project_dir = Path(
        os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    ).resolve()

    claude_md = project_dir / "CLAUDE.md"
    fm = parse_frontmatter(claude_md) if claude_md.exists() else {}

    codex_dir = resolve_codex(project_dir, fm)

    # -- Governance content --

    if codex_dir:
        emit_file(codex_dir / "start.md")

    emit_file(project_dir / ".state" / "start.md")

    user_path, _ = find_memory_file(project_dir, "user.md")
    if user_path:
        emit_file(user_path)

    emit_file(project_dir / ".state" / "memory" / "state-abstract.md")

    # -- Boot instructions --

    cmds = build_explicit_index(codex_dir) if codex_dir else []

    print("=== BOOT INSTRUCTIONS ===")
    print()
    print("The governance roots above are pre-loaded. To complete boot:")
    print("- Follow the codex loading rules: implicit tiers (priority-ordered,")
    print("  sequential), then lazy-load indexes for explicit/, reactive/, reflexive/")
    print("- The start.md convention: every folder has a start.md — read it BEFORE")
    print("  anything else in that folder")
    print()
    print("After implicit loading, run boot-attestation: verify prefs resolved,")
    print("shims registered, path containment active, state gravity active.")
    print("Write attestation log to .state/tests/boot/.")
    print()
    if cmds:
        print(f"Available explicit commands (invoke by name or /slash-command): {', '.join(cmds)}")
        print("When the user invokes any of these, read .codex/explicit/<name>/start.md")
        print("and follow its protocol exactly.")
        print()
    print("WARNING RELAY: If ANY other SessionStart hook produced a warning (look")
    print("for lines containing ⚠ or BLOCKED or WARNING), you MUST reproduce that")
    print("warning verbatim to the user in your FIRST response, BEFORE any other")
    print("content. The user CANNOT see SessionStart hook output — you are the only")
    print("relay. This is not optional.")


if __name__ == "__main__":
    main()
