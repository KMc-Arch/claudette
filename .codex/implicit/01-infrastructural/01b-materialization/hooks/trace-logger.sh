#!/usr/bin/env bash
# H-09 + H-4.4: PostToolUse — append tool call to session trace (with output size)
# Reads tool input/output JSON from stdin.
#
# Right-sized 2026-08-09 (BL-32): the output byte-format is UNCHANGED
# ("[TS] TOOL: name path (Nb)"); only per-call process overhead was cut
# (~10 spawns -> ~2). Field extraction is a single-pass bash regex (was 4x
# grep + 2x tr), one date call feeds both the timestamp and the day-stamp
# (was 2x date), and mkdir is guarded. INPUT=$(cat) is retained ON PURPOSE:
# command substitution strips trailing newlines, so ${#INPUT} — the (Nb)
# size proxy — matches the prior value exactly. Do NOT swap in `read -d ''`
# (it keeps trailing newlines and would change the byte count).

INPUT=$(cat)

# Single-pass field extraction via bash builtin regex — no grep/tr subprocesses.
TOOL_NAME=""
FILE_PATH=""
re_tool='"tool_name"[[:space:]]*:[[:space:]]*"([^"]*)"'
re_path='"file_path"[[:space:]]*:[[:space:]]*"([^"]*)"'
[[ $INPUT =~ $re_tool ]] && TOOL_NAME="${BASH_REMATCH[1]}"
[[ $INPUT =~ $re_path ]] && FILE_PATH="${BASH_REMATCH[1]}"

# H-4.4: output-size proxy = full payload length (builtin ${#...}, no spawn).
INPUT_SIZE=${#INPUT}
if [ "$INPUT_SIZE" -gt 0 ]; then
    SIZE_TAG=" (${INPUT_SIZE}b)"
else
    SIZE_TAG=""
fi

# One date invocation; derive the day-stamp from it. Also removes the
# midnight race between a separately-dated timestamp and filename.
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S")
DAY=${TIMESTAMP%%T*}

TRACE_DIR="$CLAUDE_PROJECT_DIR/.state/traces"
[[ -d $TRACE_DIR ]] || mkdir -p "$TRACE_DIR"

# Session trace file — one per day
TRACE_FILE="$TRACE_DIR/$DAY.trace"

if [ -n "$FILE_PATH" ]; then
    echo "[$TIMESTAMP] TOOL: $TOOL_NAME $FILE_PATH$SIZE_TAG" >> "$TRACE_FILE"
else
    echo "[$TIMESTAMP] TOOL: $TOOL_NAME$SIZE_TAG" >> "$TRACE_FILE"
fi

exit 0
