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
                    /^(apex-)?root:[ \t]*"?true"?[ \t]*(#|\r|$)/ { found=1; exit }
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
