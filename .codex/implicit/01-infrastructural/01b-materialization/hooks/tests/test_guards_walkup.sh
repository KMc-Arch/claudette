#!/usr/bin/env bash
# Shared-tree test: gravity-guard.sh + containment-guard.sh ^-resolution walk-up.
# Proves both guards resolve the containment ceiling to the nearest root:true
# ancestor of $CLAUDE_PROJECT_DIR (matching 01a-resolution/frontmatter.md), so a
# session launched from a non-root subdir can still write to its true ^/.state
# (BL-35), while writes above ^ stay blocked. Exit 0 = all pass.
set -u

HOOKS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GRAV="$HOOKS_DIR/gravity-guard.sh"
CONT="$HOOKS_DIR/containment-guard.sh"

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

mkdir -p "$T/apex/child/sub" "$T/apex/child/grand" "$T/apex/plain" "$T/noroot/deep"
printf -- '---\napex-root: true\n---\n' > "$T/apex/CLAUDE.md"
printf -- '---\nroot: true\n---\n'       > "$T/apex/child/CLAUDE.md"

FAILED=0
check() {  # desc expect cpd guard fp
    CLAUDE_PROJECT_DIR="$3" bash "$4" >/dev/null 2>&1 <<JSON
{"tool_input":{"file_path":"$5"}}
JSON
    local rc=$?
    if [ "$rc" -eq "$2" ]; then printf 'PASS  %s  (rc=%s)\n' "$1" "$rc"
    else printf 'FAIL  %s  (expected %s, got %s)\n' "$1" "$2" "$rc"; FAILED=1; fi
}

echo "# gravity-guard (.state writes)"
check "launch-at-root: write ^/.state            -> allow" 0 "$T/apex/child"     "$GRAV" "$T/apex/child/.state/x"
check "BL-35 non-root subdir: write true ^/.state -> allow" 0 "$T/apex/child/sub" "$GRAV" "$T/apex/child/.state/x"
check "non-root subdir: write ABOVE ^ /.state     -> block" 2 "$T/apex/child/sub" "$GRAV" "$T/apex/.state/x"
check "apex-root: write apex/.state               -> allow" 0 "$T/apex"           "$GRAV" "$T/apex/.state/x"
check "write BELOW ^/.state                       -> allow" 0 "$T/apex/child"     "$GRAV" "$T/apex/child/grand/.state/x"
check "plain subdir, nearest-root=apex: apex/.state-> allow" 0 "$T/apex/plain"    "$GRAV" "$T/apex/.state/x"
check "gravity ignores non-.state write           -> allow" 0 "$T/apex/child"     "$GRAV" "$T/apex/child/notes.md"

echo "# containment-guard (all writes)"
check "BL-35 non-root subdir: write true ^ file   -> allow" 0 "$T/apex/child/sub" "$CONT" "$T/apex/child/notes.md"
check "non-root subdir: write ABOVE ^             -> block" 2 "$T/apex/child/sub" "$CONT" "$T/apex/notes.md"
check "write fully outside the tree              -> block" 2 "$T/apex/child"     "$CONT" "$T/elsewhere.md"

echo "# fallback: no root anywhere -> raw launch dir (no regression)"
check "no-root fallback: write under launch dir   -> allow" 0 "$T/noroot/deep"    "$GRAV" "$T/noroot/deep/.state/x"
check "no-root fallback: write above launch dir   -> block" 2 "$T/noroot/deep"    "$GRAV" "$T/noroot/.state/x"

echo "# cross-guard agreement (a .state write above ^ -> both block)"
check "gravity    blocks above-^ .state" 2 "$T/apex/child/sub" "$GRAV" "$T/apex/.state/x"
check "containment blocks above-^ .state" 2 "$T/apex/child/sub" "$CONT" "$T/apex/.state/x"

if [ "$FAILED" -eq 0 ]; then echo "ALL PASS"; else echo "SOME FAILED"; fi
exit "$FAILED"
