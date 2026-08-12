#!/usr/bin/env bash
# H-05: PreToolUse — block writes outside project root (^)
# Reads tool input JSON from stdin. Exit 2 = block, exit 0 = allow.

INPUT=$(cat)

# Decode file_path with a REAL JSON parser — never grep. An embedded \" in the
# value truncates a grep match and drops a trailing ../.. traversal, letting a
# write escape ^ while the guard sees an in-bounds prefix (a containment
# fail-open). python3 is a hard platform dependency (.codex/start.md) already
# used by boot-inject.py; if the input cannot be parsed (or no decoder is
# present), FAIL CLOSED.
FILE_PATH=$(printf '%s' "$INPUT" | python3 -c 'import json,sys
d=json.load(sys.stdin)
ti=d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
v=ti.get("file_path")
if not isinstance(v, str): v=d.get("file_path")
sys.stdout.write(v if isinstance(v, str) else "")')
if [ $? -ne 0 ]; then
    echo "BLOCKED: could not parse tool input for the containment check (fail closed)." >&2
    exit 2
fi

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

# Resolve ^ the way frontmatter.md does: nearest ancestor (inclusive) of the
# launch dir whose LEADING CLAUDE.md frontmatter declares root: true / apex-root:
# true. MUST stay in lockstep with 01a-resolution/frontmatter.md and the sibling
# guard (shared scenarios: tests/test_guards_walkup.sh).
# Security posture: this is a containment boundary, so it fails CLOSED. A CLAUDE.md
# that exists but cannot be read/parsed fences AT that dir rather than being walked
# past to a looser ceiling. Detection tolerates a trailing "# comment", quoted
# "true", CRLF, and mawk (`[ \t]`, not `[[:space:]]`); only the LEADING `---`
# block counts as frontmatter (a body `---` rule is not a fence). Fall back to the
# raw launch dir only when no root is found anywhere above.
resolve_root() {
    local dir cm
    dir=$(realpath -m "$1" 2>/dev/null) || dir=""
    [ -n "$dir" ] || return 1
    while :; do
        cm="$dir/CLAUDE.md"
        if [ -e "$cm" ]; then
            if [ -f "$cm" ] && [ -r "$cm" ]; then
                if awk '
                    FNR==1 { if ($0 !~ /^---[ \t]*\r?$/) exit 1; next }
                    /^---[ \t]*\r?$/ { exit 1 }
                    /^(apex-)?root:[ \t]*"?true"?([ \t]+#|[ \t]*\r?$)/ { found=1; exit }
                    END { exit (found ? 0 : 1) }' "$cm"; then
                    printf '%s\n' "$dir"; return 0
                fi
            else
                printf '%s\n' "$dir"; return 0   # exists but unreadable/non-regular -> fail closed
            fi
        fi
        [ "$dir" = "/" ] && return 1
        dir=$(dirname "$dir")
    done
}

PROJECT_ROOT=$(resolve_root "$CLAUDE_PROJECT_DIR") \
    || PROJECT_ROOT=$(realpath -m "$CLAUDE_PROJECT_DIR" 2>/dev/null || echo "$CLAUDE_PROJECT_DIR")

# Fail CLOSED if no root could be established (e.g. empty/unset CLAUDE_PROJECT_DIR):
# an empty PROJECT_ROOT would make the "$PROJECT_ROOT"/* glob match every path.
if [ -z "$PROJECT_ROOT" ]; then
    echo "BLOCKED: cannot resolve project root (CLAUDE_PROJECT_DIR empty/unset)." >&2
    exit 2
fi

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
