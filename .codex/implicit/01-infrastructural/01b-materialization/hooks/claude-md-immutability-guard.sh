#!/usr/bin/env bash
# H-3.9: PreToolUse (Write|Edit) — enforce CLAUDE.md immutability
# Blocks writes to the root CLAUDE.md (design constraint #2).

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Normalize backslashes to forward slashes (bash parameter expansion, not sed)
FILE_PATH="${FILE_PATH//\\//}"

# Resolve to absolute if relative
if [[ "$FILE_PATH" != /* ]] && [[ ! "$FILE_PATH" =~ ^[A-Za-z]:/ ]]; then
    FILE_PATH="$CLAUDE_PROJECT_DIR/$FILE_PATH"
fi

# Canonicalize both paths to POSIX format for comparison
if command -v cygpath &>/dev/null; then
    FILE_PATH=$(cygpath -u "$FILE_PATH" 2>/dev/null || echo "$FILE_PATH")
    ROOT_CLAUDE=$(cygpath -u "$CLAUDE_PROJECT_DIR/CLAUDE.md" 2>/dev/null || echo "$CLAUDE_PROJECT_DIR/CLAUDE.md")
else
    ROOT_CLAUDE="$CLAUDE_PROJECT_DIR/CLAUDE.md"
fi

if [ "$FILE_PATH" = "$ROOT_CLAUDE" ]; then
    echo "BLOCKED: CLAUDE.md is immutable (design constraint #2)." >&2
    echo "  CLAUDE.md is a bootstrap pointer — it never grows." >&2
    echo "  All evolution happens in start.md files downstream." >&2
    exit 2
fi

exit 0
