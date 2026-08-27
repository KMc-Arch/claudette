#!/usr/bin/env bash
# Mutation proof for the two guard suites. Reverts each hardening one at a time
# and requires the suites to go RED. A green suite against a broken guard is not
# evidence of anything, so this is what makes the other two files load-bearing.
#
# Mutations are applied to the SHARED guard-core, so they land in both guards at
# once — a survivor is a real coverage hole, not a drift artifact.
#
# A SKIP (mutation target string no longer present) counts as a FAILURE, not a
# pass: these targets are whitespace- and comment-sensitive literals inside the
# guard, so a reword silently retires a control. If a target drifts, fix the
# target here — never let the harness green over a mutant it never applied.
#
# Every mutant must first PARSE (`bash -n`): a mutant that is merely a syntax
# error proves nothing (the guard never runs, every ALLOW flips to a block, the
# suites go red for the wrong reason). validate_parses() enforces that.
#
# Run: bash mutate_guards.sh   (exit 0 = every mutant caught, none skipped)
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/.." && pwd)
SUITES="$HERE/test_guard_extraction.sh $HERE/test_guards_walkup.sh $HERE/test_guards_identical.sh"
PY=$(command -v python3 || command -v python)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
MUT="$W/mutate.py"
BAD=0; SKIPPED=0

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

# A guard that is only a SYNTAX ERROR proves nothing — the suites go red because
# nothing runs. Every mutant must parse; a mutant that does not is a harness bug.
parses() { bash -n "$W/h/containment-guard.sh" 2>/dev/null && bash -n "$W/h/gravity-guard.sh" 2>/dev/null; }

judge() {  # <name> — after $W/h has been mutated
    local name=$1
    if ! parses; then
        printf 'BADMUT %-47s <-- MUTANT IS A SYNTAX ERROR (proves nothing)\n' "$name"; BAD=$((BAD+1)); return
    fi
    if run_suites "$W/h"; then
        printf 'GREEN  %-47s <-- MUTANT SURVIVED\n' "$name"; BAD=$((BAD+1))
    else
        printf 'RED    %-47s caught\n' "$name"
    fi
}

mutate() {  # <name> <old> <new> [<old> <new> ...] -- applied to BOTH guards
    local name=$1; shift
    local g
    rm -rf "$W/h"; mkdir -p "$W/h"; cp "$SRC"/*.sh "$W/h/"
    for g in "$W/h/containment-guard.sh" "$W/h/gravity-guard.sh"; do
        if ! "$PY" "$MUT" "$g" "$@"; then
            printf 'SKIP   %-47s <-- TARGET ABSENT (drifted — counts as failure)\n' "$name"
            SKIPPED=$((SKIPPED+1)); return
        fi
    done
    judge "$name"
}

mutate_one() {  # <name> <guard-basename> <old> <new> — edits ONE guard (drift)
    local name=$1 which=$2; shift 2
    rm -rf "$W/h"; mkdir -p "$W/h"; cp "$SRC"/*.sh "$W/h/"
    if ! "$PY" "$MUT" "$W/h/$which" "$@"; then
        printf 'SKIP   %-47s <-- TARGET ABSENT (drifted — counts as failure)\n' "$name"
        SKIPPED=$((SKIPPED+1)); return
    fi
    # A drift mutant is behaviourally caught by the walkup matrix AND structurally
    # by the identity check. To prove the IDENTITY check earns its keep, run it
    # alone: a single-guard edit in a region the behavioural matrix does not probe
    # must still go red here.
    if ! parses; then
        printf 'BADMUT %-47s <-- MUTANT IS A SYNTAX ERROR\n' "$name"; BAD=$((BAD+1)); return
    fi
    local ident_red=1
    GUARD_DIR="$W/h" bash "$HERE/test_guards_identical.sh" >/dev/null 2>&1 && ident_red=0
    if run_suites "$W/h"; then
        printf 'GREEN  %-47s <-- MUTANT SURVIVED\n' "$name"; BAD=$((BAD+1))
    elif [ "$ident_red" -eq 1 ]; then
        printf 'RED    %-47s caught (identity check red)\n' "$name"
    else
        printf 'RED    %-47s caught (behavioural only)\n' "$name"
    fi
}

echo "== control: the unmutated tree must be green =="
if run_suites "$SRC"; then echo "GREEN control (correct)"
else echo "control is RED — fix the suites before trusting any mutant"; exit 1; fi
echo

# The verdict is symmetric + physical-authoritative: it compares realpath(target)
# to realpath(root), falling back to the lexical view only when realpath is
# unavailable for either side. M1 proves the authoritative physical comparison is
# load-bearing; M1b proves the lexical fallback still blocks when physical is gone.
mutate "M1  physical comparison disabled (lexical-only asymmetry)" \
       "if tgt_phys is not None and root_phys is not None:" "if False:"
mutate "M1b no normalization anywhere (physical off + lexical off)" \
       "        return os.path.realpath(p)" "        return None" \
       "    return posixpath.normpath(p)" "    return p"
mutate "M2  no BOM strip"                     ".lstrip(chr(65279))" ""
mutate "M3  only bare lowercase true"         'TRUE_WORDS = ("true", "yes", "on")' 'TRUE_WORDS = ("true",)'
mutate "M4  lexists -> exists (follows link)" "os.path.lexists(cm)" "os.path.exists(cm)"
mutate "M5  unterminated block read as non-root" \
       "        return None                    # unterminated" \
       "        return False                   # unterminated"
mutate "M6  gravity .state check on lexical only (miss symlinked .state)" \
       "    if not (touches_state(tgt_lex) or touches_state(tgt_phys)):" \
       "    if not touches_state(tgt_lex):"
mutate "M7  non-string path allowed"          "    if badtype:" "    if False:"
mutate "M8  missing python allows"            "    exit 2
fi" "    exit 0
fi"
mutate "M9  no trailing-slash strip (sibling)" 'child.startswith(parent.rstrip("/") + "/")' 'child.startswith(parent.rstrip("/"))'
mutate "M10 undecidable marker walked past"   "    if state is not False:" "    if state is True:"
mutate "M11 empty CLAUDE_PROJECT_DIR allowed" "if not cpd.strip():" "if False:"
# M12: a REAL grep-style extraction (strip backslash escapes, then decode) — the
# regression the JSON decoder exists to prevent. Written with chr()-built quotes so
# it introduces no bash-string syntax error (the mutant must PARSE, see judge()).
mutate "M12 escape-stripping extraction (pre-decode)" \
       "    doc = json.load(sys.stdin)" \
       "    doc = json.loads(re.sub(chr(92) + chr(46), chr(0), sys.stdin.read()).replace(chr(0), chr(0)))"
mutate "M13 mismatch-branch .state substring (R3 [4])" \
       '    if MODE == "gravity" and ".state" not in [c.lower() for c in target.replace(chr(92), "/").split("/")]:' \
       '    if MODE == "gravity" and ".state" not in target.lower():'
# --- fixes landed this round get their own mutants ---
mutate "M16 no interpreter isolation (-I)"    '"$GUARD_PY" -I -c ' '"$GUARD_PY" -c '
mutate "M17 accept ... as a terminator again" \
       'm = re.search(r"(?m)^---[ \t]*\r?$", text[3:])' \
       'm = re.search(r"(?m)^(?:---|\.\.\.)[ \t]*\r?$", text[3:])'
mutate "M18 walk from lexical launch dir (no realpath)" \
       "    root = physical(base) or lexical(base)    # resolve launch-dir symlinks first" \
       "    root = lexical(base)"
mutate "M19 case-sensitive .state detector" \
       '        return p is not None and ".state" in [c.lower() for c in p.split("/")]' \
       '        return p is not None and ".state" in p.split("/")'
mutate "M20 gravity .state depth-1 only" \
       '        return p is not None and ".state" in [c.lower() for c in p.split("/")]' \
       '        return p is not None and ".state" in [c.lower() for c in p.split("/")[-2:-1]]'
# M14/M15 edit ONE guard only — the drift the docs once called impossible.
mutate_one "M14 single-guard drift (containment)" containment-guard.sh \
       "    if state is not False:" "    if state is True:"
mutate_one "M15 single-guard drift (gravity)" gravity-guard.sh \
       "os.path.lexists(cm)" "os.path.exists(cm)"

echo
echo "-------------------------------------------"
if [ "$BAD" -eq 0 ] && [ "$SKIPPED" -eq 0 ]; then
    echo "ALL MUTANTS CAUGHT"; exit 0
fi
echo "$BAD mutant(s) survived / were malformed, $SKIPPED skipped (drifted target) — the suites do not prove what they claim"
exit 1
