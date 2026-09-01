"""Ownership of files in the apex `.claude/agents/` directory — ONE implementation.

THE RULE (and it is the whole module):

    A file in `^/.claude/agents/` belongs to cboot **if and only if the durable
    `agent_registry` in `^/.state/roots.db` currently claims it.**

Ownership is a lookup of the file's path against current registry rows. It is
NEVER inferred from the file's contents. Nothing in this module decodes a
candidate file in order to decide whether it may be written or deleted.

Why it is a module and not a helper in cboot.py: `cboot.py` and
`.codex/explicit/purge/purge.py` both need the answer, and two divergent
implementations of the same ownership test is exactly the defect this module
exists to make impossible. Callers consume `claims_for()` / `owns()`. A caller
that reimplements the rule is a defect, not an optimisation.

The marker comment (`<!-- cboot:agent ... -->`) is ADVISORY ONLY: a
human-readable "generated, do not hand-edit" banner plus a tamper check. It
confers nothing and removes nothing. A forged marker cannot make a file ours; a
missing marker cannot make our file foreign. Divergence between the registry and
the marker is reported, never acted on.

Fail-safe posture: if `roots.db` is missing, locked, or unreadable, `claims_for()`
raises `RegistryUnavailable`. Callers that DELETE must treat that as "own
nothing" and preserve everything. Callers that WRITE must treat it as "abort".
"""

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

# The directory this module governs, relative to the apex root.
AGENTS_REL = ".claude/agents"

# Suffix of cboot's own staging artifacts. Never hand-authored; always cruft.
TMP_SUFFIX = ".md.tmp"

# Namespace suffix for cboot-generated agent names: the invocable @name and its
# filename both carry it (`drawio` -> `@drawio-pj`, `drawio-pj.md`), so cboot's
# names and files never share the namespace of hand-authored agents. Prose spells
# the role out ("project agent") and never shows the abbreviation.
SUFFIX = "-pj"

# Marker: FIRST body line of a generated file. Anchored fullmatch, never a
# search — a file that merely quotes the marker in its prose is not matched.
_MARKER_RE = re.compile(
    r'<!-- cboot:agent root=(?P<root>"(?:[^"\\]|\\.)*") generated="(?P<gen>[^"]*)" -->'
)

# Names Claude Code reserves or that cannot round-trip as a file stem.
RESERVED_NAMES = frozenset({
    "general-purpose", "statusline-setup", "output-style-setup",
    "claude", "Explore", "Plan", "Task", "Bash", "Agent",
})


class RegistryUnavailable(Exception):
    """roots.db is missing, locked, or structurally unusable.

    Deleters MUST interpret this as "cboot owns nothing" and preserve every
    file. Writers MUST abort. It is never safe to guess.
    """


# ── Claims ───────────────────────────────────────────────────────────

def _open_ro(db_path):
    """Open roots.db TRULY read-only, or raise RegistryUnavailable.

    `immutable=1&mode=ro` is the genuine read-only open — `mode=ro` alone still
    creates/updates `-wal`/`-shm` sidecars on a WAL database (see
    .state/memory/reference_sqlite_wal_readonly.md). The ONE read-only open every
    reader in this module shares, so `claims_for` and `read_spine_history` can never
    disagree about how the db is opened.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise RegistryUnavailable(f"roots.db not found: {db_path}")
    uri = "file:" + db_path.resolve().as_posix().replace("?", "%3f").replace("#", "%23")
    try:
        return sqlite3.connect(uri + "?immutable=1&mode=ro", uri=True)
    except sqlite3.Error as e:
        raise RegistryUnavailable(f"roots.db unopenable: {e}") from e


def claims_for(db_path, agents_dir):
    """Return the set of absolute agent-file paths cboot currently claims.

    Reads the CURRENT (`valid_to IS NULL`) rows of the durable SCD2
    `agent_registry`. Returns {resolved_abs_posix_path: {agent_name, rel_path}}.

    Opened read-only and immutable — `mode=ro` alone still creates/updates
    `-wal`/`-shm` sidecars on a WAL database; `immutable=1&mode=ro` is the true
    read-only open (see .state/memory/reference_sqlite_wal_readonly.md).

    Raises RegistryUnavailable on any failure. Never returns a partial answer.
    """
    agents_dir = Path(agents_dir)
    conn = _open_ro(db_path)
    try:
        try:
            # LEFT JOIN + COALESCE: prefer the CURRENT spine rel_path (so a moved
            # root is owned at its new location), falling back to the claim's own
            # frozen rel_path when the identity has no current spine row — a broken
            # or absent link never un-owns a file.
            rows = conn.execute(
                "SELECT ar.agent_name, COALESCE(rr.rel_path, ar.rel_path) AS rel_path,"
                " ar.agent_file, ar.root_id"
                " FROM agent_registry ar"
                " LEFT JOIN roots_register rr"
                "   ON rr.root_id = ar.root_id AND rr.valid_to IS NULL"
                " WHERE ar.valid_to IS NULL"
            ).fetchall()
        except sqlite3.Error as e:
            raise RegistryUnavailable(f"agent_registry unreadable: {e}") from e
    finally:
        conn.close()

    claims = {}
    for agent_name, rel_path, agent_file, root_id in rows:
        # agent_file is stored apex-relative; resolve against the apex so the
        # comparison key is a single canonical form.
        p = Path(agent_file)
        if not p.is_absolute():
            p = agents_dir.parent.parent / agent_file
        # root_id rides along so a move-aware caller can gate the past-rel judgement
        # on THIS identity's own history (see `marker_is_current_or_past_rel`); it is
        # None only for a legacy pre-spine row, which has no history to consult.
        claims[_key(p)] = {"agent_name": agent_name, "rel_path": rel_path,
                           "root_id": root_id}
    return claims


def _key(path):
    """Canonical comparison key for a path — absolute, symlinks NOT followed,
    case-folded.

    `Path.resolve()` would follow a symlinked `agents/` and let a claim match a
    file outside the directory. `absolute()` + manual `..` collapse keeps the
    comparison lexical, which is what an ownership check wants.

    Case-FOLDED because `.claude/agents/` lives on a case-insensitive, case-
    preserving mount (9p/drvfs): a claim stored as `zMisc-pj.md` and the same
    dirent later listed as `zmisc-pj.md` are ONE file, and a case-sensitive
    comparison would call cboot's own file foreign — purge would then mislabel it
    "hand-authored" forever and the project's re-claim would bump to `-2`. The
    result is only ever a dict/comparison key, never a path to open, so folding is
    safe; its folding neighbour `roots_register.deconflict` (the relocated
    de-confliction rule) and the de-confliction glob fold for the same reason.
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    parts = []
    for part in p.parts:
        if part == "..":
            if parts and parts[-1] not in ("/", "\\"):
                parts.pop()
        elif part != ".":
            parts.append(part)
    return Path(*parts).as_posix().casefold()


def owns(path, claims):
    """True iff `path` is currently claimed by the registry.

    Pure path lookup. Does not stat, open, decode, or parse the file. This is
    the ONLY question a caller may ask before writing to or deleting a file in
    the agents directory.
    """
    return _key(path) in claims


def is_tmp_artifact(path):
    """True for cboot's own `<name>.md.tmp` staging leftovers.

    These are never hand-authored — they exist only as the staging half of an
    interrupted `tmp + os.replace` write, so both cboot and purge may remove
    them unconditionally.
    """
    return Path(path).name.endswith(TMP_SUFFIX)


# ── Spine history (move-aware ownership input) ───────────────────────

def spine_history(conn):
    """`{root_id: {casefolded rel_path, ...}}` over ALL roots_register rows.

    Every rel_path each identity has EVER held — current AND closed spine rows —
    keyed on identity. This is the input `marker_is_current_or_past_rel` consults to
    tell a MOVED-but-ours file (its marker names a rel this identity used to sit at)
    from a genuinely hand-edited one. Read once from an already-open connection; the
    caller supplies the connection (cboot's projection pass and `/roots` both hold
    one), so this never opens the db itself.
    """
    hist = {}
    for root_id, rel in conn.execute(
            "SELECT root_id, rel_path FROM roots_register"):
        hist.setdefault(root_id, set()).add(rel.casefold())
    return hist


def read_spine_history(db_path):
    """`spine_history` for a caller that has NO open connection — purge.

    Opens roots.db truly read-only (`_open_ro`) and returns the same
    `{root_id: {casefolded rel_path, ...}}`. Raises RegistryUnavailable on any
    failure; a deleter that cannot read the spine must degrade to an EMPTY history,
    which makes `marker_is_current_or_past_rel` collapse to exactly `marker_matches`
    — the safe, preserve-more direction.
    """
    conn = _open_ro(db_path)
    try:
        try:
            return spine_history(conn)
        except sqlite3.Error as e:
            raise RegistryUnavailable(f"roots_register unreadable: {e}") from e
    finally:
        conn.close()


# ── Marker (advisory only) ───────────────────────────────────────────

def render_marker(rel_path, generated_at):
    """The banner line written as the first body line of a generated file.

    `rel_path` is JSON-quoted so a quote, backslash, or newline in a folder name
    round-trips instead of terminating the attribute early.
    """
    return (f'<!-- cboot:agent root={json.dumps(rel_path)} '
            f'generated="{generated_at}" -->')


def marker_matches(path, rel_path):
    """True if `path` still carries OUR marker for `rel_path`.

    The single test for "has a human been in this file". Both callers use it:
    cboot to decide whether it may rewrite a file it claims, purge to decide
    whether it may delete one. A missing marker and a marker that has been
    retargeted to some other root mean the same thing — someone edited the file —
    and splitting that judgement across two callers is how they came to disagree.

    This is NOT an ownership test. Ownership is `owns()`. This only ever makes a
    caller do LESS: cboot skips a rewrite, purge skips a delete.
    """
    return read_marker(path) == rel_path


def marker_is_current_or_past_rel(path, current_rel, root_id, hist):
    """True if `path` still carries OUR marker — for the CURRENT rel_path, OR for
    any rel_path this identity USED to hold (a relink moved it before it was
    re-projected). The MOVE-AWARE superset of `marker_matches`.

    A relink versions the spine but leaves the agent file's marker naming the PRIOR
    rel_path until the next materialize. Five call sites must agree that such a file
    is still ours-and-current-enough — four ACT on the judgement: cboot's close-pass
    (sweep it on opt-out) and held-refresh (rewrite it in place), `/roots`
    `_sweep_owned_file` (sweep it on disable/rename), and purge (treat it as ours,
    not hand-authored); `compute_drift` alone is report-only (do NOT flag it
    diverged). Splitting that judgement across the callers is how bare
    `marker_matches` STRANDED a moved file in three of them; this is the single
    judgement they now share.

    `hist` is `{root_id: {casefolded rel_path, ...}}` (see `spine_history` /
    `read_spine_history`). The past-rel arm is gated on THIS `root_id`'s own history,
    so the recogniser only ever widens to MORE of the OWNING identity's files, never
    a foreign one; and an empty/missing `hist` degrades to exactly `marker_matches`.
    Like `marker_matches`, the caller must have established ownership by path
    (`owns()`) first, and this only ever makes it do LESS work on an already-owned
    file. `current_rel` is matched EXACTLY (as `marker_matches` does); the past
    arm is case-folded to mirror the mount's case-insensitivity.
    """
    marker_rel = read_marker(path)
    if marker_rel is None:
        return False
    if marker_rel == current_rel:
        return True
    return marker_rel.casefold() in hist.get(root_id, set())


def read_marker(path):
    """Return the marker's `root=` value, or None.

    ADVISORY. Used only to report tampering on a file the registry already says
    is ours, and to render a friendlier warning about a file it says is not.
    Never a basis for writing or deleting.

    Never raises: an unreadable or undecodable file yields None. Deciding
    ownership never requires decoding a file, so a file we cannot read is
    simply a file with no readable marker.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    body = _body_after_frontmatter(text)
    for line in body.split("\n"):
        if not line.strip():
            continue
        m = _MARKER_RE.fullmatch(line.strip())
        if not m:
            return None
        try:
            return json.loads(m.group("root"))
        except ValueError:
            return None
    return None


# Frontmatter fences: a line that is exactly `---`. `re.M` `$` treats only \n
# and \r\n as breaks, so a stray form-feed inside a value cannot fake a fence
# (which `str.splitlines()` would have done).
_FM_FENCE_RE = re.compile(r"^---[ \t]*$", re.M)


def _body_after_frontmatter(text):
    """Text following a leading `---` … `---` block, or the whole text."""
    m = _FM_FENCE_RE.match(text)
    if not m:
        return text
    closing = _FM_FENCE_RE.search(text, m.end())
    if not closing:
        return text
    return text[closing.end():]


# ── Name derivation and YAML-safe emission ───────────────────────────

def derive_agent_name(folder_basename):
    """Folder basename -> candidate @name.

    Leading punctuation is stripped (`~majel` -> `majel`); case is kept
    (`zMisc` stays `zMisc`). Every remaining character outside [A-Za-z0-9-]
    collapses to a hyphen, so spaces, unicode, and a `:` (which Claude Code
    would refuse to load as a file stem) can never reach a filename.
    """
    s = unicodedata.normalize("NFKC", folder_basename)
    s = s.lstrip("~._-+#@!$%^&*()[]{}<>|/\\'\" \t")
    s = re.sub(r"[^A-Za-z0-9-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def suffixed(base):
    """Append the project-agent namespace suffix to a clean base name.

    An empty base stays empty — an unusable name is caught by the caller, never
    turned into a bare `-pj`.
    """
    return f"{base}{SUFFIX}" if base else base


def desuffix(name):
    """Recover the base from a suffixed @name: strip exactly ONE trailing SUFFIX.

    The inverse of `suffixed` for the ordinary case, and the guard that keeps
    `agent_optin.requested_name` a BASE name so re-projecting it never doubles the
    suffix (`x` -> `x-pj`, not `x-pj-pj`). It is NOT idempotent, and deliberately
    so: a literal `*-pj` FOLDER derives base `draw2-pj`, whose agent name is
    `draw2-pj-pj`, whose base is `draw2-pj` again — stripping exactly one suffix
    preserves the intended disjoint-namespace double. A name that does not end in
    the suffix (or that is nothing but the suffix) is returned unchanged.
    """
    if name and len(name) > len(SUFFIX) and name.endswith(SUFFIX):
        return name[:-len(SUFFIX)]
    return name


def yaml_scalar(value):
    """Emit a string as a YAML scalar that always reads back as that string.

    Unquoted, `name: 2025` parses as an integer and `name: null` / `no` / `true`
    as YAML literals — so the agent's identity silently becomes something other
    than what was written. JSON's string form is valid YAML and round-trips
    exactly, so it is used unconditionally rather than by a "does this look
    dangerous" test that would need to encode all of YAML 1.1's scalar rules.
    """
    return json.dumps(value, ensure_ascii=False)
