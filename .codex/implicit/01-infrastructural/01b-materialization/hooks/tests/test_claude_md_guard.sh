#!/usr/bin/env bash
# Proves claude-md-immutability-guard.sh:
#   - EVERY CLAUDE.md is covered (case-insensitive name, a hardlink to it in the
#     same directory), not only the session root's — a parent session is held to
#     the child's rule
#   - the body, the fences and every non-allowlisted frontmatter key (root:,
#     apex-root:, codex:, ...) are immutable; only name: / orchestrator: lines
#     may be added, changed or removed, with valid values
#   - the edit is judged by its RESULT (Edit, replace_all, or a full Write),
#     including the extra line break Claude Code's Edit tool deletes when
#     new_string is empty
#   - a file or result with a CR, a BOM or any non-LF line break is refused
#   - creating a new CLAUDE.md is allowed (scaffolding)
#   - anything it cannot vet fails CLOSED (bad JSON, non-UTF-8, no frontmatter,
#     old_string not verbatim, Windows drive/device paths under POSIX, a planted
#     json.py, missing/crashing interpreter, ...)
#
# Payloads are sent as RAW UTF-8 (what Claude Code writes to hook stdin), not
# \u-escaped JSON. Fixture escapes use \n \r \xNN and \N{UNICODE NAME}.
# A "block" assertion requires rc=2 AND a BLOCKED: line (rc=2 alone is also
# bash's own error exit). Fixtures live in a mktemp sandbox, which must be on a
# case-sensitive filesystem for the lowercase claude.md case to mean what it
# says. The guard never writes, so fixtures stay as built. No symlinks are
# created (ABSOLUTE HOLD) — the alias case uses a hardlink.
#
# Run: bash test_claude_md_guard.sh   (exit 0 = all pass)
# GUARD_DIR=<dir> overrides which copy is tested (used by mutate_claude_md_guard.sh).
set -u

G=${GUARD_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
GUARD="$G/claude-md-immutability-guard.sh"
PY=$(command -v python3 || command -v python)
BASH_BIN=$(command -v bash)
TO=$(command -v timeout || command -v gtimeout || true)   # macOS ships neither by default

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
ROOT="$T/root"; CHILD="$ROOT/child"; NA="$ROOT/caf"$'\xc3\xa9'
for d in "$CHILD" "$NA" low crlf bom orch nofm unterm bin smug fence swallow gam beta \
         sep2028 lonecr near loose fifo crname; do
    case "$d" in /*) mkdir -p "$d" ;; *) mkdir -p "$ROOT/$d" ;; esac
done
mkdir -p "$ROOT/dirmark/CLAUDE.md" "$T/fakebin" "$T/shadow" "$T/wa/WindowsApps" "$T/realbin"

# fx <path> <content with \n \r \xNN \N{NAME} escapes> [raw]  — exact bytes, no newline added
cat > "$T/fx.py" <<'PYEOF'
import sys
data = sys.argv[2].encode("ascii").decode("unicode_escape")
if len(sys.argv) > 3 and sys.argv[3] == "raw":
    open(sys.argv[1], "wb").write(data.encode("latin-1"))
else:
    open(sys.argv[1], "w", encoding="utf-8", newline="").write(data)
PYEOF
# j <tool> <path> [key=escaped-value ...] -> hook JSON as raw UTF-8.
#   replace_all=true|false becomes a bool; a tool written "@Write" puts file_path
#   at the top level instead of in tool_input; NotebookEdit uses notebook_path.
cat > "$T/j.py" <<'PYEOF'
import json, sys
tool, path, *kv = sys.argv[1:]
top = tool.startswith("@")
tool = tool.lstrip("@")
ti = {("notebook_path" if tool == "NotebookEdit" else "file_path"): path}
for item in kv:
    k, _, v = item.partition("=")
    ti[k] = {"true": True, "false": False}.get(v, v) if k == "replace_all" else \
        v.encode("ascii").decode("unicode_escape")
doc = {"tool_name": tool, **ti} if top else {"tool_name": tool, "tool_input": ti}
sys.stdout.buffer.write(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
PYEOF
fx() { "$PY" "$T/fx.py" "$@"; }
j()  { "$PY" "$T/j.py" "$@"; }

fx "$ROOT/CLAUDE.md"  '---\nroot: true\nname: Root Group\ncodex: ^/^/.codex\n---\n\nRead `.state/start.md`.\nRoot Group governs this tree.\n'
fx "$CHILD/CLAUDE.md" '---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\nChild body.\n'
fx "$NA/CLAUDE.md"    '---\nroot: true\nname: cafe\n---\n\nNon-ASCII folder body.\n'
fx "$ROOT/low/claude.md" '---\nroot: true\nname: low\n---\n\nLowercase-named marker.\n'
fx "$ROOT/crlf/CLAUDE.md" '---\r\nroot: true\r\nname: A\r\n---\r\n\r\nBody.\r\n'
fx "$ROOT/bom/CLAUDE.md" '\N{ZERO WIDTH NO-BREAK SPACE}---\nroot: true\nname: A\n---\n\nBody.\n'
fx "$ROOT/orch/CLAUDE.md" '---\nroot: true\nname: O\norchestrator: true\n---\n\nBody.\n'
fx "$ROOT/nofm/CLAUDE.md" 'Just a body, no frontmatter.\n'
fx "$ROOT/unterm/CLAUDE.md" '---\nroot: true\nname: U\n\nBody with no closing fence.\n'
fx "$ROOT/bin/CLAUDE.md" '---\nroot: true\nname: \xff\n---\n' raw
fx "$ROOT/smug/CLAUDE.md" '---\nname: X\N{LINE SEPARATOR}root: true\n---\n\nBody.\n'
fx "$ROOT/fence/CLAUDE.md" '---\nroot: true\n---x\nname: after-pseudo-fence\n---\n\nBody.\n'
fx "$ROOT/swallow/CLAUDE.md" '---\nname: Alpha zq9\nroot: true\ncodex: std\n---\n# Body\n'
fx "$ROOT/gam/CLAUDE.md" '---\nname: Gam zq9\n---\n# Body\n'
fx "$ROOT/beta/CLAUDE.md" '---\nname: Beta zq9\ncodex: std\n---\n# Body\n'
fx "$ROOT/sep2028/CLAUDE.md" '---\nname: Foo\ndescription: notes\N{LINE SEPARATOR}---\nroot: true\ncodex: ^/^/.codex\n---\n# Body\n'
fx "$ROOT/lonecr/CLAUDE.md" '---\nname: Foo\ndescription: notes\r---\nroot: true\n---\n# Body\n'
fx "$ROOT/loose/CLAUDE.md" '---\nroot: true\n  name: Human Name\n---\n\nBody.\n'
fx "$ROOT/crname/CLAUDE.md" '---\nroot: true\nname: A\r\n---\n\nBody.\n'
"$PY" -c 'import sys; h="---\nroot: true\nname: N\n---\n\n"; open(sys.argv[1],"w",encoding="utf-8",newline="").write(h + "b"*(1048576 - 5 - len(h)) + "\n")' "$ROOT/near/CLAUDE.md"
ln "$ROOT/CLAUDE.md" "$ROOT/alias.md"            # hardlink, not a symlink
HAVE_FIFO=0; command -v mkfifo >/dev/null 2>&1 && mkfifo "$ROOT/fifo/CLAUDE.md" && HAVE_FIFO=1
printf '#!/bin/sh\nexit 3\n' > "$T/fakebin/python3"; chmod +x "$T/fakebin/python3"
printf 'import sys\nsys.exit(0)\n' > "$T/shadow/json.py"
printf '#!/bin/sh\nexit 49\n' > "$T/wa/WindowsApps/python3"; chmod +x "$T/wa/WindowsApps/python3"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$PY" > "$T/realbin/python"; chmod +x "$T/realbin/python"

PASS=0; FAIL=0
record() {  # <desc> <expect> <rc> <out>
    if [ "$3" -ge 126 ]; then
        printf 'FAIL  %-62s harness error rc=%s\n' "$1" "$3"; FAIL=$((FAIL+1)); return
    fi
    if [ "$2" -eq 2 ] && ! printf '%s' "$4" | grep -q '^BLOCKED:'; then
        printf 'FAIL  %-62s rc=%s with no BLOCKED: line\n' "$1" "$3"; FAIL=$((FAIL+1)); return
    fi
    if [ "$3" -eq "$2" ]; then printf 'PASS  %-62s rc=%s\n' "$1" "$3"; PASS=$((PASS+1))
    else printf 'FAIL  %-62s expected %s, got %s  %s\n' "$1" "$2" "$3" "$(printf '%s' "$4" | head -1)"; FAIL=$((FAIL+1)); fi
}
check() {  # <desc> <expect> <json> [CLAUDE_PROJECT_DIR]
    local out rc
    out=$(printf '%s' "$3" | CLAUDE_PROJECT_DIR="${4-$ROOT}" ${TO:+"$TO" 20} bash "$GUARD" 2>&1); rc=$?
    record "$1" "$2" "$rc" "$out"
}

R="$ROOT/CLAUDE.md"; C="$CHILD/CLAUDE.md"

echo "# not a CLAUDE.md — no opinion"
check "ordinary file, no frontmatter -> allow"                      0 "$(j Write "$ROOT/notes.md" content='hi\n')"
check "no path parameter -> allow"                                  0 '{"tool_name":"Bash","tool_input":{"command":"ls"}}'
check "relative ordinary file -> allow"                             0 "$(j Write notes.md content='x')"
check "top-level file_path, ordinary file -> allow"                 0 "$(j @Write "$ROOT/notes.md")"

echo "# allowlisted frontmatter edits -> allow"
check "Edit name: value (own)"                                      0 "$(j Edit "$R" old_string='name: Root Group\n' new_string='name: Root Group Two\n')"
check "add orchestrator: true"                                      0 "$(j Edit "$R" old_string='name: Root Group\n' new_string='name: Root Group\norchestrator: true\n')"
check "orchestrator: true -> false"                                 0 "$(j Edit "$ROOT/orch/CLAUDE.md" old_string='orchestrator: true' new_string='orchestrator: false')"
check "remove orchestrator: line (with its newline)"                0 "$(j Edit "$ROOT/orch/CLAUDE.md" old_string='orchestrator: true\n' new_string='')"
check "parent session edits child name:"                            0 "$(j Edit "$C" old_string='name: child' new_string='name: kid')"
check "replace_all touching only name:"                             0 "$(j Edit "$C" old_string='child' new_string='kid' replace_all=true)"
check "relative CLAUDE.md path anchored to CPD, name: edit"         0 "$(j Edit child/CLAUDE.md old_string='name: child' new_string='name: kid')"
check "Write whole file, only name: changed"                        0 "$(j Write "$R" content='---\nroot: true\nname: Renamed\ncodex: ^/^/.codex\n---\n\nRead `.state/start.md`.\nRoot Group governs this tree.\n')"
check "Write identical content (no-op)"                             0 "$(j Write "$C" content='---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\nChild body.\n')"
check "Write creates a new CLAUDE.md"                               0 "$(j Write "$ROOT/newproj/CLAUDE.md" content='---\nroot: true\ncodex: /anything\n---\n\nNew body.\n')"
check "non-ASCII folder: name: edit"                                0 "$(j Edit "$NA/CLAUDE.md" old_string='name: cafe' new_string='name: caf\xe9')"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | PATH="$T/wa/WindowsApps:$T/realbin:/usr/bin:/bin" CLAUDE_PROJECT_DIR="$ROOT" bash "$GUARD" 2>&1); rc=$?
record "Windows Store python3 stub is skipped (name: edit)"         0 "$rc" "$out"

echo "# body, fences, protected keys -> block"
check "body edit, own CLAUDE.md (child session)"                    2 "$(j Edit "$C" old_string='Child body.' new_string='Rewritten.')" "$CHILD"
check "body edit of a lowercase claude.md"                          2 "$(j Edit "$ROOT/low/claude.md" old_string='Lowercase-named marker.' new_string='X')"
check "flip root: true -> false"                                    2 "$(j Edit "$C" old_string='root: true' new_string='root: false')" "$CHILD"
check "repoint codex:"                                              2 "$(j Edit "$C" old_string='codex: ^/^/.codex' new_string='codex: /elsewhere')"
check "add apex-root: true"                                         2 "$(j Edit "$C" old_string='root: true\n' new_string='root: true\napex-root: true\n')"
check "parent session edits child body"                             2 "$(j Edit "$C" old_string='Child body.' new_string='Parent wrote this.')"
check "parent Write-overwrites child body"                          2 "$(j Write "$C" content='---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\nNew body.\n')"
check "Write drops the trailing newline only"                       2 "$(j Write "$C" content='---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\nChild body.')"
check "add a comment line inside frontmatter"                       2 "$(j Edit "$C" old_string='name: child\n' new_string='name: child\n# note\n')"
check "rename key name: -> Name:"                                   2 "$(j Edit "$C" old_string='name: child' new_string='Name: child')"
check "indented orchestrator: line"                                 2 "$(j Edit "$C" old_string='name: child\n' new_string='name: child\n  orchestrator: true\n')"
check "replace_all also hits the body"                              2 "$(j Edit "$R" old_string='Root Group' new_string='X' replace_all=true)"
check "replace_all true->false also hits root:"                     2 "$(j Edit "$ROOT/orch/CLAUDE.md" old_string='true' new_string='false' replace_all=true)"
check "edit that moves the closing fence"                           2 "$(j Edit "$C" old_string='---\n\nChild' new_string='\n---\nChild')"
check "line after a ---x pseudo-fence is body"                      2 "$(j Edit "$ROOT/fence/CLAUDE.md" old_string='name: after-pseudo-fence' new_string='name: changed')"
check "non-ASCII folder: Write flipping root:"                      2 "$(j Write "$NA/CLAUDE.md" content='---\nroot: false\nname: cafe\n---\n\nNon-ASCII folder body.\n')"
check "add a column-0 name: beside an indented one"                 2 "$(j Edit "$ROOT/loose/CLAUDE.md" old_string='root: true\n' new_string='root: true\nname: Other\n')"

echo "# the Edit tool's extra line break on an empty new_string -> block"
check "empty new_string would swallow the root: line"               2 "$(j Edit "$ROOT/swallow/CLAUDE.md" old_string=' zq9' new_string='')"
check "empty new_string would swallow the closing fence"            2 "$(j Edit "$ROOT/gam/CLAUDE.md" old_string=' zq9' new_string='')"
check "replace_all empty new_string would swallow codex:"           2 "$(j Edit "$ROOT/beta/CLAUDE.md" old_string=' zq9' new_string='' replace_all=true)"
check "delete a name: line without its newline (both results checked)" 2 "$(j Edit "$C" old_string='name: child' new_string='')"

echo "# CR, BOM and non-LF line breaks -> block"
check "U+2028 before a fence: inserting a line moves the readers' fence" 2 "$(j Edit "$ROOT/sep2028/CLAUDE.md" old_string='\N{LINE SEPARATOR}---\n' new_string='\N{LINE SEPARATOR}orchestrator: true\n---\n')"
check "lone CR before a fence: same attack"                         2 "$(j Edit "$ROOT/lonecr/CLAUDE.md" old_string='notes\r' new_string='notes\rorchestrator: true\n')"
check "remove a name: line that hides root: behind U+2028"          2 "$(j Edit "$ROOT/smug/CLAUDE.md" old_string='name: X\N{LINE SEPARATOR}root: true\n' new_string='')"
check "U+2028 smuggles root: false into name:"                      2 "$(j Edit "$C" old_string='name: child\n' new_string='name: X\N{LINE SEPARATOR}root: false\n')"
check "NEL smuggles root: false into name:"                         2 "$(j Edit "$C" old_string='name: child\n' new_string='name: X\x85root: false\n')"
check "CRLF file: Write keeping CRLF, name: changed"                2 "$(j Write "$ROOT/crlf/CLAUDE.md" content='---\r\nroot: true\r\nname: B\r\n---\r\n\r\nBody.\r\n')"
check "CRLF file, LF old_string"                                    2 "$(j Edit "$ROOT/crlf/CLAUDE.md" old_string='root: true\nname: A' new_string='root: true\nname: B')"
check "BOM file: Edit name:"                                        2 "$(j Edit "$ROOT/bom/CLAUDE.md" old_string='name: A' new_string='name: B')"
check "Write adding a CR to a name: line"                           2 "$(j Write "$C" content='---\nroot: true\nname: child\r\ncodex: ^/^/.codex\n---\n\nChild body.\n')"
check "CR only on a name: line, removed by the edit (file refused)" 2 "$(j Edit "$ROOT/crname/CLAUDE.md" old_string='name: A\r\n' new_string='name: B\n')"

echo "# invalid allowlisted values -> block"
check "orchestrator: maybe"                                         2 "$(j Edit "$ROOT/orch/CLAUDE.md" old_string='orchestrator: true' new_string='orchestrator: maybe')"
check "duplicate name: line"                                        2 "$(j Edit "$C" old_string='name: child\n' new_string='name: child\nname: other\n')"
check "bidi override in name:"                                      2 "$(j Edit "$C" old_string='name: child' new_string='name: a\N{RIGHT-TO-LEFT OVERRIDE}b')"
check "ESC in name:"                                                2 "$(j Edit "$C" old_string='name: child' new_string='name: a\x1bb')"
check "NUL in name:"                                                2 "$(j Edit "$C" old_string='name: child' new_string='name: a\x00b')"
check "name: starting with {"                                       2 "$(j Edit "$C" old_string='name: child' new_string='name: {root: false}')"
check "name: containing ---"                                        2 "$(j Edit "$C" old_string='name: child' new_string='name: Travel --- Europe')"
check "name: longer than 200 chars"                                 2 "$(j Edit "$C" old_string='name: child' new_string="name: $(printf 'x%.0s' $(seq 1 210))")"
check "name: with more than 8 leading blanks"                       2 "$(j Edit "$C" old_string='name: child' new_string='name:         child')"
check "empty name:"                                                 2 "$(j Edit "$C" old_string='name: child' new_string='name:')"
check "result over 1 MiB (valid key added to a near-cap file)"      2 "$(j Edit "$ROOT/near/CLAUDE.md" old_string='name: N\n' new_string='name: N\norchestrator: true\n')"

echo "# coverage of aliases, paths and odd files -> block"
check "hardlink alias to CLAUDE.md, body edit"                      2 "$(j Edit "$ROOT/alias.md" old_string='Root Group governs this tree.' new_string='X')"
check "backslash path to a CLAUDE.md, body edit"                    2 "$(j Edit "$ROOT"'\child\CLAUDE.md' old_string='Child body.' new_string='X')"
check "relative CLAUDE.md path anchored to CPD, body edit"          2 "$(j Edit child/CLAUDE.md old_string='Child body.' new_string='X')"
check "relative CLAUDE.md path, no CPD"                             2 "$(j Edit child/CLAUDE.md old_string='name: child' new_string='name: kid')" ""
check "Windows drive path under POSIX (would read as creation)"     2 "$(j Write 'C:/proj/CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "Windows drive path, backslashes"                             2 "$(j Write 'C:\proj\CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "device path \\\\.\\C:\\... to a CLAUDE.md"                   2 "$(j Write '\\.\C:\proj\CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "device path \\\\?\\UNC\\... to a CLAUDE.md"                  2 "$(j Write '\\?\UNC\host\share\CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "file without frontmatter"                                    2 "$(j Edit "$ROOT/nofm/CLAUDE.md" old_string='Just a body' new_string='---\norchestrator: true\n---\nJust a body')"
check "unterminated frontmatter"                                    2 "$(j Edit "$ROOT/unterm/CLAUDE.md" old_string='name: U' new_string='name: V')"
check "non-UTF-8 CLAUDE.md"                                         2 "$(j Edit "$ROOT/bin/CLAUDE.md" old_string='root: true' new_string='root: true')"
check "CLAUDE.md is a directory"                                    2 "$(j Write "$ROOT/dirmark/CLAUDE.md" content='x')"
if [ "$HAVE_FIFO" -eq 1 ]; then
check "CLAUDE.md is a FIFO"                                         2 "$(j Write "$ROOT/fifo/CLAUDE.md" content='x')"
else echo "SKIP  CLAUDE.md is a FIFO (no mkfifo here)"; fi
check "Edit a CLAUDE.md that does not exist"                        2 "$(j Edit "$ROOT/ghost/CLAUDE.md" old_string='a' new_string='b')"
check "Write strips the BOM"                                        2 "$(j Write "$ROOT/bom/CLAUDE.md" content='---\nroot: true\nname: A\n---\n\nBody.\n')"
mkdir -p "$ROOT/huge"
# Over the cap, with the old_string also far past it: a guard reading only the
# first MiB would see one (frontmatter) occurrence, and a shrinking replace_all
# would fit under the result cap while the real tool also rewrote the body.
"$PY" -c 'import sys; a="name: "+"A"*150; open(sys.argv[1],"w",encoding="utf-8",newline="").write("---\nroot: true\n"+a+"\n---\n\n"+"b"*1048576+"\n"+a+"\n")' "$ROOT/huge/CLAUDE.md"
check "CLAUDE.md over 1 MiB (replace_all past the read cap)"        2 "$(j Edit "$ROOT/huge/CLAUDE.md" old_string="name: $(printf 'A%.0s' $(seq 1 150))" new_string='name: B' replace_all=true)"

echo "# malformed or unvettable input -> block"
check "old_string not verbatim (curly quote)"                       2 "$(j Edit "$C" old_string='name: \N{RIGHT SINGLE QUOTATION MARK}child' new_string='name: kid')"
check "empty old_string"                                            2 "$(j Edit "$C" old_string='' new_string='x')"
check "empty old_string with replace_all"                           2 "$(j Edit "$C" old_string='' new_string='' replace_all=true)"
check "old_string ambiguous without replace_all"                    2 "$(j Edit "$R" old_string='Root Group' new_string='X')"
check "replace_all not a bool"                                      2 "$(j Edit "$C" old_string='name: child' new_string='name: kid' replace_all=yes)"
check "Write with no content"                                       2 "$(j Write "$C")"
check "top-level file_path CLAUDE.md, no content"                   2 "$(j @Write "$C")"
check "NotebookEdit aimed at CLAUDE.md"                             2 "$(j NotebookEdit "$C" old_string='name: child' new_string='name: kid')"
check "malformed JSON"                                              2 '{"tool_name":"Edit","tool_input":'
check "JSON that is not an object"                                  2 '["Edit"]'
check "file_path not a string"                                      2 '{"tool_name":"Edit","tool_input":{"file_path":7}}'
check "hook stdin that is not UTF-8"                                2 "$(printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"\xff"}}' "$C")"
"$PY" -c 'import json,sys; sys.stdout.write(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":"---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\n"+"B"*200000+"\n"}}))' "$C" > "$T/big.json"
check "Write >128 KB (the old env-var handoff failed open on E2BIG)" 2 "$(cat "$T/big.json")"

echo "# interpreter failures -> block"
out=$(printf '%s' "$(j Edit "$C" old_string='Child body.' new_string='Owned.')" | (cd "$T/shadow" && CLAUDE_PROJECT_DIR="$ROOT" bash "$GUARD") 2>&1); rc=$?
record "json.py planted in the hook's cwd (python -I)"               2 "$rc" "$out"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | env -i PATH=/nonexistent CLAUDE_PROJECT_DIR="$ROOT" "$BASH_BIN" "$GUARD" 2>&1); rc=$?
record "no python interpreter on PATH"                              2 "$rc" "$out"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | PATH="$T/fakebin:$PATH" CLAUDE_PROJECT_DIR="$ROOT" bash "$GUARD" 2>&1); rc=$?
record "interpreter exits with an unexpected rc"                    2 "$rc" "$out"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
