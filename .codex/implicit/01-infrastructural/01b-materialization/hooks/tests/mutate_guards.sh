#!/usr/bin/env bash
# Mutation proof for the two guard suites. Reverts each hardening one at a time
# and requires the suites to go RED. A green suite against a broken guard is not
# evidence of anything, so this is what makes the other two files load-bearing.
#
# Mutations are applied to the SHARED guard-core, so they land in both guards at
# once — a survivor is a real coverage hole, not a drift artifact.
#
# Run: bash mutate_guards.sh   (exit 0 = every mutant caught)
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/.." && pwd)
SUITES="$HERE/test_guard_extraction.sh $HERE/test_guards_walkup.sh $HERE/test_guards_identical.sh"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
MUT="$W/mutate.py"
BAD=0

cat > "$MUT" <<'PYEOF'
import sys
p, pairs = sys.argv[1], sys.argv[2:]
s = open(p, encoding="utf-8").read()
for old, new in zip(pairs[0::2], pairs[1::2]):
    if old not in s:
        sys.stderr.write("MUTATION TARGET ABSENT: %r\n" % (old,))
        sys.exit(9)
    s = s.replace(old, new)
open(p, "w", encoding="utf-8").write(s)
PYEOF

run_suites() {  # <guard-dir> -> 0 if ALL suites green
    local d=$1 s
    for s in $SUITES; do
        GUARD_DIR="$d" bash "$s" >/dev/null 2>&1 || return 1
    done
    return 0
}

mutate() {  # <name> <old> <new> [<old> <new> ...] -- applied together
    local name=$1; shift
    local g
    rm -rf "$W/h"; mkdir -p "$W/h"; cp "$SRC"/*.sh "$W/h/"
    for g in "$W/h/containment-guard.sh" "$W/h/gravity-guard.sh"; do
        if ! python3 "$MUT" "$g" "$@" 2>/dev/null; then
            printf 'SKIP  %-48s (mutation target absent)\n' "$name"; return
        fi
    done
    if run_suites "$W/h"; then
        printf 'GREEN %-48s <-- MUTANT SURVIVED\n' "$name"; BAD=$((BAD+1))
    else
        printf 'RED   %-48s caught\n' "$name"
    fi
}

echo "== control: the unmutated tree must be green =="
if run_suites "$SRC"; then echo "GREEN control (correct)"
else echo "control is RED — fix the suites before trusting any mutant"; exit 1; fi
echo

# lexical() and physical() overlap: both collapse "..", so for a plain
# traversal either one alone still blocks. They are kept as redundant controls
# because physical() returns None on an OSError, leaving lexical() as the only
# check. M1 and M1b prove each half is covered on its own.
mutate "M1  lexical norm off" \
       "    return posixpath.normpath(p)" "    return p"
mutate "M1b lexical AND physical both off" \
       "    return posixpath.normpath(p)" "    return p" \
       "    if tgt_phys and root_phys:"   "    if False:"
mutate "M2  no BOM strip"                     ".lstrip(chr(65279))" ""
mutate "M3  only bare lowercase true"         'TRUE_WORDS = ("true", "yes", "on")' 'TRUE_WORDS = ("true",)'
mutate "M4  lexists -> exists (follows link)" "os.path.lexists(cm)" "os.path.exists(cm)"
mutate "M5  unterminated block read as non-root" \
       "        return None                    # unterminated" \
       "        return False                   # unterminated"
mutate "M6  symlink-resolved second view off" "    if tgt_phys and root_phys:" "    if False:"
mutate "M7  non-string path allowed"          "    if badtype:" "    if False:"
mutate "M8  missing python allows"            "    exit 2
fi" "    exit 0
fi"
mutate "M9  no trailing-slash strip"          'child.startswith(parent.rstrip("/") + "/")' 'child.startswith(parent + "/")'
mutate "M10 undecidable marker walked past"   "    if state is not False:" "    if state is True:"
mutate "M11 empty CLAUDE_PROJECT_DIR allowed" "if not cpd.strip():" "if False:"
mutate "M12 grep-style extraction (no JSON decode)" \
       "    doc = json.load(sys.stdin)" \
       "    doc = json.loads(re.sub(r'(?s)\\\\\\\\.', '', sys.stdin.read()))"
mutate "M13 gravity checks the RAW path only" \
       "    if not (touches_state(tgt_lex) or touches_state(physical(target))):" \
       "    if not touches_state(target):"
# M14 is different in kind: it edits ONE guard only. That is the drift the old
# docs called impossible, and it must be caught by test_guards_identical.sh.
mutate_one() {  # <name> <guard-basename> <old> <new>
    local name=$1 which=$2; shift 2
    rm -rf "$W/h"; mkdir -p "$W/h"; cp "$SRC"/*.sh "$W/h/"
    if ! python3 "$MUT" "$W/h/$which" "$@" 2>/dev/null; then
        printf 'SKIP  %-48s (mutation target absent)\n' "$name"; return
    fi
    if run_suites "$W/h"; then
        printf 'GREEN %-48s <-- MUTANT SURVIVED\n' "$name"; BAD=$((BAD+1))
    else
        printf 'RED   %-48s caught\n' "$name"
    fi
}
mutate_one "M14 single-guard drift (containment only)" containment-guard.sh \
       "    if state is not False:" "    if state is True:"
mutate_one "M15 single-guard drift (gravity only)" gravity-guard.sh \
       "os.path.lexists(cm)" "os.path.exists(cm)"

echo
echo "-------------------------------------------"
if [ "$BAD" -eq 0 ]; then echo "ALL MUTANTS CAUGHT"; exit 0; fi
echo "$BAD mutant(s) survived — the suites do not prove what they claim"; exit 1
