#!/usr/bin/env bash
# Proves how gravity-guard.sh + containment-guard.sh decode the write target:
#   - escaped-quote traversal (the \" that truncated the old grep) is BLOCKED
#   - notebook_path is checked exactly like file_path
#   - malformed JSON, a non-string path, and a missing interpreter FAIL CLOSED
#   - an oversized path cannot make normalization fall back to the raw string
#   - normal in-^ allow / out-of-^ block / no-path allow are unchanged
#
# NOTE ON notebook_path: the guards decode it, but the live PreToolUse matcher
# is "Write|Edit", which does NOT match NotebookEdit — the tool never reaches
# these hooks. These cases prove the DECODER is correct, so the guard is right
# the moment the matcher is widened. They do not prove notebooks are guarded.
# Nothing here can: a unit test that pipes JSON into the script bypasses the
# matcher by construction.
#
# A "block" assertion requires rc=2 AND a BLOCKED: line, because rc=2 is also
# bash's own error exit — an rc-only assertion stays green against a guard that
# never runs.
#
# Run: bash test_guard_extraction.sh   (exit 0 = all pass)
# GUARD_DIR=<dir> overrides which copies are tested (used by mutate_guards.sh).
set -u

G=${GUARD_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
GRAV="$G/gravity-guard.sh"
CONT="$G/containment-guard.sh"

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
ROOT="$T/root"
mkdir -p "$ROOT/sub" "$ROOT/.state" "$T/sib/.state"
# Self-fencing: without its own marker the sandbox inherits ^ from whatever
# root tree TMPDIR happens to sit under, and the assertions below stop meaning
# what they say.
printf -- '---\nroot: true\n---\n' > "$ROOT/CLAUDE.md"

# Resolve the interpreter the way the guards do (python3 || python), so a
# host with only `python` exercises the guard rather than piping empty stdin.
PY=$(command -v python3 || command -v python)
PASS=0; FAIL=0
check() {  # <desc> <expect> <guard> <json>
    local out rc
    out=$(printf '%s' "$4" | CLAUDE_PROJECT_DIR="$ROOT" timeout 20 bash "$3" 2>&1)
    rc=$?
    if [ "$rc" -ge 126 ]; then
        printf 'FAIL  %-46s harness error rc=%s\n' "$1" "$rc"; FAIL=$((FAIL+1)); return
    fi
    if [ "$2" -eq 2 ] && ! printf '%s' "$out" | grep -q '^BLOCKED:'; then
        printf 'FAIL  %-46s rc=%s with no BLOCKED: line\n' "$1" "$rc"; FAIL=$((FAIL+1)); return
    fi
    if [ "$rc" -eq "$2" ]; then printf 'PASS  %-46s rc=%s\n' "$1" "$rc"; PASS=$((PASS+1))
    else printf 'FAIL  %-46s expected %s, got %s\n' "$1" "$2" "$rc"; FAIL=$((FAIL+1)); fi
}

echo "# containment-guard — all writes"
check "in-^ file_path -> allow"                 0 "$CONT" '{"tool_input":{"file_path":"'"$ROOT"'/sub/x.md"}}'
check "escaped-quote traversal -> block"        2 "$CONT" '{"tool_input":{"file_path":"'"$ROOT"'/q\"/../../../../../../etc/evil"}}'
check "notebook_path outside ^ -> block"        2 "$CONT" '{"tool_input":{"notebook_path":"/etc/evil.ipynb"}}'
check "notebook_path inside ^ -> allow"         0 "$CONT" '{"tool_input":{"notebook_path":"'"$ROOT"'/nb.ipynb"}}'
check "plain out-of-^ file_path -> block"       2 "$CONT" '{"tool_input":{"file_path":"/etc/passwd"}}'
check "top-level file_path (no tool_input)"     2 "$CONT" '{"file_path":"/etc/passwd"}'
check "malformed JSON -> block"                 2 "$CONT" '{"tool_input":{"file_path":'
check "JSON that is not an object -> block"     2 "$CONT" '["file_path","/etc/passwd"]'
check "valid JSON, no path key -> allow"        0 "$CONT" '{"tool_input":{"command":"ls"}}'
check "file_path is an array -> block"          2 "$CONT" '{"tool_input":{"file_path":["/etc/x"]}}'
check "file_path is null -> block"              2 "$CONT" '{"tool_input":{"file_path":null}}'
check "file_path is empty string -> allow"      0 "$CONT" '{"tool_input":{"file_path":""}}'

echo
echo "# gravity-guard — only .state/ writes"
check "in-^ .state file_path -> allow"          0 "$GRAV" '{"tool_input":{"file_path":"'"$ROOT"'/.state/x"}}'
# Traversal that RESOLVES into a .state outside ^ — the case gravity owns.
check "escaped-quote into outside .state -> block" 2 "$GRAV" '{"tool_input":{"file_path":"'"$ROOT"'/.state/q\"/../../../sib/.state/evil"}}'
# And the converse: ".state" in the raw string but NOT in the resolved path is
# correctly none of gravity's business (containment blocks it — see above).
# The old suite asserted a block here, which only passed because the filter
# inspected the RAW path while the verdict used the resolved one.
check "raw .state, resolves elsewhere -> allow"  0 "$GRAV" '{"tool_input":{"file_path":"'"$ROOT"'/.state/q\"/../../../../../../etc/evil"}}'
check "sibling .state notebook_path -> block"   2 "$GRAV" '{"tool_input":{"notebook_path":"'"$T"'/sib/.state/evil.ipynb"}}'
# This must target a path OUTSIDE ^: a non-.state path inside ^ is allowed
# whether or not the .state filter exists, which made the old assertion a
# tautology. Outside ^, only the filter can produce an allow.
check "non-.state path OUTSIDE ^ -> allow"      0 "$GRAV" '{"tool_input":{"file_path":"'"$T"'/sib/plain.md"}}'
check "malformed JSON -> block"                 2 "$GRAV" '{"tool_input":{"file_path":'

echo
echo "# normalization must not depend on an exec that can fail"
# Built by shell concatenation only. Routing this through an exec (python -c,
# printf with argv) hits MAX_ARG_STRLEN itself and hands the guard an EMPTY
# payload, which blocks as undecodable JSON — a pass for the wrong reason.
BIG=$("$PY" -c 'print("a"*200000)')
check "oversized path with ../ escape -> block" 2 "$CONT" \
      '{"tool_input":{"file_path":"'"$ROOT"'/'"$BIG"'/../../../../etc/evil"}}'
check "oversized path to parent .state -> block" 2 "$GRAV" \
      '{"tool_input":{"file_path":"'"$ROOT"'/'"$BIG"'/../../sib/.state/evil"}}'

echo
echo "# the guard has NO external realpath dependency (R3 [2]: normalization is"
echo "# in-process os.path.realpath, not the shell 'realpath' binary — a broken one"
echo "# on PATH is irrelevant, which is the whole point of dropping the shell-out)."
mkdir -p "$T/stub"; printf '#!/bin/sh\nexit 1\n' > "$T/stub/realpath"; chmod +x "$T/stub/realpath"
for g in "$CONT" "$GRAV"; do
    case "$g" in *containment*) tgt="$ROOT/../../etc/evil"; nm=containment ;;
                 *)             tgt="$ROOT/../sib/.state/evil"; nm=gravity ;; esac
    # A broken 'realpath' AND 'grep' AND 'awk' on PATH — none is on the decision
    # path any more; only python is. The traversal must still block.
    out=$(printf '%s' '{"tool_input":{"file_path":"'"$tgt"'"}}' \
          | env PATH="$T/stub:$(dirname "$PY"):/usr/bin:/bin" CLAUDE_PROJECT_DIR="$ROOT" /bin/bash "$g" 2>&1); rc=$?
    if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q '^BLOCKED:'; then
        printf 'PASS  %-46s rc=2\n' "broken realpath binary is irrelevant ($nm)"; PASS=$((PASS+1))
    else printf 'FAIL  %-46s rc=%s\n' "broken realpath binary ($nm)" "$rc"; FAIL=$((FAIL+1)); fi
done

echo
echo "# R4 [0]: the outer wrapper fails closed on an abnormal python exit (rc not in {0,2})."
# Force the guard-core python step to exit 1 (a crash/uncaught-exception stand-in) by
# feeding a python shim that ignores the real program and exits 1. The wrapper must
# turn that into a BLOCK (rc=2), never an allow.
SHIM=$(mktemp -d); printf '#!/bin/sh\nexit 1\n' > "$SHIM/python3"; printf '#!/bin/sh\nexit 1\n' > "$SHIM/python"
chmod +x "$SHIM/python3" "$SHIM/python"
for g in "$CONT" "$GRAV"; do
    case "$g" in *containment*) nm=containment ;; *) nm=gravity ;; esac
    out=$(printf '%s' '{"tool_input":{"file_path":"'"$ROOT"'/sub/x.md"}}' \
          | env PATH="$SHIM:$PATH" CLAUDE_PROJECT_DIR="$ROOT" /bin/bash "$g" 2>&1); rc=$?
    if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q 'did not complete'; then
        printf 'PASS  %-46s rc=2\n' "abnormal python exit -> fail closed ($nm)"; PASS=$((PASS+1))
    else printf 'FAIL  %-46s rc=%s out=%s\n' "abnormal python exit ($nm)" "$rc" "$out"; FAIL=$((FAIL+1)); fi
done
rm -rf "$SHIM"

echo "# a missing interpreter must fail closed"
for g in "$CONT" "$GRAV"; do
    case "$g" in *containment*) nm=containment ;; *) nm=gravity ;; esac
    out=$(printf '%s' '{"tool_input":{"file_path":"'"$ROOT"'/sub/x.md"}}' \
          | env PATH=/nonexistent CLAUDE_PROJECT_DIR="$ROOT" /bin/bash "$g" 2>&1); rc=$?
    if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q 'no python interpreter'; then
        printf 'PASS  %-46s rc=2\n' "no python on PATH ($nm)"; PASS=$((PASS+1))
    else printf 'FAIL  %-46s rc=%s out=%s\n' "no python on PATH ($nm)" "$rc" "$out"; FAIL=$((FAIL+1)); fi
done

echo
echo "# an innocent json.py in the cwd must not shadow the stdlib and open the fence (R2 [0])"
SH=$(mktemp -d); printf 'raise SystemExit\n' > "$SH/json.py"
out=$( cd "$SH" && printf '%s' '{"tool_input":{"file_path":"/etc/passwd"}}' \
        | CLAUDE_PROJECT_DIR="$ROOT" /bin/bash "$CONT" 2>&1 ); rc=$?
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q '^BLOCKED:'; then
    printf 'PASS  %-46s rc=2\n' "json.py shadow does not open the fence"; PASS=$((PASS+1))
else printf 'FAIL  %-46s rc=%s\n' "json.py shadow" "$rc"; FAIL=$((FAIL+1)); fi
rm -rf "$SH"

echo
echo "# Windows drive paths against a POSIX root (test-burn B19/B20/B23)"
check "C:/ path -> block"                       2 "$CONT" '{"tool_input":{"file_path":"C:/Users/nobody/foo.txt"}}'
check "C:\\ path -> block"                      2 "$CONT" '{"tool_input":{"file_path":"C:\\Users\\nobody\\foo.txt"}}'
check "C:/ .state path -> block"                2 "$GRAV" '{"tool_input":{"file_path":"C:/some/parent/.state/foo.md"}}'

echo
echo "-------------------------------------------"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] && { echo "ALL PASS"; exit 0; }
exit 1
