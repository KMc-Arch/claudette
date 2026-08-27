#!/usr/bin/env bash
# Proves how gravity-guard.sh and containment-guard.sh resolve the containment
# ceiling ^ — the nearest root: true ancestor of the launch dir (BL-35) — and
# that every undecidable marker fences AT that directory rather than being
# walked past to a LOOSER ceiling.
#
# Every walk-up / marker scenario runs through BOTH guards (via both()), so a
# resolve_root change in only one of them cannot pass unobserved — the drift the
# docs once wrongly called impossible. A few scenarios are single-guard by nature
# (hostile CLAUDE_PROJECT_DIR, the no-root fallback, and the symlink pair, which
# test containment- and gravity-specific paths); for those, byte-identity of the
# shared core (test_guards_identical.sh) is what rules out one-guard drift.
#
# A "block" assertion requires rc=2 AND a BLOCKED: line on stderr. rc=2 alone is
# also bash's own error exit, so rc-only assertions stay green against a guard
# that never executes a line.
#
# Run: bash test_guards_walkup.sh   (exit 0 = all pass)
# GUARD_DIR=<dir> overrides which copies are tested (used by mutate_guards.sh).
set -u

G=${GUARD_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
CONT="$G/containment-guard.sh"
GRAV="$G/gravity-guard.sh"

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0

# Self-fencing fixtures: every tree gets its own apex marker, so TMPDIR sitting
# under a root tree cannot pull ^ up out of the fixture. (The old suite skipped
# in that case, losing the coverage instead.)
mkdir -p "$T/apex/proj/sub" "$T/apex/.state" "$T/outside"
printf -- '---\napex-root: true\n---\n' > "$T/apex/CLAUDE.md"
printf -- '---\nroot: true\n---\n'      > "$T/apex/proj/CLAUDE.md"

check() {  # <name> <expected-rc> <cpd> <guard> <json>
    local name=$1 want=$2 cpd=$3 guard=$4 json=$5 out rc
    out=$(printf '%s' "$json" | CLAUDE_PROJECT_DIR="$cpd" timeout 20 bash "$guard" 2>&1)
    rc=$?
    if [ "$rc" -ge 126 ]; then
        printf 'FAIL  %-52s harness error rc=%s\n' "$name" "$rc"; FAIL=$((FAIL+1)); return
    fi
    if [ "$want" -eq 2 ] && ! printf '%s' "$out" | grep -q '^BLOCKED:'; then
        printf 'FAIL  %-52s rc=%s with no BLOCKED: line\n' "$name" "$rc"; FAIL=$((FAIL+1)); return
    fi
    if [ "$rc" -eq "$want" ]; then
        printf 'PASS  %-52s rc=%s\n' "$name" "$rc"; PASS=$((PASS+1))
    else
        printf 'FAIL  %-52s expected %s, got %s\n' "$name" "$want" "$rc"; FAIL=$((FAIL+1))
    fi
}

# both <name> <cpd> <tree-root> — runs one fixture through BOTH guards.
# Containment target = a plain file above ^; gravity target = the parent .state/.
# Same fixture, same expectation, so neither guard can drift unobserved.
both() {  # <name> <expected-rc> <cpd> <above-dir>
    local name=$1 want=$2 cpd=$3 above=$4
    check "$name [containment]" "$want" "$cpd" "$CONT" "$(jp file_path "$above/notes.md")"
    check "$name [gravity]"     "$want" "$cpd" "$GRAV" "$(jp file_path "$above/.state/x.md")"
}

PY=$(command -v python3 || command -v python)
jp() { "$PY" -c 'import json,sys; print(json.dumps({"tool_input":{sys.argv[1]: sys.argv[2]}}))' "$1" "$2"; }

echo "# the ordinary case"
check "in-^ write allowed             [containment]" 0 "$T/apex/proj" "$CONT" "$(jp file_path "$T/apex/proj/ok.md")"
check "in-^ .state allowed            [gravity]"     0 "$T/apex/proj" "$GRAV" "$(jp file_path "$T/apex/proj/.state/x")"
both  "write above ^ blocked"                        2 "$T/apex/proj"        "$T/apex"
both  "walk-up: launched below the root"             2 "$T/apex/proj/sub"    "$T/apex"
check "gravity has no opinion outside .state"        0 "$T/apex/proj" "$GRAV" "$(jp file_path "$T/outside/plain.md")"

echo
echo "# root: true spellings that MUST fence here (each one used to widen ^)"
for spell in $'\xef\xbb\xbf---\nroot: true\n---\n' \
             $'---\nroot: True\n---\n' \
             $'---\nroot: yes\n---\n' \
             $'---\nroot: "true"\n---\n' \
             $'---\nroot: true  # this project\n---\n' \
             $'---\r\nroot: true\r\n---\r\n' \
             $'---\ntitle: x\nroot: true\n---\n'; do
    printf '%s' "$spell" > "$T/apex/proj/CLAUDE.md"
    label=$(printf '%s' "$spell" | tr -d '\r' | sed -n 2p)
    both "spelling [$label]" 2 "$T/apex/proj/sub" "$T/apex"
done
printf -- '---\nroot: false\n---\n' > "$T/apex/proj/CLAUDE.md"
both "root: false is NOT a root (walks up to apex)" 0 "$T/apex/proj/sub" "$T/apex"
printf -- '---\nroot: true\n---\n' > "$T/apex/proj/CLAUDE.md"

echo
echo "# undecidable markers must FENCE, never be walked past"
mk_tree() {  # <name> <how-to-make-CLAUDE.md>
    mkdir -p "$T/$1/proj/sub" "$T/$1/.state"
    printf -- '---\napex-root: true\n---\n' > "$T/$1/CLAUDE.md"
}
mk_tree dang; ln -sf "$T/dang/proj/no-such-target" "$T/dang/proj/CLAUDE.md"
both "dangling CLAUDE.md symlink"       2 "$T/dang/proj/sub" "$T/dang"
mk_tree loop; ln -sf "$T/loop/proj/CLAUDE.md" "$T/loop/proj/CLAUDE.md" 2>/dev/null
both "self-referential CLAUDE.md symlink" 2 "$T/loop/proj/sub" "$T/loop"
mk_tree dir;  mkdir -p "$T/dir/proj/CLAUDE.md"
both "CLAUDE.md that is a directory"    2 "$T/dir/proj/sub" "$T/dir"
mk_tree unt;  printf -- '---\nsome: value\nnever terminated\n' > "$T/unt/proj/CLAUDE.md"
both "frontmatter with no terminator"   2 "$T/unt/proj/sub" "$T/unt"
mk_tree nr;   mkfifo "$T/nr/proj/CLAUDE.md" 2>/dev/null || : > "$T/nr/proj/CLAUDE.md"
both "non-regular CLAUDE.md"            2 "$T/nr/proj/sub" "$T/nr"

echo
echo "# a body root: true after a CLOSED block is not a declaration"
mk_tree body
printf -- '---\ntitle: x\n---\n\n# Notes\n\nroot: true\n' > "$T/body/proj/CLAUDE.md"
both "body root: true after closed frontmatter" 0 "$T/body/proj/sub" "$T/body"
mk_tree nofm
printf -- '# Just a heading\n\nroot: true\n' > "$T/nofm/proj/CLAUDE.md"
both "no frontmatter at all"                    0 "$T/nofm/proj/sub" "$T/nofm"

echo
echo "# no root anywhere above: fall back to the launch dir (fences tighter)"
mkdir -p "$T/noroot/launch/sub"
check "fallback: write under the launch dir -> allow" 0 "$T/noroot/launch" "$CONT" "$(jp file_path "$T/noroot/launch/x.md")"
check "fallback: write above the launch dir -> block" 2 "$T/noroot/launch" "$CONT" "$(jp file_path "$T/noroot/x.md")"

echo
echo "# the ceiling must survive a hostile CLAUDE_PROJECT_DIR"
check "empty CLAUDE_PROJECT_DIR fails closed"      2 "" "$CONT" "$(jp file_path "$T/apex/proj/ok.md")"
# The assertion above is satisfied by any block, including an accidental
# fallback to the process cwd. This one is not: it targets a file INSIDE the
# cwd, so a cwd fallback would ALLOW it. Only a real fail-closed blocks here.
check "empty CPD: write inside cwd still blocked"  2 "" "$CONT" "$(jp file_path "$PWD/probe.md")"
check "CLAUDE_PROJECT_DIR=/ still allows in-root"  0 "/" "$CONT" "$(jp file_path "$T/apex/proj/ok.md")"

echo
echo "# a symlinked component must not carry a write out of ^"
mkdir -p "$T/sym/proj/sub" "$T/sym/.state"
printf -- '---\napex-root: true\n---\n' > "$T/sym/CLAUDE.md"
printf -- '---\nroot: true\n---\n'      > "$T/sym/proj/CLAUDE.md"
ln -sfn "$T/sym/.state" "$T/sym/proj/parentstate"
ln -sfn "$T/sym"        "$T/sym/proj/up"
check "symlink into the parent .state -> block" 2 "$T/sym/proj" "$GRAV" "$(jp file_path "$T/sym/proj/parentstate/x.md")"
check "symlink out of ^                -> block" 2 "$T/sym/proj" "$CONT" "$(jp file_path "$T/sym/proj/up/notes.md")"

echo
echo "# a symlinked LAUNCH DIR must resolve ^ to the real ancestry, not the link's name"
# (R2 [2]) The walk seeds from the symlink-resolved launch dir, matching
# boot-inject.py's start_dir.resolve(); a name-only walk would climb the wrong tree.
mkdir -p "$T/real/proj/sub" "$T/real/.state"
printf -- '---\napex-root: true\n---\n' > "$T/real/CLAUDE.md"
printf -- '---\nroot: true\n---\n'      > "$T/real/proj/CLAUDE.md"
ln -sfn "$T/real/proj" "$T/launchlink"          # a symlink that IS the launch dir
both  "launch dir is a symlink"                 2 "$T/launchlink" "$T/real"
check "in-^ via symlinked launch -> allow"      0 "$T/launchlink" "$CONT" "$(jp file_path "$T/real/proj/ok.md")"

echo
echo "# a '...' line inside the leading block is NOT a terminator (R2 [4])"
# Accepting it would end the block early, miss a real root:true after it, and walk
# past to a looser ceiling — the exact under-recognition the grammar forbids.
mk_tree dots
printf -- '---\n...\nroot: true\n---\n' > "$T/dots/proj/CLAUDE.md"
both "root:true after a ... line still fences"  2 "$T/dots/proj/sub" "$T/dots"

echo
echo "# a prefix-sibling of the root is OUTSIDE ^ (R2 [6])"
# ^=.../proj must not admit .../proj-evil; inside() appends a separator so the
# name prefix cannot leak. A fixture that exercises it, so the separator is covered.
mkdir -p "$T/apex/proj-evil/.state"
check "prefix-sibling dir (containment) -> block" 2 "$T/apex/proj" "$CONT" "$(jp file_path "$T/apex/proj-evil/x.md")"
check "prefix-sibling .state (gravity)  -> block" 2 "$T/apex/proj" "$GRAV" "$(jp file_path "$T/apex/proj-evil/.state/x.md")"

echo
echo "# a Windows-drive CLAUDE_PROJECT_DIR under a POSIX interpreter is refused (R2 [10][12])"
# posixpath cannot walk a drive path (c:/x -> c: -> "" -> stats the process cwd);
# refuse it outright rather than collapse to a cwd-dependent verdict.
check "Windows-drive CPD under POSIX -> block"  2 'C:\proj' "$CONT" "$(jp file_path "c:/proj/sub/a.txt")"
check "gravity ignores non-.state Win target"   0 "$T/apex/proj" "$GRAV" "$(jp file_path "C:/some/file.txt")"

echo
echo "# gravity sees a .state revealed only by symlink resolution, and one nested deep (R2 [40][42])"
mkdir -p "$T/deep/proj/sub" "$T/deep/.state/memory"
printf -- '---\napex-root: true\n---\n' > "$T/deep/CLAUDE.md"
printf -- '---\nroot: true\n---\n'      > "$T/deep/proj/CLAUDE.md"
check "parent .state nested deep -> block"      2 "$T/deep/proj" "$GRAV" "$(jp file_path "$T/deep/.state/memory/x.md")"
mkdir -p "$T/deep/.State"
check "parent .State (case-insensitive) -> block" 2 "$T/deep/proj" "$GRAV" "$(jp file_path "$T/deep/.State/x.md")"

echo
echo "-------------------------------------------"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] && { echo "ALL PASS"; exit 0; }
exit 1
