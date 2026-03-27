#!/usr/bin/env bash
# H-06: PreToolUse — warn on potential state gravity violations
# Reads tool input JSON from stdin. Exit 2 = block, exit 0 = allow.
#
# State gravity rule: .state/ writes default to the nearest root: true context.
# This hook blocks writes to .state/ paths that are ABOVE the project root
# (i.e., a parent's .state/). Writes to .state/ paths WITHIN ^ (including
# child project .state/ paths) are allowed.

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Only check .state/ writes
if ! echo "$FILE_PATH" | grep -q '\.state[/\\]'; then
    exit 0
fi

# Resolve to absolute (handle both Unix / and Windows C:\ paths)
if [[ "$FILE_PATH" != /* ]] && [[ ! "$FILE_PATH" =~ ^[A-Za-z]:[\\/] ]]; then
    FILE_PATH="$CLAUDE_PROJECT_DIR/$FILE_PATH"
fi

# Normalize to POSIX paths for consistent comparison
if command -v cygpath &>/dev/null; then
    FILE_PATH=$(cygpath -u "$FILE_PATH" 2>/dev/null || echo "$FILE_PATH")
    CLAUDE_PROJECT_DIR=$(cygpath -u "$CLAUDE_PROJECT_DIR" 2>/dev/null || echo "$CLAUDE_PROJECT_DIR")
fi

# Normalize path (resolve .. etc)
FILE_PATH=$(realpath -m "$FILE_PATH" 2>/dev/null || echo "$FILE_PATH")
PROJECT_ROOT=$(realpath -m "$CLAUDE_PROJECT_DIR" 2>/dev/null || echo "$CLAUDE_PROJECT_DIR")

# Check if the write target is within the project root
case "$FILE_PATH" in
    "$PROJECT_ROOT"/*)
        # Within ^ — allowed (includes child .state/ paths)
        exit 0
        ;;
    *)
        # Outside ^ — this is a parent or sibling .state/, block it
        echo "BLOCKED: State gravity violation — writing to .state/ outside project root." >&2
        echo "  Target: $FILE_PATH" >&2
        echo "  Root:   $PROJECT_ROOT" >&2
        echo "State gravity: .state/ writes default to the nearest root: true context." >&2
        echo "Use explicit ^ or ^/^ path notation if you intend to write to a parent's .state/." >&2
        exit 2
        ;;
esac
