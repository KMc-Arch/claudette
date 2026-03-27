#!/usr/bin/env bash
# H-09 + H-4.4: PostToolUse — append tool call to session trace (with output size)
# Reads tool input/output JSON from stdin.

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | grep -oE '"tool_name"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')
FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S")

# H-4.4: Estimate output size from full JSON payload
# tool_output may be an object/array, not a simple string — use total payload size as proxy
INPUT_SIZE=${#INPUT}
if [ "$INPUT_SIZE" -gt 0 ]; then
    SIZE_TAG=" (${INPUT_SIZE}b)"
else
    SIZE_TAG=""
fi

TRACE_DIR="$CLAUDE_PROJECT_DIR/.state/traces"
mkdir -p "$TRACE_DIR"

# Session trace file — one per day
TRACE_FILE="$TRACE_DIR/$(date -u +%Y-%m-%d).trace"

if [ -n "$FILE_PATH" ]; then
    echo "[$TIMESTAMP] TOOL: $TOOL_NAME $FILE_PATH$SIZE_TAG" >> "$TRACE_FILE"
else
    echo "[$TIMESTAMP] TOOL: $TOOL_NAME$SIZE_TAG" >> "$TRACE_FILE"
fi

exit 0
