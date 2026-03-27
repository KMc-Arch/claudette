#!/usr/bin/env bash
# H-04/H-07: PreToolUse — block access to _-prefixed paths
# Reads tool input JSON from stdin. Exit 2 = block, exit 0 = allow.

INPUT=$(cat)

# Extract paths from common tool parameters
PATHS=$(echo "$INPUT" | grep -oE '"(file_path|path|pattern|command)"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')

for P in $PATHS; do
    # Check each path segment for _ prefix
    if echo "$P" | grep -qE '(^|[/\\])_[^/\\]'; then
        echo "BLOCKED: _-prefixed path detected: $P" >&2
        echo "The _ prefix means invisible. These items do not exist to Claude." >&2
        exit 2
    fi
done

exit 0
