#!/usr/bin/env python3
"""SessionStart hook: inject governance content into Claude's context.

Resolves the project hierarchy (apex root, codex inheritance, state gravity)
and emits governance file contents directly to stdout. The platform injects
this output into Claude's context as a system-reminder.

Replaces boot-inject.sh. Same hook slot, hierarchy-aware.

Environment:
    CLAUDE_PROJECT_DIR  set by Claude Code to the project root
"""

import io
import os
import re
import sys
from pathlib import Path

# Emit only content above this marker in any governance file (whole-file
# fallback when absent). Line-anchored: prose merely MENTIONING the token
# mid-line does not trim. Keeps the eager payload small; reference sections
# load lazily via Read.
BOOT_CUT_RE = re.compile(r"(?m)^<!-- boot:cut")

# Warnings that must reach the model (stderr is invisible to it) — collected
# during resolution and emitted into the stdout payload and the stub.
WARNINGS = []


def _ceiling_bytes():
    """Inline-safety ceiling for the whole payload, in bytes.

    The harness spills oversized hook output to a file with only a ~2 KB
    preview — a SILENT governance failure. Lowest observed spill: 29,898 B
    (2026-08-01); inline passes are only observed well below that, so this
    default is conservative against observed failures, NOT a measured
    threshold (upper-bound rule). Override via BOOT_INJECT_CEILING;
    malformed or non-positive values fall back to the default rather than
    crash the hook — a crashed hook is a total governance loss.
    """
    try:
        value = int(os.environ.get("BOOT_INJECT_CEILING", ""))
        if value > 0:
            return value
    except ValueError:
        pass
    return 15000


CEILING_BYTES = _ceiling_bytes()


# -- Frontmatter parsing --------------------------------------------------


def parse_frontmatter(path):
    """Extract simple key: value pairs from YAML frontmatter.

    Handles only flat single-line 'key: value' pairs. List item lines and
    nested YAML are skipped (a list key itself is stored with an empty
    value). Sufficient for the keys this module queries (root, apex-root,
    codex). BOM-tolerant; the closing '---' must be its own line, so values
    containing '---' cannot truncate the block.
    """
    try:
        text = path.read_text(encoding="utf-8").lstrip("﻿")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---"):
        return {}
    m = re.search(r"(?m)^---[ \t]*$", text[3:])
    if not m:
        return {}
    end = 3 + m.start()
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


def find_nearest_root(start_dir):
    """Walk up from start_dir (exclusive) to find the nearest root: true ancestor."""
    current = start_dir.resolve().parent
    while current != current.parent:
        claude_md = current / "CLAUDE.md"
        if claude_md.exists():
            fm = parse_frontmatter(claude_md)
            if fm.get("root") is True or fm.get("apex-root") is True:
                return current
        current = current.parent
    return None


def resolve_codex(project_dir, fm, apex=None):
    """Resolve the effective codex directory for this project.

    Apex roots and projects with local .codex/: use local.
    Children with codex: ^/^/.codex: resolve to apex's .codex/.
    Children with codex: ^/.codex: resolve to nearest root ancestor's .codex/.
    """
    codex_ref = fm.get("codex", "")

    if not codex_ref:
        local = project_dir / ".codex"
        return local if local.is_dir() else None

    if codex_ref.startswith("^/^"):
        if not apex:
            apex = find_apex(project_dir)
        if apex:
            relative = codex_ref.replace("^/^/", "", 1)
            resolved = (apex / relative).resolve()
            if resolved.is_dir() and resolved.is_relative_to(apex.resolve()):
                return resolved
    elif codex_ref.startswith("^/"):
        nearest = find_nearest_root(project_dir)
        if nearest:
            relative = codex_ref[2:]  # strip "^/"
            resolved = (nearest / relative).resolve()
            if resolved.is_dir() and resolved.is_relative_to(nearest.resolve()):
                return resolved

    if codex_ref:
        # stderr is invisible to the model — record for payload emission too
        msg = f"codex ref '{codex_ref}' could not be resolved; falling back to local .codex"
        WARNINGS.append(msg)
        print(f"WARNING: {msg}", file=sys.stderr)

    local = project_dir / ".codex"
    return local if local.is_dir() else None


def find_memory_file(project_dir, filename, apex=None):
    """Find a memory file, checking local .state/memory/ first,
    then walking up through root: true ancestors. Stops at apex boundary.
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        return None, None

    local = project_dir / ".state" / "memory" / filename
    if local.is_file():
        return local, "local"

    apex_resolved = apex.resolve() if apex else None

    # If project is the apex itself, local check above is sufficient — no ancestor walk
    if apex_resolved and project_dir.resolve() == apex_resolved:
        return None, None

    current = project_dir.resolve().parent
    while current != current.parent:
        # Stop at apex ceiling — check apex's own memory, then break
        if apex_resolved and current == apex_resolved:
            candidate = current / ".state" / "memory" / filename
            if candidate.is_file():
                return candidate, "inherited"
            break
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


def emit_file(buf, path, required=False):
    """Write file content (banner + body) to buf. Honors a line-anchored
    boot:cut marker: only content above it is emitted, with a pointer to the
    full file. Returns True if emitted.

    A file that EXISTS but cannot be loaded (unreadable, non-UTF8, empty) is
    a governance gap the model must hear about — a WARNING line goes into the
    payload instead of a silent skip. A missing file warns only if required.
    """
    if not path:
        return False
    # Warnings go through WARNINGS (not straight into buf) so they survive
    # the inline/stub fork — the stub must hear about degraded files too.
    try:
        is_file = path.is_file()
    except OSError as exc:  # e.g. EACCES on a parent dir — pathlib does not swallow it
        WARNINGS.append(f"governance file {path.as_posix()} could not be probed ({type(exc).__name__}) — READ IT MANUALLY NOW.")
        return False
    if not is_file:
        if required:
            kind = "exists but is not a regular file" if path.exists() else "is missing"
            WARNINGS.append(f"expected governance file {path.as_posix()} {kind} — governance may be incomplete.")
        return False
    try:
        content = path.read_text(encoding="utf-8").lstrip("﻿").rstrip()
    except (OSError, UnicodeDecodeError) as exc:
        WARNINGS.append(f"governance file {path.as_posix()} exists but could not be loaded ({type(exc).__name__}) — READ IT MANUALLY NOW.")
        return False
    if not content:
        WARNINGS.append(f"governance file {path.as_posix()} exists but is EMPTY — governance may be incomplete.")
        return False
    m = BOOT_CUT_RE.search(content)
    if m:
        content = content[:m.start()].rstrip()
        if not content:
            WARNINGS.append(f"governance file {path.as_posix()} has no eager content above its boot:cut marker — read the full file.")
            return False
        content += (
            f"\n\n(trimmed at boot:cut — reference sections load lazily;"
            f" full file: {path.as_posix()})"
        )
    print(f"======== {path.as_posix()} ========", file=buf)
    print(content, file=buf)
    print(file=buf)
    return True


def build_explicit_index(codex_dir):
    """Build sorted list of explicit command names. An unreadable directory
    degrades to an empty index rather than killing the whole payload."""
    explicit_dir = codex_dir / "explicit"
    try:
        if not explicit_dir.is_dir():
            return []
        return sorted(
            d.name for d in explicit_dir.iterdir()
            if d.is_dir() and not d.name.startswith(("_", "."))
        )
    except OSError:
        WARNINGS.append(f"explicit command index unavailable ({explicit_dir.as_posix()} unreadable)")
        return []


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

    apex = find_apex(project_dir)
    codex_dir = resolve_codex(project_dir, fm, apex=apex)

    # -- Governance content (buffered: payload is size-checked before emission) --

    buf = io.StringIO()
    sources = []  # governance files that made it into the payload

    if codex_dir:
        src = codex_dir / "start.md"
        if emit_file(buf, src, required=True):
            sources.append(src)
    else:
        WARNINGS.append("no codex directory resolved — codex governance NOT loaded")

    src = project_dir / ".state" / "start.md"
    if emit_file(buf, src, required=True):
        sources.append(src)

    user_path, _ = find_memory_file(project_dir, "user.md", apex=apex)
    if user_path and emit_file(buf, user_path):
        sources.append(user_path)

    # Build the command index BEFORE flushing warnings — it can add one.
    cmds = build_explicit_index(codex_dir) if codex_dir else []

    # All warnings must ride the payload — stderr never reaches the model.
    for w in WARNINGS:
        print(f"⚠ WARNING: {w}", file=buf)
    if WARNINGS:
        print(file=buf)

    # NOTE: state-abstract.md is deliberately NOT emitted (decided 2026-08-01).
    # Instance state is observational, high-churn, and unbounded — it belongs
    # in the uncapped lazy channel (Read), not the capped eager one. The boot
    # instructions below carry the read mandate instead.

    # -- Boot instructions --

    print("=== BOOT INSTRUCTIONS ===", file=buf)
    print(file=buf)
    print("The governance roots above are pre-loaded. To complete boot:", file=buf)
    print("- Follow the codex loading rules: implicit tiers (priority-ordered,", file=buf)
    print("  sequential), then lazy-load indexes for explicit/, reactive/, reflexive/", file=buf)
    print("- The start.md convention: every folder has a start.md — read it BEFORE", file=buf)
    print("  anything else in that folder", file=buf)
    print("- Instance state does NOT load eagerly: before substantive work, read", file=buf)
    print(f"  {(project_dir / '.state' / 'memory' / 'state-abstract.md').as_posix()}", file=buf)
    print(file=buf)
    if cmds:
        print(f"Available explicit commands (invoke by name or /slash-command): {', '.join(cmds)}", file=buf)
        print("When the user invokes any of these, read .codex/explicit/<name>/start.md", file=buf)
        print("and follow its protocol exactly.", file=buf)
        print(file=buf)
    print("WARNING RELAY: If ANY other SessionStart hook produced a warning (look", file=buf)
    print("for lines containing ⚠ or BLOCKED or WARNING), you MUST reproduce that", file=buf)
    print("warning verbatim to the user in your FIRST response, BEFORE any other", file=buf)
    print("content. The user CANNOT see SessionStart hook output — you are the only", file=buf)
    print("relay. This is not optional.", file=buf)

    # -- Size gate: emit payload inline, or degrade LOUDLY --

    payload = buf.getvalue()
    size = len(payload.encode("utf-8"))
    if size <= CEILING_BYTES:
        sys.stdout.write(payload)
        return

    # Over ceiling: the harness would spill the payload to a file with a 2 KB
    # preview and no warning. Emit a short stub instead — recovery-critical
    # lines first, the one unbounded line (command index) last and dropped
    # if the stub itself would breach the ceiling.
    stub = [
        f"=== GOVERNANCE BUNDLE OVER CEILING ({size} B > {CEILING_BYTES} B) — NOT INLINED ===",
        "",
        "Your governance rules did NOT load. Oversized hook output is silently",
        "spilled by the harness; this stub replaces it. RECOVER NOW —",
        "READ THESE FILES, in order, BEFORE any other action:",
    ]
    stub += [f"  {i}. {src.as_posix()}" for i, src in enumerate(sources, 1)]
    stub += [
        "",
        "Then complete boot per their instructions. Before substantive work, also",
        f"read {(project_dir / '.state' / 'memory' / 'state-abstract.md').as_posix()}",
        "WARNING RELAY: reproduce any other SessionStart hook warning (⚠ / BLOCKED /",
        "WARNING) verbatim to the user in your FIRST response. This is not optional.",
    ]
    stub += [f"⚠ WARNING: {w}" for w in WARNINGS]
    if cmds:
        cmd_line = f"Explicit commands: {', '.join(cmds)}"
        current = len("\n".join(stub).encode("utf-8"))
        if current + len(cmd_line.encode("utf-8")) + 1 <= min(CEILING_BYTES, 4000):
            stub.append(cmd_line)
    print("\n".join(stub))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a crashed hook is a total governance loss — degrade loudly instead
        pd = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        print("=== BOOT-INJECT CRASHED — GOVERNANCE NOT LOADED ===")
        print(f"⚠ WARNING: boot-inject.py raised {type(exc).__name__}: {exc}")
        print("READ THESE FILES NOW, before any other action:")
        print(f"  1. the codex start.md for this project — local .codex/start.md if present,")
        print(f"     else the codex named by the 'codex:' ref in {pd}/CLAUDE.md")
        print(f"  2. {pd}/.state/start.md")
        print("WARNING RELAY: reproduce any other SessionStart hook warning (⚠ / BLOCKED /")
        print("WARNING) verbatim to the user in your FIRST response. This is not optional.")
        sys.exit(0)
