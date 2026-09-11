#!/usr/bin/env bash
# Mutation proof for test_claude_md_guard.sh. Reverts each hardening in
# claude-md-immutability-guard.sh one at a time and requires the suite to go RED.
# A green suite against a broken guard is not evidence, so this is what makes the
# suite load-bearing. Same rules as mutate_guards.sh:
#   - a SKIP (target literal no longer present) counts as a FAILURE — fix the
#     target here, never let the harness green over a mutant it never applied
#   - every mutant must PARSE — bash -n AND the embedded python must compile —
#     or it proves nothing (the rc wrapper would block everything and the suite
#     would go red for the wrong reason)
#   - the unmutated guard must pass first, or every mutant is "caught" trivially
#
# Deliberately NOT mutated (each is backed by a second control, so removing it
# alone changes no verdict — an equivalent mutant, not a coverage hole):
#   - the empty-old_string check (count("") > 1 trips the ambiguity check)
#   - the isfile() check (open() on a non-regular file raises OSError -> block)
#   - st_ino != 0 in the alias test (guards filesystems with no inode numbers;
#     none is available to test on here)
#
# Run: bash mutate_claude_md_guard.sh   (exit 0 = every mutant caught, none skipped)
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/.." && pwd)
SUITE="$HERE/test_claude_md_guard.sh"
GNAME=claude-md-immutability-guard.sh
PY=$(command -v python3 || command -v python)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
BAD=0; SKIPPED=0; N=0

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
_, a, rest = s.partition("-I -c '")
body, b, _ = rest.partition("'\nrc=$?")
if not (a and b):
    sys.exit(1)
compile(body, "guard", "exec")
PYEOF

fresh() { rm -rf "$W/h"; mkdir -p "$W/h"; cp "$SRC/$GNAME" "$W/h/"; }

fresh
if ! GUARD_DIR="$W/h" bash "$SUITE" >/dev/null 2>&1; then
    echo "BASELINE RED: the suite fails against the unmutated guard — fix that first."
    exit 1
fi

mutate() {  # <name> <old> <new> [<old> <new> ...]
    local name=$1; shift
    N=$((N+1)); fresh
    if ! "$PY" "$W/mutate.py" "$W/h/$GNAME" "$@"; then
        printf 'SKIP   %-52s <-- TARGET ABSENT (drifted — counts as failure)\n' "$name"
        SKIPPED=$((SKIPPED+1)); return
    fi
    if ! bash -n "$W/h/$GNAME" 2>/dev/null || ! "$PY" "$W/parses.py" "$W/h/$GNAME" 2>/dev/null; then
        printf 'BADMUT %-52s <-- MUTANT DOES NOT PARSE (proves nothing)\n' "$name"; BAD=$((BAD+1)); return
    fi
    if GUARD_DIR="$W/h" bash "$SUITE" >/dev/null 2>&1; then
        printf 'GREEN  %-52s <-- MUTANT SURVIVED\n' "$name"; BAD=$((BAD+1))
    else
        printf 'RED    %-52s caught\n' "$name"
    fi
}

X='sys.exit(0) or '   # prefix that turns a die(...) into an allow

# --- which files are covered
mutate "name match is case-sensitive"            'if base.casefold() != "claude.md":' 'if base != "CLAUDE.md":'
mutate "hardlink/short-name alias ignored"       'return a.st_ino != 0 and (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)' 'return False'
mutate "relative path without CPD allowed"       'die("BLOCKED: relative CLAUDE.md path' "${X}"'die("BLOCKED: relative CLAUDE.md path'
# --- judged by result
mutate "skeleton comparison skipped"             'if new_sk != old_sk:' 'if False:'
mutate "any Write treated as creation"           'if not os.path.lexists(p):' 'if tool == "Write" or not os.path.lexists(p):'
mutate "non-Write/Edit tool allowed"             'if tool not in ("Write", "Edit"):' 'if False:'
mutate "fuzzy (non-verbatim) old_string allowed" 'die("BLOCKED: old_string does not occur verbatim' "${X}"'die("BLOCKED: old_string does not occur verbatim'
mutate "ambiguous old_string allowed"            'if count > 1 and not ra:' 'if False:'
mutate "read cap ignored"                        'if len(raw) > MAX_BYTES:' 'if False:'
# --- the allowlist and its values
mutate "allowlist widened to root:/codex:"       'ALLOWED = ("name", "orchestrator")' 'ALLOWED = ("name", "orchestrator", "root", "codex")' \
                                                 '"orchestrator": re.compile(' '"root": re.compile(r".*"), "codex": re.compile(r".*"), "orchestrator": re.compile('
mutate "value validation skipped"                'if old_keys.get(k) != v and not valid(k, v):' 'if False:'
mutate "duplicate key allowed"                   'if m.group(1) in keys:' 'if False:'
mutate "control/format chars allowed"            'if any(unicodedata.category(c) in BAD_CATEGORIES and c != chr(9) for c in val):' 'if False:'
mutate "name: first-char restriction dropped"    '[^ \t\[\]{}&*!|>%@`]' '\S'
mutate "name: length cap dropped"                '.{0,199}' '.*'
mutate "orchestrator: any value"                 'r"[ \t]*(true|false)[ \t]*"' 'r".*"'
# --- frontmatter parsing
mutate "lines split on \\n only (U+2028 hides)"  'lines = text.splitlines(True)' 'lines = re.split(r"(?<=\n)", text)'
mutate "only an exact --- closes frontmatter"    'if lines[i].startswith("---"):' 'if lines[i].rstrip() == "---":'
mutate "BOM dropped from the skeleton"           'kept, keys = [bom, lines[0]], {}' 'kept, keys = [lines[0]], {}'
mutate "no frontmatter treated as editable"      'die("BLOCKED: " + which + " CLAUDE.md has no leading' "${X}"'die("BLOCKED: " + which + " CLAUDE.md has no leading'
mutate "unterminated frontmatter allowed"        'die("BLOCKED: " + which + " CLAUDE.md frontmatter is unterminated' "${X}"'die("BLOCKED: " + which + " CLAUDE.md frontmatter is unterminated'
# --- fail closed on unvettable input
mutate "undecodable JSON allowed"                'die("BLOCKED: tool input is not decodable JSON' "${X}"'die("BLOCKED: tool input is not decodable JSON'
mutate "non-object JSON allowed"                 'die("BLOCKED: tool input is not a JSON object' "${X}"'die("BLOCKED: tool input is not a JSON object'
mutate "non-string path allowed"                 'die("BLOCKED: file_path/notebook_path is present' "${X}"'die("BLOCKED: file_path/notebook_path is present'
mutate "Edit of a missing CLAUDE.md allowed"     'die("BLOCKED: Edit targets a CLAUDE.md that does not exist' "${X}"'die("BLOCKED: Edit targets a CLAUDE.md that does not exist'
mutate "non-UTF-8 CLAUDE.md allowed"             'die("BLOCKED: CLAUDE.md is not valid UTF-8' "${X}"'die("BLOCKED: CLAUDE.md is not valid UTF-8'
mutate "Write without content allowed"           'die("BLOCKED: Write content is missing' "${X}"'die("BLOCKED: Write content is missing'
mutate "malformed Edit parameters allowed"       'die("BLOCKED: Edit parameters are missing' "${X}"'die("BLOCKED: Edit parameters are missing'
mutate "missing interpreter allowed"             $'(fail closed)." >&2\n    exit 2' $'(fail closed)." >&2\n    exit 0'
mutate "rc wrapper fails open"                   $'fail closed." >&2\nexit 2' $'fail closed." >&2\nexit 0'

echo
echo "$N mutants: $BAD survived or unparseable, $SKIPPED skipped"
[ "$BAD" -eq 0 ] && [ "$SKIPPED" -eq 0 ]
