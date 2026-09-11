#!/usr/bin/env bash
# H-3.9: PreToolUse (Write|Edit) — every CLAUDE.md: body immutable; only
# allowlisted frontmatter keys may change.
#
# SCOPE: any write target named CLAUDE.md (case-insensitive), or a hardlink to
# the CLAUDE.md in the same directory. Anywhere, not just the session root: a
# parent session editing a child's CLAUDE.md is held to exactly the rule the
# child's own session is. As referenced: a symlink is its own file, and a
# hardlink in ANOTHER directory is not detected — making either needs Bash or a
# human (BDRY-10).
#
# RULE — judged by the RESULT, never by where the edit lands. The guard computes
# the file as it will be after the tool runs, drops the allowlisted frontmatter
# lines from both the current and the resulting text, and requires what is left
# to be byte-identical. So the body, the --- fences, blank and comment lines, and
# every other key (root:, apex-root:, codex:, ...) cannot change. Only a line of
# the exact form `<key>: <value>` for an allowlisted key, at column 0, inside the
# leading frontmatter block, may be added, changed or removed.
#
# MODELLING THE TOOL. The result is the guard's own computation, so where Claude
# Code's Edit tool is known to transform text, the guard checks EVERY result the
# tool could produce, and all of them must pass:
#   - Empty new_string: the tool also deletes the line break after the match when
#     old_string does not end in one (observed in Claude Code 2.1.268). Both the
#     result with that line break and the result without it are checked.
#   - Line endings: the tool rewrites CRLF/LF across the whole file. Rather than
#     model that, a file or result containing a CR, a BOM, or any other character
#     str.splitlines() breaks on (VT, FF, FS/GS/RS, NEL, U+2028, U+2029) is
#     refused outright. That also keeps every frontmatter reader in the codex
#     agreeing on where the block ends, since they all split on LF.
#
# WHY A KEY ALLOWLIST, not "frontmatter is fair game": root: sets the containment
# ceiling ^ — containment-guard re-reads it on every write, so flipping a child's
# root: to false widens that session's fence to its parent — and codex: selects
# which governance and hooks a project runs under. Those stay human-only. A new
# key is human-only until it is added to ALLOWED below (and to frontmatter.md).
#
# CREATION is allowed: a Write to a CLAUDE.md that does not exist yet is
# scaffolding (/bundle, /rebuild, /new-project). It cannot loosen the running
# session — a new marker can only add a root, which fences tighter. It CAN set
# root:/apex-root:/codex: and a body for a future session launched in that new
# subtree: that takes a human to launch it, stays inside ^, and shows in the diff.
#
# FAILS CLOSED on anything it cannot vet: undecodable input or file, no leading
# frontmatter block, an Edit whose old_string is not found verbatim (the Edit
# tool can match curly quotes loosely, which the guard does not reproduce), a
# Windows drive path under a POSIX interpreter, a device-namespace path that is
# not a plain drive path, a missing interpreter, or any unexpected error.
#
# NOT COVERED: Bash writes (sed -i, redirection, interpreters). This hook sees
# Write/Edit only — the same limit as every Write/Edit guard here (BDRY-10).
#
# -I isolates the interpreter (no cwd on sys.path, so a planted json.py cannot
# shadow the stdlib; PYTHON* env ignored); see containment-guard.sh. The whole
# decision runs in that one python step.

trap '' PIPE    # a closed stderr must not turn the final echo into rc=141 (non-blocking)

GUARD_PY=
for c in python3 python; do
    c=$(command -v "$c") || continue
    case "$c" in */WindowsApps/*) continue ;; esac   # the Microsoft Store stub, not an interpreter
    GUARD_PY=$c
    break
done
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
    "name": re.compile(r"[ \t]{1,8}[^ \t\[\]{}&*!|>%@`].{0,199}"),
    "orchestrator": re.compile(r"[ \t]*(true|false)[ \t]*", re.I),
}
LINE = re.compile("(" + "|".join(re.escape(k) for k in ALLOWED) + r"):([^\n]*)\n")
MAX_BYTES = 1048576
BAD_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
DRIVE = re.compile(r"^[A-Za-z]:/")
NL = chr(10)
# Every line break str.splitlines() honours other than LF — CR, VT, FF, FS, GS,
# RS, NEL, U+2028, U+2029 — plus the BOM.
UNVETTABLE = "".join(chr(c) for c in (13, 11, 12, 28, 29, 30, 133, 8232, 8233, 65279))


def die(*msg):
    for m in msg:
        sys.stderr.write(m + chr(10))
    sys.exit(2)


# ---- decode ------------------------------------------------------------------
try:
    # Claude Code writes hook stdin as UTF-8. Decode it as such explicitly: under
    # -I, Windows Python would otherwise read the pipe as cp1252 and garble any
    # non-ASCII path (a real CLAUDE.md would then look absent — "creation").
    doc = json.loads(sys.stdin.buffer.read().decode("utf-8"))
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
if p[:4] in ("//./", "//?/"):          # Windows device / long-path namespace
    if DRIVE.match(p[4:]):
        p = p[4:]                      # \\.\C:\x and \\?\C:\x are plain C:\x
    elif p.rsplit("/", 1)[-1].casefold() == "claude.md":
        die("BLOCKED: a device-namespace path to a CLAUDE.md cannot be vetted (fail closed).")
if not (p.startswith("/") or DRIVE.match(p)):
    cpd = (os.environ.get("CLAUDE_PROJECT_DIR") or "").strip().replace(chr(92), "/")
    if cpd:
        p = cpd.rstrip("/") + "/" + p
p = posixpath.normpath(p)
base = p.rsplit("/", 1)[-1]
anchored = p.startswith("/") or bool(DRIVE.match(p))


def same_file_as_marker(path):
    # As referenced: lstat, never stat — a symlink is its own file (a human placed
    # it; see frontmatter.md), but a hardlink to the marker IS the marker.
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
if DRIVE.match(p) and os.name != "nt":
    die("BLOCKED: a Windows drive path to a CLAUDE.md cannot be vetted under a POSIX interpreter (fail closed).")

# ---- the resulting text(s) -------------------------------------------------------
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
if any(c in UNVETTABLE for c in old):
    die("BLOCKED: CLAUDE.md contains a CR, a BOM or another non-LF line break, so the guard cannot vet an edit to it",
        "  (the Edit tool rewrites line endings across the file). Edit it by hand, or convert it to plain LF first.")

if tool == "Write":
    content = ti.get("content")
    if not isinstance(content, str):
        die("BLOCKED: Write content is missing or not a string (fail closed).")
    results = [content]
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
            "  loosely, which it does not reproduce. Quote the file exactly.")
    if count > 1 and not ra:
        die("BLOCKED: old_string occurs " + str(count) + " times in CLAUDE.md — make it unique or use replace_all.")
    k = -1 if ra else 1
    results = [old.replace(o, n, k)]
    if n == "" and not o.endswith(NL) and (o + NL) in old:
        results.append(old.replace(o + NL, n, k))   # the tool also eats the line break


# ---- compare ---------------------------------------------------------------------
def skeleton(text, which):
    # -> (text minus allowlisted frontmatter lines, {key: value}, loose keys).
    # LF is the only line break left by now: UNVETTABLE was refused first.
    lines = text.splitlines(True)
    if not lines or lines[0] != "---" + NL:
        die("BLOCKED: " + which + " CLAUDE.md has no leading frontmatter block;",
            "  a CLAUDE.md without one is human-maintained in full.")
    close = None
    for i in range(1, len(lines)):
        if lines[i].startswith("---"):  # earliest possible fence: never over-extend
            close = i
            break
    if close is None:
        die("BLOCKED: " + which + " CLAUDE.md frontmatter is unterminated (fail closed).")
    kept, keys, loose = [lines[0]], {}, set()
    for ln in lines[1:close]:
        m = LINE.fullmatch(ln)
        if m is None:
            kept.append(ln)
            # An indented, quoted or re-cased line some reader would still take as
            # an allowlisted key: readers then disagree on which line wins.
            lk = ln.split(":", 1)[0].strip().strip(chr(34) + chr(39)).lower() if ":" in ln else ""
            if lk in ALLOWED:
                loose.add(lk)
            continue
        if m.group(1) in keys:
            die("BLOCKED: duplicate " + m.group(1) + ": line in " + which + " CLAUDE.md frontmatter.")
        keys[m.group(1)] = m.group(2)
    kept.extend(lines[close:])
    return "".join(kept), keys, loose


def valid(key, val):
    if "---" in val:
        return False                   # line-unanchored readers would end the block here
    if any(unicodedata.category(c) in BAD_CATEGORIES and c != chr(9) for c in val):
        return False
    return VALUE[key].fullmatch(val) is not None


old_sk, old_keys, loose = skeleton(old, "the current")
for new in results:
    if any(c in UNVETTABLE for c in new):
        die("BLOCKED: the change would put a CR, a BOM or another non-LF line break into CLAUDE.md.")
    if len(new.encode("utf-8", "surrogatepass")) > MAX_BYTES:
        die("BLOCKED: the resulting CLAUDE.md would be larger than 1 MiB (fail closed).")
    new_sk, new_keys, _ = skeleton(new, "the resulting")
    if new_sk != old_sk:
        die("BLOCKED: this change reaches outside the editable frontmatter keys of CLAUDE.md.",
            "  Claude may add, change or remove only these frontmatter lines: " + ", ".join(k + ":" for k in ALLOWED) + ".",
            "  The body, the --- fences, and every other key (root:, apex-root:, codex:, ...) are human-maintained.")
    changed = {k for k in set(old_keys) | set(new_keys) if old_keys.get(k) != new_keys.get(k)}
    if changed & loose:
        die("BLOCKED: CLAUDE.md also has a non-standard (indented, quoted or re-cased) line for " + ", ".join(sorted(changed & loose)) + ":",
            "  readers disagree on which line wins, so only a human may change that key.")
    for k in changed:
        if k in new_keys and not valid(k, new_keys[k]):
            die("BLOCKED: invalid value for " + k + ": in CLAUDE.md frontmatter.",
                "  orchestrator: takes true or false; name: takes one line of printable text (max 200, no ---).")
sys.exit(0)
'
rc=$?
if [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; then
    exit "$rc"
fi
echo "BLOCKED: CLAUDE.md guard did not complete (rc=$rc) — fail closed." >&2
exit 2
