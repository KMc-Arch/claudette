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

# Resolve Python interpreter: python3 FIRST (PEP 394 canonical, and it avoids
# preferring a broken Windows `python` stub that WSL PATH interop can surface —
# such a stub would run and exit non-zero, i.e. fail OPEN); `python` as fallback.
# See backlog BL-PY-INTERP.
PY=$(command -v python3 || command -v python)
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

# Hand the tool-call JSON to Python over STDIN — never argv or an environment
# variable. A large Write's `content` can exceed the execve argument/env size
# limit (MAX_ARG_STRLEN, ~128 KiB); passing it via env failed the interpreter
# launch with E2BIG and a NON-blocking exit code — i.e. fail OPEN on exactly the
# large-payload case. Only the small constant program below travels through argv;
# the unbounded payload rides stdin.
GUARD_PY=$(cat <<'PY'
import json
import os
import sys

# Read raw bytes and decode with surrogateescape so a non-UTF-8 or truncated
# payload can NEVER raise here (which, before the try, would exit 1 = a
# non-blocking ALLOW). host JSON is always valid UTF-8; this only hardens the edge.
raw = sys.stdin.buffer.read().decode("utf-8", "surrogateescape")


def is_claude_md(name):
    # Trailing dots/spaces are stripped by Win32/SMB path normalization, so
    # "CLAUDE.md." and "CLAUDE.md " open the same file there — fold them too.
    return os.path.basename(name).strip().rstrip(". ").lower() == "claude.md"


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
    tool_input = data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)  # not a file-targeting call
    # A real Write/Edit file_path is a clean string; anything else (a number, a
    # list, an embedded NUL) is malformed — treat it as an error and fall to the
    # fail-closed handler below rather than crashing to exit 1 (which PreToolUse
    # treats as non-blocking = ALLOW).
    if not isinstance(file_path, str) or "\x00" in file_path:
        raise ValueError("file_path is not a clean string")
    # Match on the given spelling (normalized: trailing slash, "."/".." segments)
    # AND the symlink-resolved target — so a symlink named claude.md and a symlink
    # that resolves to a CLAUDE.md are both caught.
    given = file_path.replace("\\", "/")
    candidates = [os.path.normpath(given), os.path.realpath(given)]
    if any(is_claude_md(c) for c in candidates):
        block()
    sys.exit(0)
except SystemExit:
    raise  # block() / the allow-path sys.exit(0) — let them through unchanged
except Exception:
    # Unparseable payload OR any unexpected post-parse shape/crash. Fail CLOSED
    # for a plausibly-CLAUDE.md target (a real target's path contains "claude.md"),
    # else allow — a transient glitch on an unrelated edit must not break the
    # session, and host-generated JSON essentially never fails to parse. (This is
    # the inode/hardlink-blind spot's only backstop too: a hardlink named
    # otherwise is not caught here — that residual is covered out-of-band.)
    if "claude.md" in raw.lower():
        block()
    sys.exit(0)
PY
)
printf '%s' "$INPUT" | "$PY" -c "$GUARD_PY"
rc=$?
# The program above returns exactly 0 (allow) or 2 (block). Anything else means
# the interpreter did not run it to a verdict — a broken/stub interpreter, a
# launch failure, or a fatal signal. That is not a clean allow, so fail CLOSED.
if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then
    echo "BLOCKED: claude-md-immutability-guard: interpreter returned rc=$rc (no clean verdict) — failing closed." >&2
    exit 2
fi
exit "$rc"
