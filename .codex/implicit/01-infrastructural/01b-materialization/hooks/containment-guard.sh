#!/usr/bin/env bash
# H-05: PreToolUse — block writes outside project root (^)
# Reads tool input JSON from stdin. Exit 2 = block, exit 0 = allow.

INPUT=$(cat)

# Extract file_path from tool input
FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')

if [ -z "$FILE_PATH" ]; then
    exit 0  # No file_path parameter — not a file write tool call
fi

# Resolve to absolute path
if [[ "$FILE_PATH" != /* ]]; then
    FILE_PATH="$CLAUDE_PROJECT_DIR/$FILE_PATH"
fi

# Check if path is within project root
case "$FILE_PATH" in
    "$CLAUDE_PROJECT_DIR"/*)
        exit 0  # Within project root — allowed
        ;;
    "$CLAUDE_PROJECT_DIR")
        exit 0  # Is project root — allowed
        ;;
    *)
        echo "BLOCKED: Write target is outside project root." >&2
        echo "  Target: $FILE_PATH" >&2
        echo "  Root:   $CLAUDE_PROJECT_DIR" >&2
        echo "Path containment: all writes must target paths within ^." >&2
        exit 2
        ;;
esac
