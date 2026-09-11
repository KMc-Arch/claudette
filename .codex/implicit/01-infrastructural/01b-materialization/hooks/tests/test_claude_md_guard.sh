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
#   - a file or result with a CR, a BOM or any non-LF line break is refused;
#     a frontmatter block ending past 64 KiB is refused
#   - moving an allowlisted line past a protected one is re-checked as a change
#   - an existing CLAUDE.md must be addressed by its exact on-disk name
#   - creating a new CLAUDE.md is refused too (scaffolding runs scripts)
#   - anything it cannot vet fails CLOSED (bad JSON, non-UTF-8, no frontmatter,
#     old_string not verbatim, a path it cannot stat cleanly, device-namespace,
#     drive-relative and /proc paths, drive paths under POSIX, a planted json.py,
#     missing/crashing interpreter, a closed stderr, ...)
#
# Payloads are sent as RAW UTF-8 (what Claude Code writes to hook stdin), not
# \u-escaped JSON. Fixture/argument escapes use \n \r \xNN, \N{UNICODE NAME} and
# <U+XXXX> (any code point, including a lone surrogate, which j.py sends as a JSON
# \u escape the way JSON.stringify does).
# A "block" assertion requires rc=2 AND a BLOCKED: line (rc=2 alone is also
# bash's own error exit). Fixtures live in a mktemp sandbox, which must be on a
# case-sensitive filesystem for the lowercase claude.md case to mean what it
# says; the exact-on-disk-name case needs a CASE-INSENSITIVE scratch and uses the
# apex's .state/tmp when that is one (else it is skipped). Under Windows Python
# the POSIX-only drive-path cases are skipped. The guard never writes, so
# fixtures stay as built. No symlinks are created (ABSOLUTE HOLD) — the alias
# case uses a hardlink.
#
# Run: bash test_claude_md_guard.sh   (exit 0 = all pass)
# GUARD_DIR=<dir> overrides which copy is tested (used by mutate_claude_md_guard.sh).
set -u

G=${GUARD_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
GUARD="$G/claude-md-immutability-guard.sh"
PY=$(command -v python3 || command -v python)
BASH_BIN=$(command -v bash)
TO=$(command -v timeout || command -v gtimeout || true)   # macOS ships neither by default

IS_NT=$("$PY" -c 'import os; print(int(os.name == "nt"))')
APEX=$(cd "$(dirname "$0")/../../../../../.." && pwd)

T=$(mktemp -d)
CI=
trap 'chmod -R u+rwx "$T" 2>/dev/null; rm -rf "$T" ${CI:+"$CI"}' EXIT
case "$T" in /*|[A-Za-z]:/*) ;; *) echo "HARNESS: mktemp gave a non-absolute path: $T"; exit 99 ;; esac
ROOT="$T/root"; CHILD="$ROOT/child"; NA="$ROOT/caf"$'\xc3\xa9'; FF="$ROOT/fffd"$'\xef\xbf\xbd'"dir"
for d in "$CHILD" "$NA" "$FF" low crlf bom orch nofm unterm bin smug fence swallow gam beta \
         sep2028 lonecr near loose fifo crname movedash swap mover scancap quotedkey recased \
         bombody wo noperm/sub noread; do
    case "$d" in /*) mkdir -p "$d" ;; *) mkdir -p "$ROOT/$d" ;; esac
done
for i in 0 1 2 3 4 5 6 7 8 9; do mkdir -p "$ROOT/sep$i"; done
mkdir -p "$ROOT/dirmark/CLAUDE.md" "$T/fakebin" "$T/shadow" "$T/wa/WindowsApps" "$T/realbin"
# A case-insensitive scratch for the exact-on-disk-name case, if the apex has one.
if [ -d "$APEX/.state/tmp" ] && CI=$(mktemp -d -p "$APEX/.state/tmp" 2>/dev/null); then
    : > "$CI/CaseProbe"
    [ -e "$CI/caseprobe" ] || { rm -rf "$CI"; CI=; }
fi

# fx <path> <content with \n \r \xNN \N{NAME} escapes> [raw]  — exact bytes, no newline added
cat > "$T/esc.py" <<'PYEOF'
import re
def unesc(v):
    v = v.encode("latin-1", "backslashreplace").decode("unicode_escape")
    return re.sub(r"<U\+([0-9A-Fa-f]{4,6})>", lambda m: chr(int(m.group(1), 16)), v)
PYEOF
cat > "$T/fx.py" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[0].rsplit("/", 1)[0])
from esc import unesc
data = unesc(sys.argv[2])
if len(sys.argv) > 3 and sys.argv[3] == "raw":
    open(sys.argv[1], "wb").write(data.encode("latin-1"))
else:
    open(sys.argv[1], "w", encoding="utf-8", newline="").write(data)
PYEOF
# j <tool> <path> [key=escaped-value ...] -> hook JSON as raw UTF-8.
#   replace_all=true|false becomes a bool; a tool written "@Write" puts file_path
#   at the top level instead of in tool_input; NotebookEdit uses notebook_path.
#   The path takes <U+XXXX> tokens too; lone surrogates go out as JSON \u escapes.
cat > "$T/j.py" <<'PYEOF'
import json, re, sys
sys.path.insert(0, sys.argv[0].rsplit("/", 1)[0])
from esc import unesc
tool, path, *kv = sys.argv[1:]
top = tool.startswith("@")
tool = tool.lstrip("@")
path = re.sub(r"<U\+([0-9A-Fa-f]{4,6})>", lambda m: chr(int(m.group(1), 16)), path)
ti = {("notebook_path" if tool == "NotebookEdit" else "file_path"): path}
extra = {}                             # "@key=value" goes to the top level (e.g. @cwd=...)
for item in kv:
    k, _, v = item.partition("=")
    if k.startswith("@"):
        extra[k[1:]] = unesc(v)
        continue
    ti[k] = {"true": True, "false": False}.get(v, v) if k == "replace_all" else unesc(v)
doc = {"tool_name": tool, **ti} if top else {"tool_name": tool, "tool_input": ti}
doc.update(extra)
sys.stdout.buffer.write(json.dumps(doc, ensure_ascii=False).encode("utf-8", "backslashreplace"))
PYEOF
fx() { "$PY" "$T/fx.py" "$@" || { echo "HARNESS: fixture $1 failed"; exit 99; }; }
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
fx "$FF/CLAUDE.md" '---\nroot: true\nname: F\n---\n\nBody.\n'
fx "$ROOT/movedash/CLAUDE.md" '---\nroot: true\ncodex: ^/^/.codex\nname: Cost --- Benefit\n---\nbody\n'
fx "$ROOT/swap/CLAUDE.md" '---\nname: Real\n  name: Shadow\nroot: true\n---\nbody\n'
fx "$ROOT/mover/CLAUDE.md" '---\nroot: true\nname: Mover\ncodex: x\n---\nbody\n'
fx "$ROOT/quotedkey/CLAUDE.md" '---\nroot: true\n"orchestrator": false\n---\nbody\n'
fx "$ROOT/recased/CLAUDE.md" '---\nroot: true\nName: Human\n---\nbody\n'
fx "$ROOT/bombody/CLAUDE.md" '---\nroot: true\nname: B\n---\nbody \N{ZERO WIDTH NO-BREAK SPACE}text\n'
fx "$ROOT/wo/CLAUDE.md" '---\nroot: true\nname: W\n---\nbody\n'
fx "$ROOT/noperm/sub/CLAUDE.md" '---\nroot: true\nname: P\n---\nbody\n'
fx "$ROOT/noread/CLAUDE.md" '---\nroot: true\nname: R\n---\nbody\n'
mkdir -p "$T/wa2/WindowsApps"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$PY" > "$T/wa2/WindowsApps/python3"; chmod +x "$T/wa2/WindowsApps/python3"
"$PY" -c 'import sys; open(sys.argv[1],"w",encoding="utf-8",newline="").write("---\nname: Pad\ndescription: " + "x"*65600 + "\n---\nChild body.\n")' "$ROOT/scancap/CLAUDE.md"
SEPS=('\r' '\x0b' '\x0c' '\x1c' '\x1d' '\x1e' '\x85' '\N{LINE SEPARATOR}' '\N{PARAGRAPH SEPARATOR}' '\N{ZERO WIDTH NO-BREAK SPACE}')
for i in 0 1 2 3 4 5 6 7 8 9; do
    fx "$ROOT/sep$i/CLAUDE.md" '---\nname: Foo\ndescription: notes'"${SEPS[$i]}"'---\nroot: true\ncodex: ^/^/.codex\n---\n# Body\n'
done
[ -n "$CI" ] && { mkdir -p "$CI/proj"; fx "$CI/proj/CLAUDE.md" '---\nroot: true\nname: CI\n---\nbody\n'; }
UNPRIV=1; [ "$(id -u 2>/dev/null)" = 0 ] && UNPRIV=0   # root reads/stats through any mode
"$PY" -c 'import sys; h="---\nroot: true\nname: N\n---\n\n"; open(sys.argv[1],"w",encoding="utf-8",newline="").write(h + "b"*(1048576 - 5 - len(h)) + "\n")' "$ROOT/near/CLAUDE.md"
ln "$ROOT/CLAUDE.md" "$ROOT/alias.md"            # hardlink, not a symlink
HAVE_FIFO=0
if [ "$IS_NT" = 0 ] && command -v mkfifo >/dev/null 2>&1 && mkfifo "$ROOT/fifo/CLAUDE.md" 2>/dev/null \
   && [ -p "$ROOT/fifo/CLAUDE.md" ]; then HAVE_FIFO=1; fi   # MSYS mkfifo makes a .lnk, not a FIFO
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
    if [ -z "$3" ]; then   # j.py failed: an empty payload would "block" vacuously
        printf 'FAIL  %-62s empty payload (harness error)\n' "$1"; FAIL=$((FAIL+1)); return
    fi
    out=$(printf '%s' "$3" | CLAUDE_PROJECT_DIR="${4-$ROOT}" ${TO:+"$TO" 20} bash "$GUARD" 2>&1); rc=$?
    record "$1" "$2" "$rc" "$out"
}
skip() { printf 'SKIP  %s\n' "$1"; }
recrc() {  # <desc> <expect> <rc> — for cases with no stderr to read
    if [ "$3" = "$2" ]; then printf 'PASS  %-62s rc=%s\n' "$1" "$3"; PASS=$((PASS+1))
    else printf 'FAIL  %-62s expected %s, got %s\n' "$1" "$2" "$3"; FAIL=$((FAIL+1)); fi
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

check "non-ASCII folder: name: edit"                                0 "$(j Edit "$NA/CLAUDE.md" old_string='name: cafe' new_string='name: caf\xe9')"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | PATH="$T/wa/WindowsApps:$T/realbin:/usr/bin:/bin" CLAUDE_PROJECT_DIR="$ROOT" bash "$GUARD" 2>&1); rc=$?
record "Windows Store python3 stub is skipped (name: edit)"         0 "$rc" "$out"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | PATH="$T/wa2/WindowsApps" CLAUDE_PROJECT_DIR="$ROOT" "$BASH_BIN" "$GUARD" 2>&1); rc=$?
record "a working Python that only exists under WindowsApps is used" 0 "$rc" "$out"
check "move a valid name: line past a protected one"                0 "$(j Edit "$ROOT/mover/CLAUDE.md" old_string='root: true\nname: Mover\n' new_string='name: Mover\nroot: true\n')"

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
check "add a column-0 orchestrator: beside a quoted one"            2 "$(j Edit "$ROOT/quotedkey/CLAUDE.md" old_string='root: true\n' new_string='root: true\norchestrator: true\n')"
check "add a column-0 name: beside a re-cased Name:"                2 "$(j Edit "$ROOT/recased/CLAUDE.md" old_string='root: true\n' new_string='root: true\nname: Other\n')"
check "move a name: line holding --- above root:/codex:"            2 "$(j Edit "$ROOT/movedash/CLAUDE.md" old_string='root: true\ncodex: ^/^/.codex\nname: Cost --- Benefit\n' new_string='name: Cost --- Benefit\nroot: true\ncodex: ^/^/.codex\n')"
check "swap name: with its indented twin"                           2 "$(j Edit "$ROOT/swap/CLAUDE.md" old_string='name: Real\n  name: Shadow\n' new_string='  name: Shadow\nname: Real\n')"
check "frontmatter ending past 64 KiB (containment reads only that)" 2 "$(j Edit "$ROOT/scancap/CLAUDE.md" old_string='name: Pad\n' new_string='')"

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
check "BOM inside the body: name: edit refused"                     2 "$(j Edit "$ROOT/bombody/CLAUDE.md" old_string='name: B' new_string='name: C')"
for i in 0 1 2 3 4 5 6 7 8 9; do
check "separator #$i before a fence: inserting a line"               2 "$(j Edit "$ROOT/sep$i/CLAUDE.md" old_string="${SEPS[$i]}"'---\n' new_string="${SEPS[$i]}"'orchestrator: true\n---\n')"
done

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
FIRSTS=('[' ']' '{' '}' '&' '*' '!' '|' '>' '%' '@' '`')
for c in "${FIRSTS[@]}"; do
check "name: starting with $c"                                       2 "$(j Edit "$C" old_string='name: child' new_string="name: ${c}x")"
done
check "name: with a lone surrogate (Cs)"                            2 "$(j Edit "$C" old_string='name: child' new_string='name: a<U+D800>b')"
check "name: with a private-use character (Co)"                     2 "$(j Edit "$C" old_string='name: child' new_string='name: a<U+E000>b')"
check "name: with an unassigned code point (Cn)"                    2 "$(j Edit "$C" old_string='name: child' new_string='name: a<U+0378>b')"
check "result over 1 MiB (valid key added to a near-cap file)"      2 "$(j Edit "$ROOT/near/CLAUDE.md" old_string='name: N\n' new_string='name: N\norchestrator: true\n')"
"$PY" -c 'import json,sys; t=open(sys.argv[1],encoding="utf-8").read().replace("name: N\n","name: N\norchestrator: true\n",1); sys.stdout.write(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":t}}))' "$ROOT/near/CLAUDE.md" > "$T/nearw.json"
check "Write adding a key to a near-cap file (result over 1 MiB)"   2 "$(cat "$T/nearw.json")"

echo "# coverage of aliases, paths and odd files -> block"
check "hardlink alias to CLAUDE.md, body edit"                      2 "$(j Edit "$ROOT/alias.md" old_string='Root Group governs this tree.' new_string='X')"
check "backslash path to a CLAUDE.md, body edit"                    2 "$(j Edit "$ROOT"'\child\CLAUDE.md' old_string='Child body.' new_string='X')"
check "relative CLAUDE.md path anchored to CPD, body edit"          2 "$(j Edit child/CLAUDE.md old_string='Child body.' new_string='X')"
check "relative CLAUDE.md path, no CPD"                             2 "$(j Edit child/CLAUDE.md old_string='name: child' new_string='name: kid')" ""
mkdir -p "$T/empty"
check "relative path resolves against the hook cwd, not the CPD"    2 "$(j Write CLAUDE.md content='---\nroot: false\n---\nx\n' @cwd="$CHILD")" "$T/empty"
check "CLAUDE.md/. (normalised to the marker)"                      2 "$(j Edit "$C/." old_string='Child body.' new_string='X')"
check "CLAUDE.md/ (trailing slash)"                                 2 "$(j Edit "$C/" old_string='Child body.' new_string='X')"
check "CLAUDE.md. is treated as the marker (Windows alias)"         2 "$(j Edit "$C." old_string='Child body.' new_string='X')"
check "CLAUDE.md::\$DATA is treated as the marker (main stream)"    2 "$(j Edit "$CHILD"'/CLAUDE.md::$DATA' old_string='Child body.' new_string='X')"
if [ "$IS_NT" = 0 ]; then
check "Windows drive path under POSIX (would read as creation)"     2 "$(j Write 'C:/proj/CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "Windows drive path, backslashes"                             2 "$(j Write 'C:\proj\CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "lowercase drive path c:/... under POSIX"                     2 "$(j Write 'c:/proj/CLAUDE.md' content='---\nroot: false\n---\nx\n')"
else skip "drive paths under POSIX (Windows Python vets them for real)"; fi
check "device path \\\\.\\C:\\... to a CLAUDE.md"                   2 "$(j Write '\\.\C:\proj\CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "device path \\\\?\\UNC\\... to a CLAUDE.md"                  2 "$(j Write '\\?\UNC\host\share\CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "lowercase device path to claude.md"                          2 "$(j Write '\\?\UNC\host\share\claude.md' content='---\nroot: false\n---\nx\n')"
check "drive-relative C:CLAUDE.md"                                  2 "$(j Write 'C:CLAUDE.md' content='---\nroot: false\n---\nx\n')"
check "path with a lone surrogate (cannot stat it)"                 2 "$(j Write "$ROOT/fffd<U+D800>dir/CLAUDE.md" content='---\nroot: false\n---\nx\n')"
if [ "$IS_NT" = 0 ] && [ -d /proc/self ]; then
out=$(printf '%s' "$(j Write /proc/self/cwd/CLAUDE.md content='---\nroot: false\n---\nx\n')" | (cd "$T" && CLAUDE_PROJECT_DIR="$ROOT" bash "$GUARD") 2>&1); rc=$?
record "/proc/self/cwd/CLAUDE.md (resolves in the hook process)"    2 "$rc" "$out"
else skip "/proc path (no /proc here)"; fi
if [ "$UNPRIV" = 1 ]; then
chmod 0200 "$ROOT/wo/CLAUDE.md"
check "unreadable CLAUDE.md (mode 0200)"                            2 "$(j Write "$ROOT/wo/CLAUDE.md" content='---\nroot: false\n---\nx\n')"
chmod 000 "$ROOT/noperm"
check "CLAUDE.md under an unsearchable folder (stat fails)"         2 "$(j Write "$ROOT/noperm/sub/CLAUDE.md" content='---\nroot: false\n---\nx\n')"
chmod 755 "$ROOT/noperm"
chmod 0311 "$ROOT/noread"
check "CLAUDE.md in a folder that cannot be listed"                 2 "$(j Edit "$ROOT/noread/CLAUDE.md" old_string='name: R' new_string='name: S')"
chmod 755 "$ROOT/noread"
else skip "permission cases (running as root)"; fi
if [ -n "$CI" ]; then
check "case-variant spelling of an existing CLAUDE.md"              2 "$(j Edit "$CI/proj/claude.md" old_string='name: CI' new_string='name: CJ')" "$CI"
else skip "exact on-disk name (no case-insensitive scratch)"; fi
check "file without frontmatter"                                    2 "$(j Edit "$ROOT/nofm/CLAUDE.md" old_string='Just a body' new_string='---\norchestrator: true\n---\nJust a body')"
check "unterminated frontmatter"                                    2 "$(j Edit "$ROOT/unterm/CLAUDE.md" old_string='name: U' new_string='name: V')"
check "non-UTF-8 CLAUDE.md"                                         2 "$(j Edit "$ROOT/bin/CLAUDE.md" old_string='root: true' new_string='root: true')"
check "CLAUDE.md is a directory"                                    2 "$(j Write "$ROOT/dirmark/CLAUDE.md" content='x')"
if [ "$HAVE_FIFO" -eq 1 ]; then
check "CLAUDE.md is a FIFO"                                         2 "$(j Write "$ROOT/fifo/CLAUDE.md" content='x')"
else echo "SKIP  CLAUDE.md is a FIFO (no mkfifo here)"; fi
check "Edit a CLAUDE.md that does not exist"                        2 "$(j Edit "$ROOT/ghost/CLAUDE.md" old_string='a' new_string='b')"
check "Write creating a new CLAUDE.md (human-only)"                 2 "$(j Write "$ROOT/newproj/CLAUDE.md" content='---\nroot: true\ncodex: /anything\n---\n\nNew body.\n')"
check "Write creating a plain-template CLAUDE.md (human-only)"      2 "$(j Write "$ROOT/newproj2/CLAUDE.md" content='---\nroot: true\nname: New\ncodex: ^/^/.codex\n---\n\nRead `.state/start.md`.\n')"
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
check "a non-UTF-8 byte in the path (strict decode, no substitution)" 2 "$(printf '{"tool_name":"Write","tool_input":{"file_path":"%s/caf\xe9/CLAUDE.md","content":"---\\nroot: false\\n---\\nx\\n"}}' "$ROOT")"
"$PY" -c 'import json,sys; sys.stdout.write(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":"---\nroot: true\nname: child\ncodex: ^/^/.codex\n---\n\n"+"B"*200000+"\n"}}))' "$C" > "$T/big.json"
check "Write >128 KB (the old env-var handoff failed open on E2BIG)" 2 "$(cat "$T/big.json")"

echo "# interpreter failures -> block"
out=$(printf '%s' "$(j Edit "$C" old_string='Child body.' new_string='Owned.')" | (cd "$T/shadow" && CLAUDE_PROJECT_DIR="$ROOT" bash "$GUARD") 2>&1); rc=$?
record "json.py planted in the hook's cwd (python -I)"               2 "$rc" "$out"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | env -i PATH=/nonexistent CLAUDE_PROJECT_DIR="$ROOT" "$BASH_BIN" "$GUARD" 2>&1); rc=$?
record "no python interpreter on PATH"                              2 "$rc" "$out"
out=$(printf '%s' "$(j Edit "$C" old_string='name: child' new_string='name: kid')" | PATH="$T/fakebin:$PATH" CLAUDE_PROJECT_DIR="$ROOT" bash "$GUARD" 2>&1); rc=$?
record "interpreter exits with an unexpected rc"                    2 "$rc" "$out"
j Edit "$C" old_string='Child body.' new_string='X' > "$T/pipe.json"
cat > "$T/pipe.py" <<'PYEOF'
import os, subprocess, sys
r, w = os.pipe()
os.close(r)                            # stderr goes to a pipe nobody reads
env = dict(os.environ, CLAUDE_PROJECT_DIR=sys.argv[3])
with open(sys.argv[2], "rb") as fh:
    p = subprocess.run(["bash", sys.argv[1]], stdin=fh, stdout=subprocess.DEVNULL, stderr=w, env=env)
print(p.returncode if p.returncode >= 0 else 128 - p.returncode)
PYEOF
recrc "a closed stderr still ends in a block, not rc=141"           2 "$("$PY" "$T/pipe.py" "$GUARD" "$T/pipe.json" "$ROOT")"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
