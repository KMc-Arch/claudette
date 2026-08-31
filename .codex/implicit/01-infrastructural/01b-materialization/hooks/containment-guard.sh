#!/usr/bin/env bash
# H-05: PreToolUse — block writes outside the project root (^).
# Reads tool input JSON from stdin. Exit 2 = block, exit 0 = allow.
#
# MATCHER REALITY: registered on "Write|Edit" only (cboot.py). That regex does
# NOT match NotebookEdit — a PreToolUse matcher is matched against the whole
# tool name, so NotebookEdit never reaches this hook. notebook_path is decoded
# below anyway so the guard is correct the moment the matcher is widened, but
# until then notebooks are an UNGUARDED write channel. Do not claim otherwise.
#
# The whole decision — decode, root resolution, normalization, comparison —
# happens in one python step. That is deliberate. Every shell tool this used to
# lean on fails OPEN when it errors: grep returns non-zero and the prefilter
# reads it as "no match"; realpath cannot exec an oversized path (E2BIG) and the
# `|| echo` fallback hands back a string with `../..` still in it; awk reports
# "not a root" for a marker it merely could not parse, walking the ceiling UP.
# One step that already runs, and that already fails closed, does all of it.
#
# -I isolates the interpreter: sys.path[0] is NOT the cwd (so an innocent
# json.py in the project root cannot shadow the stdlib and make json.load a
# no-op), and PYTHON* env vars are ignored. It does NOT drop ordinary env, so
# CLAUDE_PROJECT_DIR still reaches os.environ. An interpreter too old to know -I
# exits non-zero, which the rc wrapper below turns into a fail-closed block.
#
GUARD_MODE=containment

# >>> guard-core (byte-identical across BOTH guards — proven by tests/test_guards_identical.sh)
GUARD_PY=$(command -v python3 || command -v python)
if [ -z "$GUARD_PY" ]; then
    echo "BLOCKED: no python interpreter available for the guard (fail closed)." >&2
    exit 2
fi

"$GUARD_PY" -I -c 'import json, os, posixpath, re, sys

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
cpd = (os.environ.get("CLAUDE_PROJECT_DIR") or "").strip()
if not cpd:
    die("BLOCKED: CLAUDE_PROJECT_DIR is empty or unset — cannot resolve ^ (fail closed).")
# strip() above also removes a stray trailing newline/space: without it the raw
# value flows into the walk seed and root_lex carries the newline, so an ordinary
# in-tree write fails the prefix test (fail-closed false positive). R4 [2].


def is_win(p):
    return bool(DRIVE.match(p))


win_root = is_win(cpd)
if win_root and os.path is posixpath:
    die("BLOCKED: a Windows-drive CLAUDE_PROJECT_DIR under a POSIX interpreter "
        "is not supported — cannot resolve ^ (fail closed).")


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
    # A Windows drive path and a POSIX root are not comparable. Gravity only
    # polices .state writes, so a non-.state target here is simply not its
    # concern — exit 0 rather than blocking an ordinary write with a rule that
    # was never meant to see it. Otherwise refusing is the only honest answer;
    # the old code silently resolved against the process cwd, so the verdict
    # depended on where the hook happened to be invoked.
    if MODE == "gravity" and ".state" not in [c.lower() for c in target.replace(chr(92), "/").split("/")]:
        sys.exit(0)
    die("BLOCKED: cannot compare a Windows drive path against a POSIX project root (fail closed).",
        "  Target: " + target,
        "  Root:   " + cpd)


# ---- normalization ----------------------------------------------------------
# AS REFERENCED: normpath collapses "." and ".." TEXTUALLY, in-process, and never
# follows a symlink. That is deliberate and load-bearing — a symlink inside ^ is
# an authorised extension of the project (a human placed it; the ABSOLUTE HOLD in
# root CLAUDE.md keeps symlink construction human-only), so a write through it is
# in-project BY REFERENCE and must be allowed. Egress via a symlink pointing OUT
# of ^ is delegated to environment isolation (BL-61) and surfaced by
# symlink-egress-scan.sh — it is NOT decided here. normpath still collapses "..",
# so ../ traversal and oversized paths are blocked, with no exec and no
# argument-length limit (which is what made the old `realpath -m` shell-out fail
# open). We never call realpath: resolving a symlink would override the human
# decision to extend the project through it.
def lexical(p):
    return posixpath.normpath(p)


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
    m = re.search(r"(?m)^---[ \t]*\r?$", text[3:])
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


# Resolve ^ over the REFERENCED launch path — abspath/normpath make it absolute
# and collapse "." / ".." without touching the filesystem. A symlinked launch dir
# is treated as the project it is referenced as, never resolved to its target.
base = cpd if cpd.startswith("/") or win_root else os.path.abspath(cpd)
root = lexical(base)
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
# Compare AS REFERENCED (see normalization above): the target is inside ^ iff its
# referenced, ".."-collapsed path is inside the referenced ^. No symlink is
# resolved on either side — symmetric by construction, so the asymmetry that made
# the physical scheme regress cannot arise.
tgt_lex, root_lex = lexical(target), lexical(root)
outside = not inside(tgt_lex, root_lex)

if MODE == "gravity":
    def touches_state(p):
        return p is not None and ".state" in [c.lower() for c in p.split("/")]
    if not touches_state(tgt_lex):
        sys.exit(0)                    # not a .state write (as referenced): gravity has no opinion
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
