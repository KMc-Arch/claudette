#!/usr/bin/env bash
# Shared-tree test: gravity-guard.sh + containment-guard.sh ^-resolution walk-up.
# Proves both guards resolve the containment ceiling to the nearest root:true
# ancestor of $CLAUDE_PROJECT_DIR (matching 01a-resolution/frontmatter.md), so a
# session launched from a non-root subdir can still write to its true ^/.state
# (BL-35), while writes above ^ stay blocked — and that detection FAILS CLOSED on
# unreadable / malformed / absent root markers rather than loosening the ceiling.
# Exit 0 = all pass.
set -u

HOOKS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GRAV="$HOOKS_DIR/gravity-guard.sh"
CONT="$HOOKS_DIR/containment-guard.sh"

T=$(mktemp -d)
trap 'chmod -R u+rwX "$T" 2>/dev/null; rm -rf "$T"' EXIT

# --- base tree: apex-root over a root child over a non-root sub -----------------
mkdir -p "$T/apex/child/sub" "$T/apex/child/grand" "$T/apex/plain" "$T/apex/other" "$T/noroot/deep"
printf -- '---\napex-root: true\n---\n' > "$T/apex/CLAUDE.md"
printf -- '---\nroot: true\n---\n'       > "$T/apex/child/CLAUDE.md"

# --- comment-root: a valid YAML root line carrying a trailing "  # comment" (#3) -
mkdir -p "$T/cmt/proj/sub"
printf -- '---\napex-root: true\n---\n'              > "$T/cmt/CLAUDE.md"
printf -- '---\nroot: true  # child project root\n---\n' > "$T/cmt/proj/CLAUDE.md"

# --- non-regular marker: a CLAUDE.md that is a DIRECTORY at a NON-root proj.
# [ -f ] is false regardless of runner privilege, so this isolates the fail-closed
# else-branch (uid-independent, unlike a chmod-000 file which root can read).
mkdir -p "$T/nr/proj/sub" "$T/nr/proj/CLAUDE.md"
printf -- '---\napex-root: true\n---\n' > "$T/nr/CLAUDE.md"

# --- false-positive guard: `root: true#comment` (NO space) is the YAML string
# "true#comment", NOT boolean true, so proj must NOT be treated as a root (#4).
mkdir -p "$T/fp/proj"
printf -- '---\napex-root: true\n---\n'      > "$T/fp/CLAUDE.md"
printf -- '---\nroot: true#comment\n---\n'   > "$T/fp/proj/CLAUDE.md"

# --- body-fence: a NON-root doc whose body has a `---` rule then `root: true` (#5)
mkdir -p "$T/bf/proj"
printf -- '---\napex-root: true\n---\n'          > "$T/bf/CLAUDE.md"
printf -- '# Proj\n\nNotes\n\n---\nroot: true\n---\n' > "$T/bf/proj/CLAUDE.md"

FAILED=0
check() {  # desc expect cpd guard fp   (timeout so a hang FAILs instead of wedging)
    CLAUDE_PROJECT_DIR="$3" timeout 10 bash "$4" >/dev/null 2>&1 <<JSON
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

echo "# HARDENING: root marker with a trailing '  # comment' still detected (#3, fail-open fix)"
check "comment-root: write true ^ file            -> allow" 0 "$T/cmt/proj/sub" "$CONT" "$T/cmt/proj/notes.md"
check "comment-root: write ABOVE ^ (apex)         -> block" 2 "$T/cmt/proj/sub" "$CONT" "$T/cmt/x.md"
check "comment-root: write parent .state          -> block" 2 "$T/cmt/proj/sub" "$GRAV" "$T/cmt/.state/x"

echo "# HARDENING: non-regular CLAUDE.md fails CLOSED, fences here (uid-independent) (#3/#4-coda)"
check "non-regular marker: write within fenced dir -> allow" 0 "$T/nr/proj/sub" "$CONT" "$T/nr/proj/ok.md"
check "non-regular marker: write ABOVE fenced dir  -> block" 2 "$T/nr/proj/sub" "$CONT" "$T/nr/x.md"

echo "# HARDENING: 'root: true#comment' (no space) is NOT a root -> walk past (#4-coda)"
check "no-space-comment: proj not a root, write fp/.state -> allow" 0 "$T/fp/proj" "$GRAV" "$T/fp/.state/x"

echo "# HARDENING: a body '---' rule is NOT frontmatter, so proj is not a false root (#5)"
check "body-fence: proj not a root, write bf/.state-> allow" 0 "$T/bf/proj" "$GRAV" "$T/bf/.state/x"

echo "# HARDENING: empty/unset CLAUDE_PROJECT_DIR must FAIL CLOSED (block, no hang) (#1/#1-coda)"
check "empty CLAUDE_PROJECT_DIR (gravity)          -> block" 2 "" "$GRAV" "$T/apex/.state/x"
check "empty CLAUDE_PROJECT_DIR (containment)      -> block" 2 "" "$CONT" "$T/apex/notes.md"

echo "# cross-guard agreement: both guards ALLOW the true-^ write from a non-root subdir"
check "gravity     allows ^/.state from subdir" 0 "$T/apex/child/sub" "$GRAV" "$T/apex/child/.state/x"
check "containment allows ^ file  from subdir" 0 "$T/apex/child/sub" "$CONT" "$T/apex/child/deep/x"

# --- no-root fallback: guarded for hermeticity (#10) ---------------------------
# These require $T to have NO root:true ancestor. If TMPDIR sits under a root tree
# (e.g. TMPDIR=/mnt/claudette/.tmp), skip rather than false-fail.
anc="$T"; hasroot=""
while [ "$anc" != "/" ]; do
    anc=$(dirname "$anc")
    if [ -f "$anc/CLAUDE.md" ] && grep -qE '^(apex-)?root:[[:space:]]*true' "$anc/CLAUDE.md" 2>/dev/null; then
        hasroot="$anc"; break
    fi
done
echo "# no-root fallback (raw launch dir; no regression)"
if [ -z "$hasroot" ]; then
    check "no-root fallback: write under launch dir  -> allow" 0 "$T/noroot/deep" "$GRAV" "$T/noroot/deep/.state/x"
    check "no-root fallback: write above launch dir  -> block" 2 "$T/noroot/deep" "$GRAV" "$T/noroot/.state/x"
else
    echo "SKIP  no-root fallback (TMPDIR sits under root:true tree: $hasroot)"
fi

if [ "$FAILED" -eq 0 ]; then echo "ALL PASS"; else echo "SOME FAILED"; fi
exit "$FAILED"
