#!/usr/bin/env bash
# Mutation proof for test_claude_md_guard.sh. Reverts each hardening in
# claude-md-immutability-guard.sh one at a time and requires the suite to go RED.
# A green suite against a broken guard is not evidence, so this is what makes the
# suite load-bearing. Same rules as mutate_guards.sh:
#   - a SKIP (target literal absent or not unique) counts as a FAILURE — fix the
#     target here, never let the harness green over a mutant it never applied
#   - every mutant must PARSE — bash -n AND the embedded python must compile —
#     or it proves nothing (the rc wrapper would block everything and the suite
#     would go red for the wrong reason)
#   - the unmutated guard must pass first, or every mutant is "caught" trivially
#
# Deliberately NOT mutated — removing any one of these alone changes no verdict
# the suite can observe on this platform (each was checked by hand):
#   - st_ino != 0 in the alias test: only matters on a filesystem with no inode
#     numbers, where it prevents over-blocking; none is available to test on.
#   - lstat (not stat) in the alias test: only a symlink could tell them apart,
#     and creating one is human-only (ABSOLUTE HOLD).
#   - the refusal of a CR/BOM/non-LF break in the RESULT: while the whole-file
#     refusal stands, every such result is also caught by the skeleton comparison
#     or the value grammar (Cc/Zl/Zp) — a 300-case fuzz found no difference.
#   - "---" barred inside a value: a value containing --- makes its own line the
#     first --- line, which the fence rule already refuses.
#   - the backslash-ambiguity refusal on its own: with backslashes kept literal on
#     POSIX (as Claude Code keeps them) the guard already vets the file the tool
#     writes; the refusal is a second layer. The combined mutant above is caught.
#   - which stat error counts as "absent": creation is refused too, so an absent
#     target and an unstatable one both block.
#   - -X utf8: identical to the default on a UTF-8 host; it matters under a legacy
#     locale or Windows code page, neither available here.
#   - Windows-only branches: fs() (the literal \\?\ form), ntpath normalisation,
#     the "D:" -> "D:/" folder fix, backslash translation, the path-length cap —
#     unreachable under a POSIX interpreter; exercised by the Windows-native lens.
#   - the size pre-check before building an Edit result: the byte-size check on
#     the built result gives the same verdict; it only saves building a huge string.
#   - the timeouts on the interpreter probe and run: proving them needs a hanging
#     interpreter, which would add minutes per mutant.
# Environment-dependent (reported as ENV, not counted, when the suite skipped the
# case that proves it): the FIFO case (isfile), the permission cases (stat,
# listdir, read), the exact-on-disk-name case (needs a case-insensitive scratch).
#
# Run: bash mutate_claude_md_guard.sh   (exit 0 = every mutant caught, none skipped)
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/.." && pwd)
SUITE="$HERE/test_claude_md_guard.sh"
GNAME=claude-md-immutability-guard.sh
PY=$(command -v python3 || command -v python)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
BAD=0; SKIPPED=0; ENV=0; N=0

cat > "$W/mutate.py" <<'PYEOF'
import sys
p, pairs = sys.argv[1], sys.argv[2:]
s = open(p, encoding="utf-8").read()
for old, new in zip(pairs[0::2], pairs[1::2]):
    if s.count(old) != 1:
        sys.stderr.write("MUTATION TARGET NOT UNIQUE/ABSENT (%d): %r\n" % (s.count(old), old))
        sys.exit(9)
    s = s.replace(old, new)
open(p, "w", encoding="utf-8").write(s)
PYEOF

cat > "$W/parses.py" <<'PYEOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
_, a, rest = s.partition(" -c '")
body, b, _ = rest.partition("'\nrc=$?")
if not (a and b):
    sys.exit(1)
compile(body, "guard", "exec")
PYEOF

fresh() { rm -rf "$W/h"; mkdir -p "$W/h"; cp "$SRC/$GNAME" "$W/h/"; }

fresh
BASE_OUT=$(GUARD_DIR="$W/h" bash "$SUITE" 2>&1)
if [ $? -ne 0 ]; then
    echo "BASELINE RED: the suite fails against the unmutated guard — fix that first."
    printf '%s\n' "$BASE_OUT" | grep -E '^FAIL' | head
    exit 1
fi
skipped_case() { printf '%s\n' "$BASE_OUT" | grep -q "^SKIP  $1"; }

mutate() {  # <name> <old> <new> [<old> <new> ...]
    local name=$1; shift
    N=$((N+1)); fresh
    if ! "$PY" "$W/mutate.py" "$W/h/$GNAME" "$@"; then
        printf 'SKIP   %-56s <-- TARGET ABSENT (drifted — counts as failure)\n' "$name"
        SKIPPED=$((SKIPPED+1)); return
    fi
    if ! bash -n "$W/h/$GNAME" 2>/dev/null || ! "$PY" "$W/parses.py" "$W/h/$GNAME" 2>/dev/null; then
        printf 'BADMUT %-56s <-- MUTANT DOES NOT PARSE (proves nothing)\n' "$name"; BAD=$((BAD+1)); return
    fi
    if GUARD_DIR="$W/h" bash "$SUITE" >/dev/null 2>&1; then
        printf 'GREEN  %-56s <-- MUTANT SURVIVED\n' "$name"; BAD=$((BAD+1))
    else
        printf 'RED    %-56s caught\n' "$name"
    fi
}
mutate_env() {  # <skip-prefix> <name> <old> <new> — only meaningful where the suite ran that case
    local pre=$1; shift
    if skipped_case "$pre"; then
        printf 'ENV    %-56s (suite skipped: %s)\n' "$1" "$pre"; ENV=$((ENV+1)); return
    fi
    mutate "$@"
}

X='sys.exit(0) or '   # prefix that turns a die(...) into an allow

# --- which files are covered, and how the path is read
mutate "name match is case-sensitive"            'return b.rstrip(". ").casefold() == "claude.md"' 'return b.rstrip(". ") == "CLAUDE.md"'
mutate "trailing dot/space alias not normalised" 'return b.rstrip(". ").casefold() == "claude.md"' 'return b.casefold() == "claude.md"'
mutate "stream suffix alias not normalised"      'b = b.split(":", 1)[0]' 'b = b'
mutate "drive-relative prefix kept in the name"  $'    if DRIVE_RELATIVE.match(b):\n        b = b[2:]\n' ''
mutate "invisible characters kept in the name"   'b = "".join(c for c in b if unicodedata.category(c) != "Cf")' 'b = b'
mutate "hardlink alias ignored"                  'return a.st_ino != 0 and (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)' 'return False'
mutate "notebook_path not decoded"               'for key in ("file_path", "notebook_path"):' 'for key in ("file_path",):'
mutate "top-level file_path not decoded"         'for src in (ti, doc):' 'for src in (ti,):'
mutate "POSIX backslash read as a separator"     'if not WIN and BS in target:' 'if False:' 'raw = target.replace(BS, "/") if WIN else target' 'raw = target.replace(BS, "/")'
mutate "relative path anchored to CPD, not cwd"  'anchor = doc.get("cwd")' 'anchor = None'
mutate "no CLAUDE_PROJECT_DIR fallback"          'anchor = os.environ.get("CLAUDE_PROJECT_DIR") or ""' 'anchor = ""'
mutate "drive-relative path joined to the cwd"   'if not (p.startswith("/") or DRIVE.match(p) or DRIVE_RELATIVE.match(p)):' 'if not (p.startswith("/") or DRIVE.match(p)):'
mutate "POSIX // not collapsed"                  'p = "/" + p.lstrip("/")        # POSIX: // is /' 'pass'
mutate "path not normalised (CLAUDE.md/.)"       'p = posixpath.normpath(p)' 'pass'
mutate "relative/drive-relative path allowed"    'die("BLOCKED: a relative or drive-relative CLAUDE.md path' "${X}"'die("BLOCKED: a relative or drive-relative CLAUDE.md path'
mutate "device-namespace path allowed"           'if device:' 'if False:'
mutate "drive path under POSIX allowed"          'if DRIVE.match(p) and not WIN:' 'if False:'
mutate "lowercase drive letter not recognised"   'DRIVE = re.compile(r"^[A-Za-z]:/")' 'DRIVE = re.compile(r"^[A-Z]:/")'
mutate "/proc path allowed"                      'if not WIN and (p == "/proc" or p.startswith("/proc/") or p.startswith("/dev/fd/")):' 'if False:'
mutate "/dev/fd path allowed"                    'if not WIN and (p == "/proc" or p.startswith("/proc/") or p.startswith("/dev/fd/")):' 'if not WIN and (p == "/proc" or p.startswith("/proc/")):'
mutate "auto-memory CLAUDE.md allowed"           'if "/.state/memory/" in "/" + p.casefold():' 'if False:'
mutate_env "exact on-disk name" "case-variant spelling allowed" 'if base not in names:' 'if False:'
mutate_env "unlistable folder" "unlistable folder allowed" 'die("BLOCKED: cannot list the directory' "${X}"'die("BLOCKED: cannot list the directory'
mutate_env "unsearchable folder" "unstatable target allowed" 'die("BLOCKED: cannot stat the CLAUDE.md target' "${X}"'die("BLOCKED: cannot stat the CLAUDE.md target'
# --- judged by result
mutate "skeleton comparison skipped"             'if new_sk != old_sk:' 'if False:'
mutate "body left out of the comparison"         'kept.extend(lines[close:])' 'pass'
mutate "creating a CLAUDE.md allowed"            'die("BLOCKED: creating a CLAUDE.md is human-only' "${X}"'die("BLOCKED: creating a CLAUDE.md is human-only'
mutate "non-Write/Edit tool allowed"             'if tool not in ("Write", "Edit"):' 'if False:'
mutate "fuzzy (non-verbatim) old_string allowed" 'die("BLOCKED: old_string does not occur verbatim' "${X}"'die("BLOCKED: old_string does not occur verbatim'
mutate "empty old_string allowed"                'die("BLOCKED: an Edit to CLAUDE.md needs a non-empty' "${X}"'die("BLOCKED: an Edit to CLAUDE.md needs a non-empty'
mutate "ambiguous old_string allowed"            'if count > 1 and not ra:' 'if False:'
mutate "tool line-break deletion not modelled"   'if n == "" and not o.endswith(NL) and (o + NL) in old:' 'if False:'
mutate "read cap ignored"                        'if len(raw_bytes) > MAX_BYTES:' 'if False:'
mutate "result size cap ignored"                 'if len(new.encode("utf-8", "surrogatepass")) > MAX_BYTES:' 'if False:'
mutate "frontmatter scan cap ignored"            'if len("".join(lines[:close + 1]).encode("utf-8", "surrogatepass")) > SCAN_CAP:' 'if False:'
mutate "CR/BOM/non-LF file accepted"             'if UNVETTABLE_RE.search(old):' 'if False:'
T10='(13, 11, 12, 28, 29, 30, 133, 8232, 8233, 65279)'
for c in 13 11 12 28 29 30 133 8232 8233 65279; do
    mutate "refusal list without chr($c)" "$T10" "$("$PY" -c 'import sys; t=[int(x) for x in sys.argv[1].strip("()").split(",")]; t.remove(int(sys.argv[2])); print("(" + ", ".join(map(str, t)) + ")")' "$T10" "$c")"
done
# --- where the frontmatter block ends
mutate "block ends at a line starting with ---"  'if "---" in lines[i]:          # Claude Code ends the block at the first --- anywhere' 'if lines[i].startswith("---"):'
mutate "closing fence need not be exactly ---"   'if lines[close] != "---" + NL:' 'if False:'
mutate "no frontmatter treated as editable"      'die("BLOCKED: " + which + " CLAUDE.md has no leading' "${X}"'die("BLOCKED: " + which + " CLAUDE.md has no leading'
mutate "unterminated frontmatter allowed"        'die("BLOCKED: " + which + " CLAUDE.md frontmatter is unterminated' "${X}"'die("BLOCKED: " + which + " CLAUDE.md frontmatter is unterminated'
# --- the allowlist and its values
mutate "allowlist widened to root:/codex:"       'ALLOWED = ("name", "orchestrator")' 'ALLOWED = ("name", "orchestrator", "root", "codex")' \
                                                 '"orchestrator": re.compile(' '"root": re.compile(r".*"), "codex": re.compile(r".*"), "orchestrator": re.compile('
mutate "indented allowlisted lines accepted"     'LINE = re.compile("(" + ' 'LINE = re.compile("[ \t]*(" + '
mutate "value validation skipped"                'if k in new_keys and not valid(k, new_keys[k][0]):' 'if False:'
mutate "moved lines not re-checked (no anchor)"  'keys[m.group(1)] = (m.group(2), len(kept))' 'keys[m.group(1)] = (m.group(2), 0)'
mutate "duplicate key allowed"                   'if m.group(1) in keys:' 'if False:'
mutate "loose (indented/quoted) key ignored"     'if changed & loose:' 'if False:'
mutate "indented loose key not seen"             'lk = ln.split(":", 1)[0].strip().strip(chr(34) + chr(39)).lower() if ":" in ln else ""' 'lk = ln.split(":", 1)[0].strip(chr(34) + chr(39)).lower() if ":" in ln else ""'
mutate "re-cased loose key not seen"             'lk = ln.split(":", 1)[0].strip().strip(chr(34) + chr(39)).lower() if ":" in ln else ""' 'lk = ln.split(":", 1)[0].strip().strip(chr(34) + chr(39)) if ":" in ln else ""'
mutate "quoted loose key not seen"               'lk = ln.split(":", 1)[0].strip().strip(chr(34) + chr(39)).lower() if ":" in ln else ""' 'lk = ln.split(":", 1)[0].strip().lower() if ":" in ln else ""'
mutate "control/format chars allowed"            'if any(unicodedata.category(c) in BAD_CATEGORIES and c != chr(9) for c in val):' 'if False:'
mutate "Cs/Co/Cn allowed"                        'BAD_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")' 'BAD_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")'
mutate "name: first-char restriction dropped"    '[^ \t\[\]{}&*!|>%@`]' '\S'
mutate "name: may start with *"                  '[^ \t\[\]{}&*!|>%@`]' '[^ \t\[\]{}&!|>%@`]'
mutate "name: may start with |"                  '[^ \t\[\]{}&*!|>%@`]' '[^ \t\[\]{}&*!>%@`]'
mutate "name: may start with a backtick"         '[^ \t\[\]{}&*!|>%@`]' '[^ \t\[\]{}&*!|>%@]'
mutate "name: length cap dropped"                '.{0,199}' '.*'
mutate "name: leading blanks unbounded"          '"name": re.compile(r"[ \t]{1,8}' '"name": re.compile(r"[ \t]+'
mutate "orchestrator: any value"                 'r"[ \t]{1,8}(true|false)[ \t]{0,8}"' 'r".*"'
mutate "orchestrator: case-insensitive"          'r"[ \t]{1,8}(true|false)[ \t]{0,8}"),' 'r"[ \t]{1,8}(true|false)[ \t]{0,8}", re.I),'
mutate "orchestrator: blanks unbounded"          'r"[ \t]{1,8}(true|false)[ \t]{0,8}"' 'r"[ \t]*(true|false)[ \t]*"'
# --- fail closed on unvettable input
mutate "stdin decoded leniently"                 'doc = json.loads(sys.stdin.buffer.read().decode("utf-8"))' 'doc = json.loads(sys.stdin.read())'
mutate "undecodable JSON allowed"                'die("BLOCKED: tool input is not decodable JSON' "${X}"'die("BLOCKED: tool input is not decodable JSON'
mutate "non-object JSON allowed"                 'die("BLOCKED: tool input is not a JSON object' "${X}"'die("BLOCKED: tool input is not a JSON object'
mutate "non-string path allowed"                 'die("BLOCKED: file_path/notebook_path is present' "${X}"'die("BLOCKED: file_path/notebook_path is present'
mutate "Edit of a missing CLAUDE.md allowed"     'die("BLOCKED: Edit targets a CLAUDE.md that does not exist' "${X}"'die("BLOCKED: Edit targets a CLAUDE.md that does not exist'
mutate_env "CLAUDE.md is a FIFO" "non-regular file read (FIFO hangs)" 'if not os.path.isfile(fs(p)):' 'if False:'
mutate_env "unreadable CLAUDE.md" "unreadable CLAUDE.md allowed" 'die("BLOCKED: cannot read CLAUDE.md' "${X}"'die("BLOCKED: cannot read CLAUDE.md'
mutate "non-UTF-8 CLAUDE.md allowed"             'die("BLOCKED: CLAUDE.md is not valid UTF-8' "${X}"'die("BLOCKED: CLAUDE.md is not valid UTF-8'
mutate "Write without content allowed"           'die("BLOCKED: Write content is missing' "${X}"'die("BLOCKED: Write content is missing'
mutate "malformed Edit parameters allowed"       'die("BLOCKED: Edit parameters are missing' "${X}"'die("BLOCKED: Edit parameters are missing'
# --- the interpreter and the wrapper
mutate "python -I dropped (planted json.py)"     '"$GUARD_PY" $GUARD_PY_PRE -I -X utf8 -c' '"$GUARD_PY" $GUARD_PY_PRE -X utf8 -c'
mutate "relative PATH candidate used"            '    case "$c" in /*) ;; *) continue ;; esac   # a relative PATH entry would resolve inside the project' ''
mutate "WindowsApps candidate not probed (stub)" '${TO:+"$TO" 10} "$c" -I -c "" >/dev/null 2>&1 </dev/null || continue ;;' ': ;;'
mutate "WindowsApps candidate always skipped"    '${TO:+"$TO" 10} "$c" -I -c "" >/dev/null 2>&1 </dev/null || continue ;;' 'continue ;;'
mutate "no py launcher fallback"                 'if [ -z "$GUARD_PY" ] && c=$(command -v py 2>/dev/null)' 'if false && c=$(command -v py 2>/dev/null)'
mutate "SIGPIPE not ignored (closed stderr)"     "trap '' PIPE    # a closed stderr" ": trap '' PIPE    # a closed stderr"
mutate "missing interpreter allowed"             $'(fail closed)." >&2\n    exit 2' $'(fail closed)." >&2\n    exit 0'
mutate "rc wrapper fails open"                   $'fail closed." >&2\nexit 2' $'fail closed." >&2\nexit 0'

echo
echo "$N mutants: $BAD survived or unparseable, $SKIPPED skipped, $ENV not applicable here"
[ "$BAD" -eq 0 ] && [ "$SKIPPED" -eq 0 ]
