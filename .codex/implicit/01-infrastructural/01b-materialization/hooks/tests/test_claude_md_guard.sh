#!/usr/bin/env bash
# Proves claude-md-immutability-guard.sh:
#   - EVERY CLAUDE.md is covered (case-insensitive name, hardlink / short-name
#     alias), not only the session root's — a parent session is held to the
#     child's rule
#   - the body, the fences and every non-allowlisted frontmatter key (root:,
#     apex-root:, codex:, ...) are immutable; only name: / orchestrator: lines
#     may be added, changed or removed, with valid values
#   - the edit is judged by its RESULT (Edit, replace_all, or a full Write)
#   - creating a new CLAUDE.md is allowed (scaffolding)
#   - anything it cannot vet fails CLOSED (bad JSON, non-UTF-8, no frontmatter,
#     old_string not verbatim, missing/crashing interpreter, ...)
#
# A "block" assertion requires rc=2 AND a BLOCKED: line (rc=2 alone is also
# bash's own error exit). Fixtures live in a mktemp sandbox; the guard never
# writes, so they stay as built. No symlinks are created (ABSOLUTE HOLD) — the
# alias case uses a hardlink.
#
# Run: bash test_claude_md_guard.sh   (exit 0 = all pass)
# GUARD_DIR=<dir> overrides which copy is tested (used by mutate_claude_md_guard.sh).
set -u

G=${GUARD_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
GUARD="$G/claude-md-immutability-guard.sh"
PY=$(command -v python3 || command -v python)
BASH_BIN=$(command -v bash)

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
ROOT="$T/root"; CHILD="$ROOT/child"
mkdir -p "$CHILD" "$ROOT/low" "$ROOT/dirmark/CLAUDE.md" "$T/fakebin" \
         "$ROOT/crlf" "$ROOT/bom" "$ROOT/orch" "$ROOT/nofm" "$ROOT/unterm" \
         "$ROOT/bin" "$ROOT/smug" "$ROOT/fence"

# fx <path> <content with \n \r \uXXXX \xNN escapes>  — exact bytes, no newline added
cat > "$T/fx.py" <<'PYEOF'
import sys
data = sys.argv[2].encode("ascii").decode("unicode_escape")
if len(sys.argv) > 3 and sys.argv[3] == "raw":
    open(sys.argv[1], "wb").write(data.encode("latin-1"))
else:
    open(sys.argv[1], "w", encoding="utf-8", newline="").write(data)
PYEOF
# j <tool> <path> [key=escaped-value ...]  -> hook JSON (replace_all=true|false is a bool)
cat > "$T/j.py" <<'PYEOF'
import json, sys
tool, path, *kv = sys.argv[1:]
ti = {"file_path": path}
for item in kv:
    k, _, v = item.partition("=")
    if k == "replace_all":
        ti[k] = {"true": True, "false": False}.get(v, v)
    else:
        ti[k] = v.encode("ascii").decode("unicode_escape")
print(json.dumps({"tool_name": tool, "tool_input": ti}))
PYEOF
fx() { "$PY" "$T/fx.py" "$@"; }
j()  { "$PY" "$T/j.py" "$@"; }

fx "$ROOT/CLAUDE.md"  '---\nroot: true\nname: Root Group\ncodex: ^/^/.codex\n---\n\nRead `.state/start.md`.\nRoot Group governs this tree.\n'
fx "$CHILD/CLAUDE.md" '---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\nChild body.\n'
fx "$ROOT/low/claude.md" '---\nroot: true\nname: low\n---\n\nLowercase-named marker.\n'
fx "$ROOT/crlf/CLAUDE.md" '---\r\nroot: true\r\nname: A\r\n---\r\n\r\nBody.\r\n'
fx "$ROOT/bom/CLAUDE.md" '\ufeff---\nroot: true\nname: A\n---\n\nBody.\n'
fx "$ROOT/orch/CLAUDE.md" '---\nroot: true\nname: O\norchestrator: true\n---\n\nBody.\n'
fx "$ROOT/nofm/CLAUDE.md" 'Just a body, no frontmatter.\n'
fx "$ROOT/unterm/CLAUDE.md" '---\nroot: true\nname: U\n\nBody with no closing fence.\n'
fx "$ROOT/bin/CLAUDE.md" '---\nroot: true\nname: \xff\n---\n' raw
fx "$ROOT/smug/CLAUDE.md" '---\nname: X\u2028root: true\n---\n\nBody.\n'
fx "$ROOT/fence/CLAUDE.md" '---\nroot: true\n---x\nname: after-pseudo-fence\n---\n\nBody.\n'
ln "$ROOT/CLAUDE.md" "$ROOT/alias.md"            # hardlink, not a symlink
printf '#!/bin/sh\nexit 3\n' > "$T/fakebin/python3"; chmod +x "$T/fakebin/python3"

PASS=0; FAIL=0
record() {  # <desc> <expect> <rc> <out>
    if [ "$3" -ge 126 ]; then
        printf 'FAIL  %-60s harness error rc=%s\n' "$1" "$3"; FAIL=$((FAIL+1)); return
    fi
    if [ "$2" -eq 2 ] && ! printf '%s' "$4" | grep -q '^BLOCKED:'; then
        printf 'FAIL  %-60s rc=%s with no BLOCKED: line\n' "$1" "$3"; FAIL=$((FAIL+1)); return
    fi
    if [ "$3" -eq "$2" ]; then printf 'PASS  %-60s rc=%s\n' "$1" "$3"; PASS=$((PASS+1))
    else printf 'FAIL  %-60s expected %s, got %s  %s\n' "$1" "$2" "$3" "$(printf '%s' "$4" | head -1)"; FAIL=$((FAIL+1)); fi
}
check() {  # <desc> <expect> <json> [CLAUDE_PROJECT_DIR]
    local out rc
    out=$(printf '%s' "$3" | CLAUDE_PROJECT_DIR="${4-$ROOT}" timeout 20 bash "$GUARD" 2>&1); rc=$?
    record "$1" "$2" "$rc" "$out"
}

R="$ROOT/CLAUDE.md"; C="$CHILD/CLAUDE.md"

echo "# not a CLAUDE.md — no opinion"
check "ordinary file, no frontmatter -> allow"                    0 "$(j Write "$ROOT/notes.md" content='hi\n')"
check "no path parameter -> allow"                                0 '{"tool_name":"Bash","tool_input":{"command":"ls"}}'
check "relative ordinary file -> allow"                           0 "$(j Write notes.md content='x')"
check "top-level file_path, ordinary file -> allow"               0 '{"tool_name":"Write","file_path":"'"$ROOT"'/notes.md"}'

echo "# allowlisted frontmatter edits -> allow"
check "Edit name: value (own)"                                    0 "$(j Edit "$R" old_string='name: Root Group\n' new_string='name: Root Group Two\n')"
check "add orchestrator: true"                                    0 "$(j Edit "$R" old_string='name: Root Group\n' new_string='name: Root Group\norchestrator: true\n')"
check "orchestrator: true -> false"                               0 "$(j Edit "$ROOT/orch/CLAUDE.md" old_string='orchestrator: true' new_string='orchestrator: false')"
check "remove orchestrator: line"                                 0 "$(j Edit "$ROOT/orch/CLAUDE.md" old_string='orchestrator: true\n' new_string='')"
check "parent session edits child name:"                          0 "$(j Edit "$C" old_string='name: child' new_string='name: kid')"
check "replace_all touching only name:"                           0 "$(j Edit "$C" old_string='child' new_string='kid' replace_all=true)"
check "Write whole file, only name: changed"                      0 "$(j Write "$R" content='---\nroot: true\nname: Renamed\ncodex: ^/^/.codex\n---\n\nRead `.state/start.md`.\nRoot Group governs this tree.\n')"
check "Write identical content (no-op)"                           0 "$(j Write "$C" content='---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\nChild body.\n')"
check "CRLF file: Write keeps CRLF, name: changed"                0 "$(j Write "$ROOT/crlf/CLAUDE.md" content='---\r\nroot: true\r\nname: B\r\n---\r\n\r\nBody.\r\n')"
check "BOM file: Edit name:"                                      0 "$(j Edit "$ROOT/bom/CLAUDE.md" old_string='name: A' new_string='name: B')"
check "Write creates a new CLAUDE.md"                             0 "$(j Write "$ROOT/newproj/CLAUDE.md" content='---\nroot: true\ncodex: /anything\n---\n\nNew body.\n')"

echo "# body, fences, protected keys -> block"
check "body edit, own CLAUDE.md (child session)"                  2 "$(j Edit "$C" old_string='Child body.' new_string='Rewritten.')" "$CHILD"
check "body edit of a lowercase claude.md"                        2 "$(j Edit "$ROOT/low/claude.md" old_string='Lowercase-named marker.' new_string='X')"
check "flip root: true -> false"                                  2 "$(j Edit "$C" old_string='root: true' new_string='root: false')" "$CHILD"
check "repoint codex:"                                            2 "$(j Edit "$C" old_string='codex: ^/^/.codex' new_string='codex: /elsewhere')"
check "add apex-root: true"                                       2 "$(j Edit "$C" old_string='root: true\n' new_string='root: true\napex-root: true\n')"
check "parent session edits child body"                           2 "$(j Edit "$C" old_string='Child body.' new_string='Parent wrote this.')"
check "parent Write-overwrites child body"                        2 "$(j Write "$C" content='---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\nNew body.\n')"
check "Write drops the trailing newline only"                     2 "$(j Write "$C" content='---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\nChild body.')"
check "add a comment line inside frontmatter"                     2 "$(j Edit "$C" old_string='name: child\n' new_string='name: child\n# note\n')"
check "rename key name: -> Name:"                                 2 "$(j Edit "$C" old_string='name: child' new_string='Name: child')"
check "indented orchestrator: line"                               2 "$(j Edit "$C" old_string='name: child\n' new_string='name: child\n  orchestrator: true\n')"
check "replace_all also hits the body"                            2 "$(j Edit "$R" old_string='Root Group' new_string='X' replace_all=true)"
check "replace_all true->false also hits root:"                   2 "$(j Edit "$ROOT/orch/CLAUDE.md" old_string='true' new_string='false' replace_all=true)"
check "edit that moves the closing fence"                         2 "$(j Edit "$C" old_string='---\n\nChild' new_string='\n---\nChild')"
check "line after a ---x pseudo-fence is body"                    2 "$(j Edit "$ROOT/fence/CLAUDE.md" old_string='name: after-pseudo-fence' new_string='name: changed')"
check "remove a name: line that hides root: behind U+2028"        2 "$(j Edit "$ROOT/smug/CLAUDE.md" old_string='name: X\u2028root: true\n' new_string='')"

echo "# invalid allowlisted values -> block"
check "orchestrator: maybe"                                       2 "$(j Edit "$ROOT/orch/CLAUDE.md" old_string='orchestrator: true' new_string='orchestrator: maybe')"
check "duplicate name: line"                                      2 "$(j Edit "$C" old_string='name: child\n' new_string='name: child\nname: other\n')"
check "U+2028 smuggles root: false into name:"                    2 "$(j Edit "$C" old_string='name: child\n' new_string='name: X\u2028root: false\n')"
check "bidi override in name:"                                    2 "$(j Edit "$C" old_string='name: child' new_string='name: a\u202eb')"
check "name: starting with {"                                     2 "$(j Edit "$C" old_string='name: child' new_string='name: {root: false}')"
check "name: longer than 200 chars"                               2 "$(j Edit "$C" old_string='name: child' new_string="name: $(printf 'x%.0s' $(seq 1 210))")"
check "empty name:"                                               2 "$(j Edit "$C" old_string='name: child' new_string='name:')"

echo "# coverage of aliases and odd files -> block"
check "hardlink alias to CLAUDE.md, body edit"                    2 "$(j Edit "$ROOT/alias.md" old_string='Root Group governs this tree.' new_string='X')"
check "relative CLAUDE.md path anchored to CPD"                   2 "$(j Edit child/CLAUDE.md old_string='Child body.' new_string='X')"
check "relative CLAUDE.md path, no CPD"                           2 "$(j Edit child/CLAUDE.md old_string='name: child' new_string='name: kid')" ""
check "file without frontmatter"                                  2 "$(j Edit "$ROOT/nofm/CLAUDE.md" old_string='Just a body' new_string='---\norchestrator: true\n---\nJust a body')"
check "unterminated frontmatter"                                  2 "$(j Edit "$ROOT/unterm/CLAUDE.md" old_string='name: U' new_string='name: V')"
check "non-UTF-8 CLAUDE.md"                                       2 "$(j Edit "$ROOT/bin/CLAUDE.md" old_string='root: true' new_string='root: true')"
check "CLAUDE.md is a directory"                                  2 "$(j Write "$ROOT/dirmark/CLAUDE.md" content='x')"
check "Edit a CLAUDE.md that does not exist"                      2 "$(j Edit "$ROOT/ghost/CLAUDE.md" old_string='a' new_string='b')"
check "CRLF file, LF old_string (tool would match loosely)"       2 "$(j Edit "$ROOT/crlf/CLAUDE.md" old_string='root: true\nname: A' new_string='root: true\nname: B')"
check "Write converts CRLF to LF"                                 2 "$(j Write "$ROOT/crlf/CLAUDE.md" content='---\nroot: true\nname: A\n---\n\nBody.\n')"
check "Write strips the BOM"                                      2 "$(j Write "$ROOT/bom/CLAUDE.md" content='---\nroot: true\nname: A\n---\n\nBody.\n')"

echo "# malformed or unvettable input -> block"
check "old_string not verbatim (curly quote)"                     2 "$(j Edit "$C" old_string='name: \u2019child' new_string='name: kid')"
check "empty old_string"                                          2 "$(j Edit "$C" old_string='' new_string='x')"
check "old_string ambiguous without replace_all"                  2 "$(j Edit "$R" old_string='Root Group' new_string='X')"
check "replace_all not a bool"                                    2 "$(j Edit "$C" old_string='name: child' new_string='name: kid' replace_all=yes)"
check "Write with no content"                                     2 "$(j Write "$C")"
check "top-level file_path CLAUDE.md, no content"                 2 '{"tool_name":"Write","file_path":"'"$C"'"}'
check "NotebookEdit aimed at CLAUDE.md"                           2 '{"tool_name":"NotebookEdit","tool_input":{"notebook_path":"'"$C"'","old_string":"name: child","new_string":"name: kid"}}'
check "malformed JSON"                                            2 '{"tool_name":"Edit","tool_input":'
check "JSON that is not an object"                                2 '["Edit"]'
check "file_path not a string"                                    2 '{"tool_name":"Edit","tool_input":{"file_path":7}}'
"$PY" -c 'import json,sys; print(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":"---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\n"+"B"*200000+"\n"}}))' "$C" > "$T/big.json"
check "Write >128 KB content changing the body"                   2 "$(cat "$T/big.json")"
mkdir -p "$ROOT/huge"
"$PY" -c 'import sys; open(sys.argv[1],"w",encoding="utf-8",newline="").write("---\nroot: true\nname: A\n---\n\n" + "b"*1100000 + "\nname: A\n")' "$ROOT/huge/CLAUDE.md"
check "CLAUDE.md over 1 MiB (replace_all past the read cap)"      2 "$(j Edit "$ROOT/huge/CLAUDE.md" old_string='name: A' new_string='name: B' replace_all=true)"
mkdir -p "$ROOT/huge"
"$PY" -c 'import sys; open(sys.argv[1], "w").write("---\nroot: true\nname: A\n---\n\n" + "b" * 1100000 + "\nname: A\n")' "$ROOT/huge/CLAUDE.md"
check "CLAUDE.md over 1 MiB (edit reaching past the vetted prefix)" 2 "$(j Edit "$ROOT/huge/CLAUDE.md" old_string='name: A' new_string='name: B' replace_all=true)"

echo "# interpreter failures -> block"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | env -i PATH=/nonexistent CLAUDE_PROJECT_DIR="$ROOT" "$BASH_BIN" "$GUARD" 2>&1); rc=$?
record "no python interpreter on PATH"                            2 "$rc" "$out"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | PATH="$T/fakebin:$PATH" CLAUDE_PROJECT_DIR="$ROOT" bash "$GUARD" 2>&1); rc=$?
record "interpreter exits with an unexpected rc"                  2 "$rc" "$out"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
