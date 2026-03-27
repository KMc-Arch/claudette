#!/usr/bin/env bash
# H-08: PostToolUse — notify when codex executables are edited
# Reads tool input/output JSON from stdin. Stdout injected into context.

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Check if file is in .codex/ and is executable
if echo "$FILE_PATH" | grep -q '\.codex/' && echo "$FILE_PATH" | grep -qE '\.(py|sh)$'; then
    echo "CODEX EXECUTABLE EDITED: $FILE_PATH"
    echo "If this module has a test/ subfolder, run the test suite now."
fi

exit 0
