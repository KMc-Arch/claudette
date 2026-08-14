#!/usr/bin/env bash
# Proves the JSON-parse extraction in gravity-guard.sh + containment-guard.sh:
#   - escaped-quote traversal (a \" that truncated the old grep) is now BLOCKED
#   - notebook_path (NotebookEdit) is checked exactly like file_path
#   - malformed JSON / no interpreter FAIL CLOSED
#   - normal in-^ allow / out-of-^ block / no-path allow are unchanged
# Exit 0 = all pass.
set -u

HOOKS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GRAV="$HOOKS_DIR/gravity-guard.sh"
CONT="$HOOKS_DIR/containment-guard.sh"

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
ROOT="$T/root"
mkdir -p "$ROOT/sub" "$ROOT/.state" "$T/sib/.state"

FAILED=0
check() {  # desc expect guard json
    printf '%s' "$4" | CLAUDE_PROJECT_DIR="$ROOT" bash "$3" >/dev/null 2>&1
    local rc=$?
    if [ "$rc" -eq "$2" ]; then printf 'PASS  %s  (rc=%s)\n' "$1" "$rc"
    else printf 'FAIL  %s  (expected %s, got %s)\n' "$1" "$2" "$rc"; FAILED=1; fi
}

# --- containment-guard: all writes ---
echo "# containment-guard"
check "in-^ file_path                         -> allow" 0 "$CONT" '{"tool_input":{"file_path":"'"$ROOT"'/sub/x.md"}}'
check "escaped-quote traversal (was fail-open) -> block" 2 "$CONT" '{"tool_input":{"file_path":"'"$ROOT"'/q\"/../../../../../../etc/evil"}}'
check "notebook_path OUTSIDE ^ (was bypass)    -> block" 2 "$CONT" '{"tool_input":{"notebook_path":"/etc/evil.ipynb"}}'
check "notebook_path inside ^                  -> allow" 0 "$CONT" '{"tool_input":{"notebook_path":"'"$ROOT"'/nb.ipynb"}}'
check "plain out-of-^ file_path                -> block" 2 "$CONT" '{"tool_input":{"file_path":"/etc/passwd"}}'
check "malformed JSON (fail closed)            -> block" 2 "$CONT" '{"tool_input":{"file_path":'
check "valid JSON, no path key                 -> allow" 0 "$CONT" '{"tool_input":{"command":"ls"}}'

# --- gravity-guard: only .state/ writes ---
echo "# gravity-guard"
check "in-^ .state file_path                   -> allow" 0 "$GRAV" '{"tool_input":{"file_path":"'"$ROOT"'/.state/x"}}'
check "escaped-quote via .state (was fail-open)-> block" 2 "$GRAV" '{"tool_input":{"file_path":"'"$ROOT"'/.state/q\"/../../../../../../etc/evil"}}'
check "notebook_path to sibling .state OUTSIDE ^-> block" 2 "$GRAV" '{"tool_input":{"notebook_path":"'"$T"'/sib/.state/evil.ipynb"}}'
check "non-.state notebook_path (gravity skips) -> allow" 0 "$GRAV" '{"tool_input":{"notebook_path":"'"$ROOT"'/nb.ipynb"}}'
check "malformed JSON (fail closed)            -> block" 2 "$GRAV" '{"tool_input":{"file_path":'

if [ "$FAILED" -eq 0 ]; then echo "ALL PASS"; else echo "SOME FAILED"; fi
exit "$FAILED"
