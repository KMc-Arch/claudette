#!/usr/bin/env bash
# H-1.12: PreToolUse (Write|Edit) — enforce audit record immutability
# Blocks writes to existing audit run folders, except decisions.md (post-hoc resolution).

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Normalize backslashes to forward slashes (bash parameter expansion, not sed)
FILE_PATH="${FILE_PATH//\\//}"

# Resolve to absolute if relative
if [[ "$FILE_PATH" != /* ]] && [[ ! "$FILE_PATH" =~ ^[A-Za-z]:[\\/] ]]; then
    FILE_PATH="$CLAUDE_PROJECT_DIR/$FILE_PATH"
fi

# Canonicalize to POSIX if available
if command -v cygpath &>/dev/null; then
    FILE_PATH=$(cygpath -u "$FILE_PATH" 2>/dev/null || echo "$FILE_PATH")
fi

# Check if path is inside an audit run folder (.state/tests/audits/YYYYMMDD-HHMM/)
if echo "$FILE_PATH" | grep -qE '\.state/tests/audits/[0-9]{8}-[0-9]{4}/'; then
    # Allow decisions.md (post-hoc resolution companion)
    BASENAME=$(basename "$FILE_PATH")
    if [ "$BASENAME" = "decisions.md" ]; then
        exit 0
    fi

    # Extract audit folder path
    AUDIT_DIR=$(echo "$FILE_PATH" | grep -oE '.*\.state/tests/audits/[0-9]{8}-[0-9]{4}')

    if [ -d "$AUDIT_DIR" ] && [ "$(ls -A "$AUDIT_DIR" 2>/dev/null)" ]; then
        echo "BLOCKED: Audit records are immutable." >&2
        echo "  Target: $FILE_PATH" >&2
        echo "  Audit outputs are never retroactively edited." >&2
        echo "  Post-hoc resolutions go in decisions.md within the audit folder." >&2
        exit 2
    fi
fi

exit 0
