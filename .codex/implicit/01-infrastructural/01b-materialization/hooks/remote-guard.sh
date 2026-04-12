#!/usr/bin/env bash
# H-14: PreToolUse (Bash) — block commands that touch remote git or GitHub.
# Defense-in-depth backup for permissions.deny. Hooks fire regardless of
# permission settings and cannot be bypassed.
#
# Exit 0 = allow, exit 2 = block.

# Only inspect Bash tool calls
TOOL=$(echo "$CLAUDE_TOOL_USE_INPUT" 2>/dev/null | grep -oP '"tool_name"\s*:\s*"\K[^"]+' || true)
if [ -z "$TOOL" ]; then
    # Fallback: read from stdin (Claude Code pipes JSON on stdin for PreToolUse)
    INPUT=$(cat)
    CMD=$(echo "$INPUT" | grep -oP '"command"\s*:\s*"\K[^"]+' || true)
else
    CMD=$(echo "$CLAUDE_TOOL_USE_INPUT" | grep -oP '"command"\s*:\s*"\K[^"]+' || true)
fi

[ -z "$CMD" ] && exit 0

# Block patterns — remote-targeting git and GitHub CLI operations
case "$CMD" in
    git\ push*|git\ remote\ add*|git\ remote\ set-url*|git\ remote\ remove*|git\ remote\ rename*)
        echo "BLOCKED by remote-guard: '$CMD' targets a remote repository." >&2
        exit 2
        ;;
    gh\ pr*|gh\ issue*|gh\ api*|gh\ release*)
        echo "BLOCKED by remote-guard: '$CMD' targets GitHub." >&2
        exit 2
        ;;
esac

exit 0
