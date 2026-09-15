#!/usr/bin/env bash
# H-3.9: PreToolUse (Write|Edit|MultiEdit) — enforce CLAUDE.md immutability.
#
# Denies EVERY Write/Edit tool call whose target is a CLAUDE.md — ANY CLAUDE.md
# (apex or child), body AND frontmatter — per the "updating any CLAUDE.md"
# ABSOLUTE HOLD. The two sanctioned routes (the approved mutator and
# /new-project) edit by DIRECT file IO, never via the Write/Edit tool, so this
# hook never sees them; the precision (allowlist/laundering) lives in the
# mutator. This hook is the blunt, fail-closed backstop: identify a CLAUDE.md
# target and refuse.
#
# Redesign note (feature/claude-md-guard-redesign): the previous version keyed
# off $CLAUDE_PROJECT_DIR + a case-sensitive apex compare, and permitted
# frontmatter Edits. That (a) failed OPEN when CLAUDE_PROJECT_DIR was empty,
# (b) missed case-variant spellings (claude.md) on this case-insensitive mount,
# (c) left child CLAUDE.md unguarded, and (d) let body text ride in through an
# Edit's new_string. This version matches on the resolved BASENAME only —
# env-independent, case-insensitive, symlink-resolved — and never carves out a
# frontmatter exception. Exit 2 = block, exit 0 = allow.

INPUT=$(cat)
export CLAUDE_HOOK_INPUT="$INPUT"

# Resolve Python interpreter: python first (Windows convention + Linux alias),
# python3 as fallback (Unix PEP 394 canonical). See backlog BL-PY-INTERP.
PY=$(command -v python || command -v python3)
if [ -z "$PY" ]; then
    # Fail CLOSED: this guard protects a CLAUDE.md under an ABSOLUTE HOLD, whose
    # default is refusal. Without Python it cannot tell whether the target is a
    # CLAUDE.md, so it refuses (exit 2 blocks; a generic non-zero would only warn
    # and let it through). Python 3.10+ is a hard platform requirement — if it is
    # absent, cboot/the mutator/new-project are dead too.
    echo "BLOCKED: claude-md-immutability-guard: no python interpreter found — failing closed." >&2
    echo "  Cannot verify this Write/Edit without Python, so it is refused." >&2
    echo "  Install Python 3.10+ (a platform requirement) and retry. See backlog BL-PY-INTERP." >&2
    exit 2
fi

"$PY" - <<'PY'
import json
import os
import sys

raw = os.environ.get("CLAUDE_HOOK_INPUT", "")


def is_claude_md(name):
    return os.path.basename(name).strip().lower() == "claude.md"


def block():
    sys.stderr.write(
        "BLOCKED: CLAUDE.md is immutable to Claude (ABSOLUTE HOLD: updating any CLAUDE.md).\n"
        "  Every route and every part — body and frontmatter — is human-only, save\n"
        "  through /new-project (creation) or the approved claude-md-mutator\n"
        "  (allowlisted frontmatter keys), both of which edit by direct file IO and\n"
        "  are invoked from the shell, not the Write/Edit tool.\n"
        "  Body content evolves through start.md files downstream.\n"
    )
    sys.exit(2)


try:
    data = json.loads(raw)
except Exception:
    # Cannot parse the tool call. Fail closed ONLY for the protected target: if
    # the payload mentions a claude.md at all, refuse; otherwise this is plainly
    # not a CLAUDE.md operation, so allow (blocking every unparseable Write/Edit
    # would break the session on a transient glitch, and the payload is
    # host-generated JSON that essentially never fails to parse).
    if "claude.md" in raw.lower():
        block()
    sys.exit(0)

tool_input = data.get("tool_input", {}) or {}
file_path = tool_input.get("file_path", "") or ""
if not file_path:
    sys.exit(0)  # not a file-targeting call

# Normalize the given spelling for a robust basename (handles a trailing slash,
# "." / ".." segments), and independently resolve symlinks — refuse if EITHER
# the given name or the fully-resolved target is a CLAUDE.md, so a symlink named
# claude.md and a symlink that resolves to a CLAUDE.md are both caught.
given = file_path.replace("\\", "/")
candidates = [os.path.normpath(given)]
try:
    candidates.append(os.path.realpath(given))
except OSError:
    pass
if any(is_claude_md(c) for c in candidates):
    block()

sys.exit(0)
PY
