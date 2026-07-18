#!/usr/bin/env bash
# H-05: PreToolUse — block writes outside project root (^)
# Reads tool input JSON from stdin. Exit 2 = block, exit 0 = allow.

INPUT=$(cat)

# Extract file_path from tool input
FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')

if [ -z "$FILE_PATH" ]; then
    exit 0  # No file_path parameter — not a file write tool call
fi

# Resolve to absolute (handle both Unix / and Windows C:\ / C:/ paths)
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

# Check if path is within project root
case "$FILE_PATH" in
    "$PROJECT_ROOT"/*)
        exit 0  # Within project root — allowed
        ;;
    "$PROJECT_ROOT")
        exit 0  # Is project root — allowed
        ;;
    *)
        echo "BLOCKED: Write target is outside project root." >&2
        echo "  Target: $FILE_PATH" >&2
        echo "  Root:   $PROJECT_ROOT" >&2
        echo "Path containment: all writes must target paths within ^." >&2
        exit 2
        ;;
esac
