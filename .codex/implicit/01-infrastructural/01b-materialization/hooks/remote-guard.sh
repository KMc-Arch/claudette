#!/usr/bin/env bash
# H-14: PreToolUse (Bash) — guard remote-targeting operations.
#
# Feature-branch pushes and PR operations are allowed. Pushes to main/master,
# force-pushes, and direct GitHub API/issue/release access are blocked.
# Defense-in-depth backup for permissions.deny — hooks fire regardless of
# permission settings and cannot be bypassed.
#
# Exit 0 = allow, exit 2 = block.

INPUT=$(cat)
CMD=$(echo "$INPUT" | grep -oP '"command"\s*:\s*"\K[^"]+' || true)
[ -z "$CMD" ] && exit 0

case "$CMD" in
    git\ push*)
        # Use Python for robust argument parsing — avoids bash edge cases
        # with flags, refspecs, and branch names containing special chars.
        echo "$CMD" | python3 -c '
import subprocess, sys

cmd = input().strip()
parts = cmd.split()

# 1. Block force-push (irrecoverable regardless of target)
for p in parts:
    if p in ("--force", "-f", "--force-with-lease", "--force-if-includes"):
        print("BLOCKED: force-push is irrecoverable.", file=sys.stderr)
        sys.exit(2)

# 2. Extract positional args (skip "git", "push", and flags)
positional = []
for p in parts[2:]:
    if p.startswith("-"):
        continue
    positional.append(p)

# 3. Check if any positional arg targets main/master
for arg in positional:
    # Handle refspec syntax: local:remote
    target = arg.split(":")[-1] if ":" in arg else arg
    if target in ("main", "master"):
        print("BLOCKED: direct push to main/master is not allowed.", file=sys.stderr)
        print("  Push a feature branch and merge via PR instead.", file=sys.stderr)
        sys.exit(2)

# 4. Bare push (no branch arg): check current branch
if len(positional) <= 1:
    try:
        current = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        current = ""
    if current in ("main", "master"):
        print("BLOCKED: bare push while on main — switch to a feature branch first.", file=sys.stderr)
        sys.exit(2)

sys.exit(0)
' || exit 2
        exit 0
        ;;

    git\ remote\ add*|git\ remote\ set-url*|git\ remote\ remove*|git\ remote\ rename*)
        echo "BLOCKED by remote-guard: '$CMD' modifies remote configuration." >&2
        exit 2
        ;;

    gh\ pr\ *)
        # PR operations (create, merge, list, view, review, edit, close) are allowed.
        exit 0
        ;;

    gh\ issue*|gh\ api*|gh\ release*)
        echo "BLOCKED by remote-guard: '$CMD' targets GitHub shared state." >&2
        exit 2
        ;;
esac

exit 0
