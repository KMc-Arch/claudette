#!/usr/bin/env bash
# H-3.9: PreToolUse (Write|Edit) — every CLAUDE.md: body immutable; only
# allowlisted frontmatter keys may change.
#
# SCOPE: any write target named CLAUDE.md (case-insensitive), or that is the same
# file as its directory's CLAUDE.md (a hardlink, an NTFS 8.3 short name such as
# CLAUDE~1.MD, which drvfs resolves on volumes that keep short names). Anywhere,
# not just the session root: a parent session editing a child's CLAUDE.md is held
# to exactly the rule the child's own session is.
#
# RULE — judged by the RESULT, never by where the edit lands. The guard computes
# the file as it will be after the tool runs, drops the allowlisted frontmatter
# lines from both the current and the resulting text, and requires what is left
# to be byte-identical. So the body, the --- fences, blank and comment lines, and
# every other key (root:, apex-root:, codex:, ...) cannot change. Only a line of
# the exact form `<key>: <value>` for an allowlisted key, at column 0, inside the
# leading frontmatter block, may be added, changed or removed.
#
# WHY A KEY ALLOWLIST, not "frontmatter is fair game": root: sets the containment
# ceiling ^ — containment-guard re-reads it on every write, so flipping a child's
# root: to false widens that session's fence to its parent — and codex: selects
# which governance and hooks a project runs under. Those stay human-only. A new
# key is human-only until it is added to ALLOWED below (and to frontmatter.md).
#
# CREATION is allowed: a Write to a CLAUDE.md that does not exist yet is
# scaffolding (/bundle, /rebuild, a new project). A new marker can only ADD a
# root, which fences tighter, never looser.
#
# FAILS CLOSED on anything it cannot vet: undecodable input or file, no leading
# frontmatter block, an Edit whose old_string is not found verbatim (the Edit
# tool can match loosely — curly quotes, CRLF — which the guard cannot
# reproduce), a missing interpreter, or any unexpected error.
#
# NOT COVERED: Bash writes (sed -i, redirection, interpreters). This hook sees
# Write/Edit only — the same limit as every Write/Edit guard here (BDRY-10).
#
# -I isolates the interpreter (no cwd on sys.path, PYTHON* env ignored); see
# containment-guard.sh. The whole decision runs in that one python step.

GUARD_PY=$(command -v python3 || command -v python)
if [ -z "$GUARD_PY" ]; then
    echo "BLOCKED: no python interpreter available for the CLAUDE.md guard (fail closed)." >&2
    exit 2
fi

"$GUARD_PY" -I -c 'import json, os, posixpath, re, sys, unicodedata

# Frontmatter keys Claude may add, change or remove — the ONLY list; everything
# else is human-only. Each key needs a value grammar in VALUE (a key without one
# raises, which the rc wrapper turns into a block).
#   name:          display name (/new-project offers to add " Group" to a parent)
#   orchestrator:  the orchestrator designation (true/false)
ALLOWED = ("name", "orchestrator")
VALUE = {
    "name": re.compile(r"[ \t]+[^ \t\[\]{}&*!|>%@`].{0,199}"),
    "orchestrator": re.compile(r"[ \t]*(true|false)[ \t]*", re.I),
}
LINE = re.compile("(" + "|".join(re.escape(k) for k in ALLOWED) + r"):([^\r\n]*)(\r\n|\n)")
MAX_BYTES = 1048576
BAD_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
DRIVE = re.compile(r"^[A-Za-z]:/")


def die(*msg):
    for m in msg:
        sys.stderr.write(m + chr(10))
    sys.exit(2)


# ---- decode ------------------------------------------------------------------
try:
    doc = json.load(sys.stdin)
except Exception:
    die("BLOCKED: tool input is not decodable JSON (fail closed).")
if not isinstance(doc, dict):
    die("BLOCKED: tool input is not a JSON object (fail closed).")
tool = doc.get("tool_name")
ti = doc.get("tool_input")
if not isinstance(ti, dict):
    ti = {}

target = None
badtype = False
for src in (ti, doc):
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
    if badtype:
        die("BLOCKED: file_path/notebook_path is present but not a string (fail closed).")
    sys.exit(0)                        # no path parameter: not a file write

# ---- is it a CLAUDE.md? --------------------------------------------------------
p = target.replace(chr(92), "/")
if not (p.startswith("/") or DRIVE.match(p)):
    cpd = (os.environ.get("CLAUDE_PROJECT_DIR") or "").strip().replace(chr(92), "/")
    if cpd:
        p = cpd.rstrip("/") + "/" + p
p = posixpath.normpath(p)
base = p.rsplit("/", 1)[-1]
anchored = p.startswith("/") or bool(DRIVE.match(p))


def same_file_as_marker(path):
    # As referenced: lstat, never stat — a symlink is its own file (a human placed
    # it; see frontmatter.md), but a hardlink or short-name alias IS the marker.
    d = path.rsplit("/", 1)[0] if "/" in path else "."
    try:
        a = os.lstat(path)
        b = os.lstat((d or "/") + "/CLAUDE.md")
    except (OSError, ValueError):
        return False
    return a.st_ino != 0 and (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


if base.casefold() != "claude.md":
    if not anchored or not same_file_as_marker(p):
        sys.exit(0)                    # not a CLAUDE.md: this guard has no opinion
if not anchored:
    die("BLOCKED: relative CLAUDE.md path with no CLAUDE_PROJECT_DIR — cannot vet (fail closed).")

# ---- the resulting text ----------------------------------------------------------
if tool not in ("Write", "Edit"):
    die("BLOCKED: CLAUDE.md may only be changed through Write or Edit (tool: " + str(tool) + ").")

if not os.path.lexists(p):
    if tool == "Write":
        sys.exit(0)                    # creation: scaffolding a new CLAUDE.md
    die("BLOCKED: Edit targets a CLAUDE.md that does not exist (fail closed).")
if not os.path.isfile(p):
    die("BLOCKED: CLAUDE.md target is not a regular file (fail closed).")
try:
    with open(p, "rb") as fh:
        raw = fh.read(MAX_BYTES + 1)
except OSError as e:
    die("BLOCKED: cannot read CLAUDE.md to vet the change (fail closed).", "  " + str(e))
if len(raw) > MAX_BYTES:
    die("BLOCKED: CLAUDE.md is larger than 1 MiB — too large to vet (fail closed).")
try:
    old = raw.decode("utf-8")
except UnicodeDecodeError:
    die("BLOCKED: CLAUDE.md is not valid UTF-8 — cannot vet (fail closed).")

if tool == "Write":
    new = ti.get("content")
    if not isinstance(new, str):
        die("BLOCKED: Write content is missing or not a string (fail closed).")
else:
    o, n = ti.get("old_string"), ti.get("new_string")
    ra = ti.get("replace_all", False)
    if ra is None:
        ra = False
    if not isinstance(o, str) or not isinstance(n, str) or not isinstance(ra, bool):
        die("BLOCKED: Edit parameters are missing or malformed (fail closed).")
    if not o:
        die("BLOCKED: an Edit to CLAUDE.md needs a non-empty old_string (fail closed).")
    count = old.count(o)
    if count == 0:
        die("BLOCKED: old_string does not occur verbatim in CLAUDE.md.",
            "  The guard vets exact matches only; the Edit tool may match curly quotes",
            "  or CRLF loosely, which it cannot reproduce. Quote the file exactly.")
    if count > 1 and not ra:
        die("BLOCKED: old_string occurs " + str(count) + " times in CLAUDE.md — make it unique or use replace_all.")
    new = old.replace(o, n) if ra else old.replace(o, n, 1)


# ---- compare ---------------------------------------------------------------------
def skeleton(text, which):
    # (text minus allowlisted frontmatter lines, {key: value}). splitlines() is the
    # widest line splitter any consumer uses, so a value cannot smuggle a second
    # line past this check with a U+2028 or a lone CR.
    bom = ""
    if text.startswith(chr(65279)):
        bom, text = chr(65279), text[1:]
    lines = text.splitlines(True)
    if not lines or lines[0] not in ("---" + chr(10), "---" + chr(13) + chr(10)):
        die("BLOCKED: " + which + " CLAUDE.md has no leading frontmatter block;",
            "  a CLAUDE.md without one is human-maintained in full.")
    close = None
    for i in range(1, len(lines)):
        if lines[i].startswith("---"):  # earliest possible fence: never over-extend
            close = i
            break
    if close is None:
        die("BLOCKED: " + which + " CLAUDE.md frontmatter is unterminated (fail closed).")
    kept, keys = [bom, lines[0]], {}
    for ln in lines[1:close]:
        m = LINE.fullmatch(ln)
        if m is None:
            kept.append(ln)
            continue
        if m.group(1) in keys:
            die("BLOCKED: duplicate " + m.group(1) + ": line in " + which + " CLAUDE.md frontmatter.")
        keys[m.group(1)] = m.group(2)
    kept.extend(lines[close:])
    return "".join(kept), keys


def valid(key, val):
    if any(unicodedata.category(c) in BAD_CATEGORIES and c != chr(9) for c in val):
        return False
    return VALUE[key].fullmatch(val) is not None


old_sk, old_keys = skeleton(old, "the current")
new_sk, new_keys = skeleton(new, "the resulting")
if new_sk != old_sk:
    die("BLOCKED: this change reaches outside the editable frontmatter keys of CLAUDE.md.",
        "  Claude may add, change or remove only these frontmatter lines: " + ", ".join(k + ":" for k in ALLOWED) + ".",
        "  The body, the --- fences, and every other key (root:, apex-root:, codex:, ...) are human-maintained.")
for k, v in new_keys.items():
    if old_keys.get(k) != v and not valid(k, v):
        die("BLOCKED: invalid value for " + k + ": in CLAUDE.md frontmatter.",
            "  orchestrator: takes true or false; name: takes one line of printable text (max 200).")
sys.exit(0)
'
rc=$?
if [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; then
    exit "$rc"
fi
echo "BLOCKED: CLAUDE.md guard did not complete (rc=$rc) — fail closed." >&2
exit 2
