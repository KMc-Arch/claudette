#!/usr/bin/env python3
"""SessionStart hook: re-inject the /read-only hold after context loss.

`/read-only` engages a session-wide CONFIRMED HOLD on mutations and records it
in a SESSION-SCOPED flag:

    <root>/.claude/skills/read-only/read-only-<session_id>.flag

This hook fires on every SessionStart (startup, resume, clear, compact, fork),
reads `session_id` from the hook payload, and — if a flag matches THIS
session's id — re-injects the hold into the fresh context via plain stdout
(the documented SessionStart injection channel). That is what carries the hold
across context compaction: the flag persists on disk; this hook re-hydrates it.

Session-scoped by design: a subordinated secondary session matches its own
flag; a PRIMARY session sharing the same tree has a different session_id and is
never falsely subordinated. This hook never writes or removes any flag — a
session owns its own flag (written on engage, removed on `/read-only done`).

A crashed hook is a total loss of the re-injection, so every failure path exits
0 and simply emits nothing (silence == read-write, the safe-by-omission case is
never the held one, so silence only ever *under*-restricts a session that the
model is separately instructed to hold).
"""

import json
import os
import sys
from pathlib import Path


def _root(payload):
    """Session root — same fallback chain as boot-inject.py: the project-dir
    env var, then the SessionStart payload's cwd, then getcwd. All resolve to
    the session's launch root, where its .claude/ lives."""
    pd = os.environ.get("CLAUDE_PROJECT_DIR")
    if pd:
        return Path(pd)
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if cwd:
        return Path(cwd)
    try:
        return Path(os.getcwd())
    except OSError:
        return Path(".")


def main():
    # Text-mode stdin decodes as cp1252 under a non-UTF-8 locale (the BL-83
    # lesson); read bytes and decode UTF-8 explicitly.
    try:
        raw = sys.stdin.buffer.read()
        payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except Exception:
        return  # no parseable payload -> no session_id -> cannot match
    if not isinstance(payload, dict):
        return

    sid = payload.get("session_id")
    if not sid or not isinstance(sid, str):
        return
    # session_id is used only as a filename segment; reject separators and
    # traversal so a malformed payload cannot escape the flag directory.
    if "/" in sid or "\\" in sid or sid in (".", ".."):
        return

    flag = _root(payload) / ".claude" / "skills" / "read-only" / f"read-only-{sid}.flag"
    try:
        if not flag.is_file():
            return
    except OSError:
        return

    # Plain stdout from a SessionStart hook is injected as context.
    sys.stdout.write(
        "=== READ-ONLY HOLD ACTIVE (this session) ===\n\n"
        "This session is under a `/read-only` CONFIRMED HOLD: it is secondary /\n"
        "subordinate against the filesystem. Do NOT perform ANY mutative operation\n"
        "(Write/Edit/NotebookEdit, mutating Bash, git commit/push/branch/reset,\n"
        "writes under .state/, outward sends, or dispatching a subagent to do any\n"
        "of these). A direct, specific user instruction to mutate MAY be honored\n"
        "once — after you state your intent and get a single confirmation. The\n"
        "hold is lifted ONLY by `/read-only done`. Report this state to the user.\n"
        f"Flag: {flag.as_posix()}\n"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never break the session
    sys.exit(0)
