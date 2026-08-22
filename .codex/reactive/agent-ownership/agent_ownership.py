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

def claims_for(db_path, agents_dir):
    """Return the set of absolute agent-file paths cboot currently claims.

    Reads the CURRENT (`valid_to IS NULL`) rows of the durable SCD2
    `agent_registry`. Returns {resolved_abs_posix_path: {agent_name, rel_path}}.

    Opened read-only and immutable — `mode=ro` alone still creates/updates
    `-wal`/`-shm` sidecars on a WAL database; `immutable=1&mode=ro` is the true
    read-only open (see .state/memory/reference_sqlite_wal_readonly.md).

    Raises RegistryUnavailable on any failure. Never returns a partial answer.
    """
    db_path = Path(db_path)
    agents_dir = Path(agents_dir)
    if not db_path.is_file():
        raise RegistryUnavailable(f"roots.db not found: {db_path}")

    uri = "file:" + db_path.resolve().as_posix().replace("?", "%3f").replace("#", "%23")
    try:
        conn = sqlite3.connect(uri + "?immutable=1&mode=ro", uri=True)
    except sqlite3.Error as e:
        raise RegistryUnavailable(f"roots.db unopenable: {e}") from e
    try:
        try:
            rows = conn.execute(
                "SELECT agent_name, rel_path, agent_file FROM agent_registry"
                " WHERE valid_to IS NULL"
            ).fetchall()
        except sqlite3.Error as e:
            raise RegistryUnavailable(f"agent_registry unreadable: {e}") from e
    finally:
        conn.close()

    claims = {}
    for agent_name, rel_path, agent_file in rows:
        # agent_file is stored apex-relative; resolve against the apex so the
        # comparison key is a single canonical form.
        p = Path(agent_file)
        if not p.is_absolute():
            p = agents_dir.parent.parent / agent_file
        claims[_key(p)] = {"agent_name": agent_name, "rel_path": rel_path}
    return claims


def _key(path):
    """Canonical comparison key for a path — absolute, symlinks NOT followed.

    `Path.resolve()` would follow a symlinked `agents/` and let a claim match a
    file outside the directory. `absolute()` + manual `..` collapse keeps the
    comparison lexical, which is what an ownership check wants.
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
    return Path(*parts).as_posix()


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


# ── Marker (advisory only) ───────────────────────────────────────────

def render_marker(rel_path, generated_at):
    """The banner line written as the first body line of a generated file.

    `rel_path` is JSON-quoted so a quote, backslash, or newline in a folder name
    round-trips instead of terminating the attribute early.
    """
    return (f'<!-- cboot:agent root={json.dumps(rel_path)} '
            f'generated="{generated_at}" -->')


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


def yaml_scalar(value):
    """Emit a string as a YAML scalar that always reads back as that string.

    Unquoted, `name: 2025` parses as an integer and `name: null` / `no` / `true`
    as YAML literals — so the agent's identity silently becomes something other
    than what was written. JSON's string form is valid YAML and round-trips
    exactly, so it is used unconditionally rather than by a "does this look
    dangerous" test that would need to encode all of YAML 1.1's scalar rules.
    """
    return json.dumps(value, ensure_ascii=False)
