#!/usr/bin/env bash
# H-3.9: PreToolUse (Write|Edit) — every CLAUDE.md: body immutable; only
# allowlisted frontmatter keys may change.
#
# SCOPE: any write target named CLAUDE.md (case-insensitive; a trailing dot or
# space, a ":stream" suffix, or an invisible formatting character is ignored —
# Windows and HFS+ resolve those to the same file), or a hardlink to the
# CLAUDE.md in the same directory. Anywhere, not just the session root: a parent
# session editing a child's CLAUDE.md is held to exactly the rule the child's own
# session is. As referenced: a symlink is its own file, and a hardlink in ANOTHER
# directory is not detected — making either needs Bash or a human (BDRY-10). An
# existing CLAUDE.md must be addressed by its exact on-disk spelling: on a
# case-insensitive filesystem the tool would otherwise rename it (it writes a
# temp file and renames it onto the given name).
#
# RULE — judged by the RESULT, never by where the edit lands. The guard computes
# the file as it will be after the tool runs, drops the allowlisted frontmatter
# lines from both the current and the resulting text, and requires what is left
# to be byte-identical. So the body, the --- fences, blank and comment lines, and
# every other key (root:, apex-root:, codex:, ...) cannot change. Only a line of
# the exact form `<key>: <value>` for an allowlisted key, at column 0, inside the
# leading frontmatter block, may be added, changed, moved or removed — and a
# moved line is re-checked like a changed one.
#
# WHERE THE BLOCK ENDS. Claude Code itself strips frontmatter with a regex that
# stops at the FIRST "---" anywhere in the text, and injects the rest as
# instructions; the codex readers stop at the first line that is exactly "---".
# So the guard ends the block at the first line containing "---" and requires
# that line to be exactly "---" — otherwise the readers disagree and the file is
# human-only. A block that ends past 64 KiB is refused too: containment-guard
# reads only that much.
#
# MODELLING THE TOOL. The result is the guard's own computation, so where Claude
# Code's Edit tool is known to transform text, the guard checks EVERY result the
# tool could produce, and all of them must pass:
#   - Empty new_string: the tool also deletes the line break after the match when
#     old_string does not end in one (observed in Claude Code 2.1.268). Both the
#     result with that line break and the result without it are checked, so to
#     remove a key, include its line break in old_string.
#   - Line endings: the tool rewrites CRLF/LF across the whole file. Rather than
#     model that, a file or result containing a CR, a BOM, or any other character
#     str.splitlines() breaks on (VT, FF, FS/GS/RS, NEL, U+2028, U+2029) is
#     refused outright.
#   - Paths: on POSIX a backslash is an ordinary filename character (Claude Code
#     keeps it), so a path containing one that names a CLAUDE.md either way is
#     refused as ambiguous; on Windows every file call goes through the literal
#     extended-length form (\\?\), as Claude Code's runtime does, so trailing
#     dots and long paths mean the same thing to both.
#   - A CLAUDE.md under .state/memory/ is refused: the tools re-stamp frontmatter
#     of .md files in the auto-memory directory.
#
# WHY A KEY ALLOWLIST, not "frontmatter is fair game": root: sets the containment
# ceiling ^ — containment-guard re-reads it on every write, so flipping a child's
# root: to false widens that session's fence to its parent — and codex: selects
# which governance and hooks a project runs under. Those stay human-only. A new
# key is human-only until it is added to ALLOWED below (and to frontmatter.md).
#
# CREATION is blocked too (KMc, 2026-09-11): a Write to a CLAUDE.md that does
# not exist yet is refused. A new CLAUDE.md is not confined to future sessions —
# Claude Code loads it into the running session when a file in that folder is
# read (subagents, the main thread after compaction, other sessions), every
# existing project below it picks it up through the upward CLAUDE.md walk, and
# one with apex-root: true between the apex and a child moves where that child
# resolves ^/^ and so its codex. Scaffolding goes through the command that owns
# it (/new-project runs bootstrap-child.py; /bundle renames a staged file with
# python); anything else, Claude hands the user the text. CLAUDE.local.md and
# .claude/rules/*.md carry the same authority but are deliberately NOT covered
# (KMc, 2026-09-11). See frontmatter.md.
#
# FAILS CLOSED on anything it cannot vet: undecodable input or file, a path it
# cannot stat cleanly, no leading frontmatter block, an Edit whose old_string is
# not found verbatim (the Edit tool can match curly quotes loosely, which the
# guard does not reproduce), device-namespace, drive-relative and /proc paths, a
# drive path under a POSIX interpreter, a Windows path too long to vet, a missing
# or hanging interpreter, or any unexpected error.
#
# NOT COVERED: Bash writes (sed -i, redirection, interpreters). This hook sees
# Write/Edit only — the same limit as every Write/Edit guard here (BDRY-10). Two
# Edits issued in parallel are each vetted against the same starting file, so
# their composition is not seen.
#
# -I isolates the interpreter (no cwd on sys.path, so a planted json.py cannot
# shadow the stdlib; PYTHON* env ignored); -X utf8 makes file names, stdin and
# stderr UTF-8 whatever the locale or code page (-X is not an env var, so -I keeps
# it). The whole decision runs in that one python step.

trap '' PIPE    # a closed stderr must not turn the final echo into rc=141 (non-blocking)

TO=$(command -v timeout || command -v gtimeout || true)
case "$TO" in *[Ss][Yy][Ss][Tt][Ee][Mm]32*) TO= ;; esac   # Windows timeout.exe pauses, it does not limit

GUARD_PY=
GUARD_PY_PRE=
while IFS= read -r c; do
    case "$c" in /*) ;; *) continue ;; esac   # a relative PATH entry would resolve inside the project
    case "$c" in
        */[Ww][Ii][Nn][Dd][Oo][Ww][Ss][Aa][Pp][Pp][Ss]/*)
            # An App Execution Alias: a real Store Python, or the stub that only
            # offers to install one. Keep it only if it actually runs.
            ${TO:+"$TO" 10} "$c" -I -c "" >/dev/null 2>&1 </dev/null || continue ;;
    esac
    GUARD_PY=$c
    break
done <<EOF
$(type -ap python3 python 2>/dev/null)
EOF
if [ -z "$GUARD_PY" ] && c=$(command -v py 2>/dev/null) && [ "${c#/}" != "$c" ] \
   && ${TO:+"$TO" 10} "$c" -3 -I -c "" >/dev/null 2>&1 </dev/null; then
    GUARD_PY=$c                                  # the Windows launcher, when no python is on PATH
    GUARD_PY_PRE=-3
fi
if [ -z "$GUARD_PY" ]; then
    echo "BLOCKED: no python interpreter available for the CLAUDE.md guard (fail closed)." >&2
    exit 2
fi

${TO:+"$TO" 60} "$GUARD_PY" $GUARD_PY_PRE -I -X utf8 -c 'import json, ntpath, os, posixpath, re, sys, unicodedata

# Frontmatter keys Claude may add, change or remove — the ONLY list; everything
# else is human-only. Each key needs a value grammar in VALUE (a key without one
# raises, which the rc wrapper turns into a block).
#   name:          display name (/new-project offers to add " Group" to a parent)
#   orchestrator:  the orchestrator designation (true/false)
ALLOWED = ("name", "orchestrator")
VALUE = {
    "name": re.compile(r"[ \t]{1,8}[^ \t\[\]{}&*!|>%@`].{0,199}"),
    "orchestrator": re.compile(r"[ \t]{1,8}(true|false)[ \t]{0,8}"),
}
LINE = re.compile("(" + "|".join(re.escape(k) for k in ALLOWED) + r"):([^\n]*)\n")
MAX_BYTES = 1048576
SCAN_CAP = 65536                       # containment-guard root_state() reads this much
BAD_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
DRIVE = re.compile(r"^[A-Za-z]:/")
DRIVE_RELATIVE = re.compile(r"^[A-Za-z]:(?!/)")
NL = chr(10)
BS = chr(92)
# Every line break str.splitlines() honours other than LF — CR, VT, FF, FS, GS,
# RS, NEL, U+2028, U+2029 — plus the BOM.
UNVETTABLE = "".join(chr(c) for c in (13, 11, 12, 28, 29, 30, 133, 8232, 8233, 65279))
UNVETTABLE_RE = re.compile("[" + re.escape(UNVETTABLE) + "]")
WIN = os.name == "nt"
WIN_PATH_MAX = 240                     # under MAX_PATH (260), with room for a temp-file suffix


def die(*msg):
    for m in msg:
        sys.stderr.write(m + chr(10))
    sys.exit(2)


# ---- decode ------------------------------------------------------------------
try:
    # Claude Code writes hook stdin as UTF-8. Decode it strictly: text-mode stdin
    # would substitute undecodable bytes (surrogateescape) instead of failing.
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
def marker_name(b):
    # Windows opens CLAUDE.md for "CLAUDE.md.", "CLAUDE.md " and "CLAUDE.md::$DATA";
    # HFS+ ignores invisible formatting characters in names.
    if DRIVE_RELATIVE.match(b):
        b = b[2:]
    b = b.split(":", 1)[0]
    b = "".join(c for c in b if unicodedata.category(c) != "Cf")
    return b.rstrip(". ").casefold() == "claude.md"


def fs(path):
    # The path to hand the OS. On Windows: the literal extended-length form, as
    # Claude Code runtime uses — no stripping of trailing dots, no MAX_PATH limit.
    if not WIN:
        return path
    w = path.replace("/", BS)
    if w.startswith(BS + BS):
        return BS + BS + "?" + BS + "UNC" + w[1:]
    return BS + BS + "?" + BS + w


def last(path):
    return path.rstrip("/").rsplit("/", 1)[-1]


if not WIN and BS in target:
    # On POSIX a backslash is an ordinary filename character — Claude Code keeps
    # it — but read as a separator it names a different file. If either reading
    # is a CLAUDE.md, refuse rather than guess.
    if marker_name(last(posixpath.normpath(target))) or marker_name(last(posixpath.normpath(target.replace(BS, "/")))):
        die("BLOCKED: a path containing a backslash that names a CLAUDE.md is ambiguous on POSIX (fail closed).")

raw = target.replace(BS, "/") if WIN else target
p = raw
if not (p.startswith("/") or DRIVE.match(p) or DRIVE_RELATIVE.match(p)):
    # Claude Code resolves a relative path against the session working directory,
    # which the hook input carries as "cwd"; CLAUDE_PROJECT_DIR is the fallback.
    anchor = doc.get("cwd")
    if not (isinstance(anchor, str) and anchor.strip()):
        anchor = os.environ.get("CLAUDE_PROJECT_DIR") or ""
    if anchor.strip():
        anchor = anchor.replace(BS, "/") if WIN else anchor
        p = anchor.rstrip("/") + "/" + p
device = p[:4] in ("//./", "//?/")    # Windows device / long-path namespace
if WIN:
    p = ntpath.normpath(p).replace(BS, "/")    # keeps the drive and trailing dots
else:
    if p.startswith("//"):
        p = "/" + p.lstrip("/")        # POSIX: // is /
    p = posixpath.normpath(p)
base = last(p)
anchored = p.startswith("/") or bool(DRIVE.match(p))


def same_file_as_marker(path):
    # As referenced: lstat, never stat — a symlink is its own file (a human placed
    # it; see frontmatter.md), but a hardlink to the marker IS the marker.
    d = path.rsplit("/", 1)[0] if "/" in path else "."
    try:
        a = os.lstat(fs(path))
        b = os.lstat(fs((d or "/") + "/CLAUDE.md"))
    except (OSError, ValueError):
        return False
    return a.st_ino != 0 and (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


if not marker_name(base):
    if not anchored or not same_file_as_marker(p):
        sys.exit(0)                    # not a CLAUDE.md: this guard has no opinion
if device:
    die("BLOCKED: a device-namespace path (//./ or //?/ form) to a CLAUDE.md cannot be vetted (fail closed).")
if not anchored:                       # relative with no cwd / CLAUDE_PROJECT_DIR, or drive-relative (C:name)
    die("BLOCKED: a relative or drive-relative CLAUDE.md path cannot be vetted (fail closed).")
if DRIVE.match(p) and not WIN:
    die("BLOCKED: a Windows drive path to a CLAUDE.md cannot be vetted under a POSIX interpreter (fail closed).")
if not WIN and (p == "/proc" or p.startswith("/proc/") or p.startswith("/dev/fd/")):
    die("BLOCKED: a /proc or /dev/fd path to a CLAUDE.md would resolve in the hook process, not the tool (fail closed).")
if WIN and len(p.encode("utf-16-le")) // 2 > WIN_PATH_MAX:
    die("BLOCKED: this CLAUDE.md path is too long to vet reliably on Windows (fail closed).")
if "/.state/memory/" in "/" + p.casefold():
    die("BLOCKED: a CLAUDE.md in the auto-memory directory is re-stamped by the tools, so it cannot be vetted.")

# ---- the resulting text(s) -------------------------------------------------------
if tool not in ("Write", "Edit"):
    die("BLOCKED: CLAUDE.md may only be changed through Write or Edit (tool: " + str(tool) + ").")

try:
    os.lstat(fs(p))
    exists = True
except FileNotFoundError:
    exists = False
except (OSError, ValueError) as e:     # EACCES, ENAMETOOLONG, ELOOP, an unencodable name, ...
    die("BLOCKED: cannot stat the CLAUDE.md target, so cannot tell whether it exists (fail closed).", "  " + str(e))
if not exists:
    if tool == "Write":
        die("BLOCKED: creating a CLAUDE.md is human-only — its text loads as instructions into this and other sessions.",
            "  Scaffold with the command that owns it (/new-project, /bundle), or give the user the text to create.")
    die("BLOCKED: Edit targets a CLAUDE.md that does not exist (fail closed).")
folder = p.rsplit("/", 1)[0] or "/"
if re.fullmatch(r"[A-Za-z]:", folder):
    folder += "/"                      # "D:" alone would be the current folder on D:
try:
    names = os.listdir(fs(folder))
except OSError as e:
    die("BLOCKED: cannot list the directory of the CLAUDE.md target (fail closed).", "  " + str(e))
if base not in names:
    die("BLOCKED: address this CLAUDE.md by its exact on-disk name — the tool would rename it to " + base + ".")
if not os.path.isfile(fs(p)):
    die("BLOCKED: CLAUDE.md target is not a regular file (fail closed).")
try:
    with open(fs(p), "rb") as fh:
        raw_bytes = fh.read(MAX_BYTES + 1)
except OSError as e:
    die("BLOCKED: cannot read CLAUDE.md to vet the change (fail closed).", "  " + str(e))
if len(raw_bytes) > MAX_BYTES:
    die("BLOCKED: CLAUDE.md is larger than 1 MiB — too large to vet (fail closed).")
try:
    old = raw_bytes.decode("utf-8")
except UnicodeDecodeError:
    die("BLOCKED: CLAUDE.md is not valid UTF-8 — cannot vet (fail closed).")
if UNVETTABLE_RE.search(old):
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
    cands = [o]
    if n == "" and not o.endswith(NL) and (o + NL) in old:
        cands.append(o + NL)           # the tool also eats the line break
    results = []
    for oo in cands:
        hits = old.count(oo) if ra else 1
        if len(old) + hits * (len(n) - len(oo)) > MAX_BYTES:
            die("BLOCKED: the resulting CLAUDE.md would be larger than 1 MiB (fail closed).")
        results.append(old.replace(oo, n, -1 if ra else 1))


# ---- compare ---------------------------------------------------------------------
def skeleton(text, which):
    # -> (text minus allowlisted frontmatter lines, {key: (value, anchor)}, loose
    # keys). The anchor is how many protected lines precede the key, so moving an
    # allowlisted line past a protected one counts as a change.
    # LF is the only line break left by now: UNVETTABLE was refused first.
    lines = text.splitlines(True)
    if not lines or lines[0] != "---" + NL:
        die("BLOCKED: " + which + " CLAUDE.md has no leading frontmatter block;",
            "  a CLAUDE.md without one is human-maintained in full.")
    close = None
    for i in range(1, len(lines)):
        if "---" in lines[i]:          # Claude Code ends the block at the first --- anywhere
            close = i
            break
    if close is None:
        die("BLOCKED: " + which + " CLAUDE.md frontmatter is unterminated (fail closed).")
    if lines[close] != "---" + NL:
        die("BLOCKED: " + which + " CLAUDE.md frontmatter has --- before a clean closing fence (a line that is exactly ---);",
            "  readers, Claude Code included, would end the block in different places, so the file is human-maintained.")
    if len("".join(lines[:close + 1]).encode("utf-8", "surrogatepass")) > SCAN_CAP:
        die("BLOCKED: " + which + " CLAUDE.md frontmatter runs past 64 KiB, where the containment guard stops reading (fail closed).")
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
        keys[m.group(1)] = (m.group(2), len(kept))
    kept.extend(lines[close:])
    return "".join(kept), keys, loose


def valid(key, val):
    if "---" in val:
        return False                   # it would end the block for Claude Code and cboot
    if any(unicodedata.category(c) in BAD_CATEGORIES and c != chr(9) for c in val):
        return False
    return VALUE[key].fullmatch(val) is not None


old_sk, old_keys, loose = skeleton(old, "the current")
for new in results:
    if UNVETTABLE_RE.search(new):
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
        if k in new_keys and not valid(k, new_keys[k][0]):
            die("BLOCKED: invalid value for " + k + ": in CLAUDE.md frontmatter.",
                "  orchestrator: takes 1-8 blanks then true or false. name: takes 1-8 blanks, then one line of",
                "  printable text (max 200) that does not start with [ ] { } & * ! | > % @ or a backtick and has no ---.")
sys.exit(0)
'
rc=$?
if [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; then
    exit "$rc"
fi
echo "BLOCKED: CLAUDE.md guard did not complete (rc=$rc) — fail closed." >&2
exit 2
