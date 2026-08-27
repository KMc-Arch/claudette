#!/usr/bin/env bash
# H-06: PreToolUse — block state-gravity violations.
# Reads tool input JSON from stdin. Exit 2 = block, exit 0 = allow.
#
# State gravity rule: .state/ writes default to the nearest root: true context.
# This hook blocks writes to .state/ paths that are ABOVE the project root
# (i.e., a parent .state/). Writes to .state/ paths WITHIN ^ (including child
# project .state/ paths) are allowed.
#
# MATCHER REALITY: registered on "Write|Edit" only (cboot.py). That regex does
# NOT match NotebookEdit — a PreToolUse matcher is matched against the whole
# tool name, so NotebookEdit never reaches this hook. notebook_path is decoded
# below anyway so the guard is correct the moment the matcher is widened, but
# until then notebooks are an UNGUARDED write channel. Do not claim otherwise.
#
# The decision body below is byte-identical to containment-guard.sh and is
# asserted so by tests/test_guards_identical.sh. Only GUARD_MODE differs. That
# replaces the previous prose claim that the two "cannot drift apart", which
# nothing enforced — single-guard edits passed both suites.
GUARD_MODE=gravity

# >>> guard-core (byte-identical in gravity-guard.sh — proven by tests/test_guards_identical.sh)
GUARD_PY=$(command -v python3 || command -v python)
if [ -z "$GUARD_PY" ]; then
    echo "BLOCKED: no python interpreter available for the guard (fail closed)." >&2
    exit 2
fi

"$GUARD_PY" -c 'import json, os, posixpath, re, sys

MODE = sys.argv[1]
Q = chr(34) + chr(39)          # the two quote characters, unquotable inline


def die(*msg):
    for m in msg:
        sys.stderr.write(m + chr(10))
    sys.exit(2)


# ---- decode the write target ------------------------------------------------
# A real JSON parser, never grep: an embedded escaped quote truncates a grep
# match and can drop a trailing ../.. traversal, leaving the guard looking at an
# in-bounds prefix while the write lands outside ^.
try:
    doc = json.load(sys.stdin)
except Exception:
    die("BLOCKED: tool input is not decodable JSON (fail closed).")
if not isinstance(doc, dict):
    die("BLOCKED: tool input is not a JSON object (fail closed).")

ti = doc.get("tool_input")
sources = [ti if isinstance(ti, dict) else {}, doc]

target = None
badtype = False
for src in sources:
    for key in ("file_path", "notebook_path"):
        if key not in src:
            continue
        v = src[key]
        if isinstance(v, str):
            if v:
                target = v
                break
        else:
            badtype = True
    if target is not None:
        break

if target is None:
    # A key that is PRESENT but not a string is undecodable input, not "no
    # target" — it fails closed like every other decode failure.
    if badtype:
        die("BLOCKED: file_path/notebook_path is present but not a string (fail closed).")
    sys.exit(0)                # genuinely no path parameter: not a file write

# ---- establish the namespace ------------------------------------------------
DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
cpd = os.environ.get("CLAUDE_PROJECT_DIR") or ""
if not cpd.strip():
    die("BLOCKED: CLAUDE_PROJECT_DIR is empty or unset — cannot resolve ^ (fail closed).")


def is_win(p):
    return bool(DRIVE.match(p))


win_root = is_win(cpd)


def canon(p):
    if not win_root:
        return p
    p = p.replace(chr(92), "/")
    if DRIVE.match(p):
        p = p[0].lower() + p[1:]
    return p


target = canon(target)
cpd = canon(cpd)

if not (target.startswith("/") or is_win(target)):
    target = cpd.rstrip("/") + "/" + target      # relative: anchor to the launch dir
elif is_win(target) != win_root:
    # A Windows drive path and a POSIX root are not comparable. Refusing is the
    # only honest answer; the old code silently resolved it against the process
    # cwd, so the verdict depended on where the hook happened to be invoked.
    die("BLOCKED: cannot compare a Windows drive path against a POSIX project root (fail closed).",
        "  Target: " + target,
        "  Root:   " + cpd)


# ---- normalization ----------------------------------------------------------
# Lexical, in-process, never an exec. The tools this hook gates resolve ".."
# lexically (Node path.resolve) without touching the filesystem, so normalizing
# the same way is what actually models the write. It also has no argument-length
# limit, which is what made the previous `realpath -m` shell-out fail open.
def lexical(p):
    return posixpath.normpath(p)


def physical(p):
    # Symlink-resolved view, so a symlinked component cannot carry a write out
    # of ^ behind a clean-looking lexical path. Pure python: no exec, no E2BIG.
    try:
        return os.path.realpath(p)
    except OSError:
        return None


def inside(child, parent):
    if child == parent:
        return True
    return child.startswith(parent.rstrip("/") + "/")


# ---- resolve ^ --------------------------------------------------------------
# Nearest ancestor (inclusive) of the launch directory whose LEADING CLAUDE.md
# frontmatter declares root: true / apex-root: true — the algorithm in
# 01a-resolution/frontmatter.md.
#
# Direction of failure is the whole design here. Walking PAST a directory raises
# the ceiling, so anything undecidable must fence AT that directory instead:
# unreadable, non-regular, a dangling or looping symlink, a frontmatter block
# with no terminator, or a marker too large to scan. And the detector must be at
# least as permissive as boot-inject.py parse_frontmatter (BOM-tolerant, quoted
# values, indented keys) — a directory the reference resolver calls a root that
# this guard does not would loosen ^ below what governance believes it is.
FM_CAP = 65536
TRUE_WORDS = ("true", "yes", "on")


def unquote(s):
    return s.strip().strip(Q).strip(Q)


def root_state(d):
    """True = declared root, False = not a root, None = undecidable (fence here)."""
    cm = os.path.join(d, "CLAUDE.md")
    if not os.path.lexists(cm):        # lexists: a dangling symlink still counts
        return False
    if not os.path.isfile(cm):         # directory, fifo, dangling/looping link
        return None
    try:
        fh = open(cm, "rb")
    except OSError:
        return None
    try:
        raw = fh.read(FM_CAP)
    except OSError:
        return None
    finally:
        fh.close()
    text = raw.decode("utf-8", "replace").lstrip(chr(65279))
    if not text.startswith("---"):
        return False
    m = re.search(r"(?m)^(?:---|\.\.\.)[ \t]*\r?$", text[3:])
    if not m:
        return None                    # unterminated (or past the scan cap)
    for line in text[3:3 + m.start()].splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        if unquote(key).lower() not in ("root", "apex-root"):
            continue
        if unquote(val.split("#", 1)[0]).lower() in TRUE_WORDS:
            return True
    return False


root = lexical(cpd if cpd.startswith("/") or win_root else os.path.abspath(cpd))
walk = root
while True:
    state = root_state(walk)
    if state is not False:             # declared root, or undecidable -> fence here
        root = walk
        break
    parent = os.path.dirname(walk)
    if parent == walk:                 # filesystem root, no marker anywhere above:
        break                          # fall back to the launch dir (fences tighter)
    walk = parent

# ---- verdict ----------------------------------------------------------------
tgt_lex = lexical(target)
outside = not inside(tgt_lex, root)
if not outside:
    tgt_phys, root_phys = physical(target), physical(root)
    if tgt_phys and root_phys:
        outside = not inside(tgt_phys, root_phys)

if MODE == "gravity":
    def touches_state(p):
        return p is not None and ".state" in p.split("/")
    if not (touches_state(tgt_lex) or touches_state(physical(target))):
        sys.exit(0)                    # not a .state write: gravity has no opinion
    if outside:
        die("BLOCKED: State gravity violation - writing to .state/ outside project root.",
            "  Target: " + tgt_lex,
            "  Root:   " + root,
            "State gravity: .state/ writes default to the nearest root: true context.",
            "Use explicit ^ or ^/^ path notation to write to a parent .state/ on purpose.")
elif outside:
    die("BLOCKED: Write target is outside project root.",
        "  Target: " + tgt_lex,
        "  Root:   " + root,
        "Path containment: writes stay within ^ (the nearest root: true context).")

sys.exit(0)
' "$GUARD_MODE"
rc=$?
# <<< guard-core

if [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; then
    exit "$rc"
fi
echo "BLOCKED: guard did not complete (rc=$rc) — fail closed." >&2
exit 2
