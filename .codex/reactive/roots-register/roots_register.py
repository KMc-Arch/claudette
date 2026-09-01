"""The single writer of identity and claim rows — ONE implementation.

Every durable identity/claim mutation in the root-identity system passes through
this module. `roots_register` (the identity spine), `agent_registry` (the SCD2
@name claim ledger), and `agent_optin` (the decision) are written HERE and
nowhere else. The decision writers are a matched pair: `accept` records an
ENABLED opt-in decision and `decline` a DISABLED one — both write ONLY the
durable decision, never a claim. `open_claim` records an ENABLED opt-in AND opens
the @name claim: it is what boot's projection pass calls once a decision already
stands, after de-confliction has chosen the @name. Boot's first-touch prompt
records the decision (`accept`/`decline`); the projection pass opens the claim
(`open_claim`); the `/roots` reconfigure command and `/move-project` also CALL
these functions; none of them writes those tables directly. Two divergent copies of claim-mutation is exactly the bug the shared
`agent_ownership` and `transcript_slug` modules already exist to make
impossible — this is that rule a third time, for the writes.

Contract shared by every write function:

  * `conn` is an open connection from the house factory
    (`^/.codex/reactive/sqlite/sqlite.py`): deferred transactions, foreign_keys
    ON, row_factory Row.
  * A mutating function opens a guarded `BEGIN IMMEDIATE` (only if the caller has
    not already opened a transaction) so its several statements are one atomic
    unit — then executes, but DOES NOT commit. The CALLER commits. That lets a
    caller compose ops (mint + open_claim, say) into a single transaction and
    commit once; on any raise the caller declines to commit and `close()` rolls
    the whole thing back. This mirrors `cboot._migrate_to_v1`.
  * Every write records a `change_reason` (spine / claim open) or `close_reason`
    (claim close) and stamps ISO-8601 UTC `valid_from` / `valid_to`.

Identity rules this module enforces:

  * `root_id` is handed out by a monotonic `MAX(root_id)+1` allocator and NEVER
    reused — the allocator counts closed rows too.
  * A move (`relink`) PRESERVES `root_id`: the spine row is versioned (old row
    closed, new opened under the SAME id) and the claim is left untouched, so a
    live project's agent survives a relocation. `relink` also re-slugs the Claude
    Code transcript store so the session history follows the move.

Name derivation and de-confliction are NOT reimplemented here: `agent_ownership`
owns `derive_agent_name` / `suffixed` / `RESERVED_NAMES` (re-exported below so a
writer reaches them through this single surface), and `deconflict` is the boot
Pass-A/Pass-B `_free_name` logic relocated — grandfathers win.
"""

import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_module(path):
    """Load a house meta-script from a filesystem path (mirrors cboot)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AO = None
_TS = None


def _ao():
    """The shared ownership/naming module — loaded once, never reimplemented."""
    global _AO
    if _AO is None:
        _AO = _load_module(_HERE.parent / "agent-ownership" / "agent_ownership.py")
    return _AO


def _ts():
    """The shared transcript-slug module — loaded once."""
    global _TS
    if _TS is None:
        _TS = _load_module(_HERE.parent / "transcript-slug" / "transcript_slug.py")
    return _TS


# Re-exports: a writer reaches name derivation through the single writer surface
# rather than importing agent_ownership a second time. Thin delegates, never a
# reimplementation — the rule still lives in exactly one module.
def derive_agent_name(folder_basename):
    """Delegate to agent_ownership.derive_agent_name (folder basename -> @name)."""
    return _ao().derive_agent_name(folder_basename)


def suffixed(base):
    """Delegate to agent_ownership.suffixed (append the -pj namespace suffix)."""
    return _ao().suffixed(base)


def reserved_names():
    """The reserved @names agent_ownership forbids (a frozenset)."""
    return _ao().RESERVED_NAMES


def _now_iso():
    """ISO-8601 UTC, second precision — the house timestamp shape (now_iso)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _begin(conn):
    """Open an IMMEDIATE transaction unless the caller already opened one.

    Taking the write lock up front makes a multi-statement op atomic; joining an
    already-open caller transaction is what lets mint + open_claim commit
    together. Mirrors `cboot._migrate_to_v1`'s guard exactly.
    """
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


# close_reasons that mean a HUMAN turned an agent off (as opposed to the project
# vanishing, being renamed, or a write failing). ONLY these also flip the durable
# opt-in decision to enabled=0; every other close leaves the decision to BE an
# agent standing, so a moved/renamed/temporarily-gone project is not silently
# un-decided. The mapping is documented here so callers pass a reason, not a flag.
_DISABLE_REASONS = frozenset({"opted-out", "disabled"})


def _current_spine(conn, root_id):
    """The current (valid_to IS NULL) roots_register row for root_id, or None."""
    return conn.execute(
        "SELECT id, root_id, rel_path, is_apex FROM roots_register"
        " WHERE root_id = ? AND valid_to IS NULL", (root_id,)).fetchone()


def _spine_rel_path(conn, root_id):
    """The current spine rel_path for root_id; raise if the identity has no
    current spine row (a claim cannot precede the identity it belongs to)."""
    row = _current_spine(conn, root_id)
    if row is None:
        raise ValueError(
            "no current roots_register row for root_id %r — mint (or relink) the "
            "identity before opening a claim" % (root_id,))
    return row["rel_path"]


# ── Identity spine ───────────────────────────────────────────────────

def next_root_id(conn):
    """The next root_id to hand out: monotonic MAX+1 over ALL rows (closed rows
    included), so an id is never reused."""
    return conn.execute(
        "SELECT COALESCE(MAX(root_id), 0) + 1 FROM roots_register").fetchone()[0]


def mint(conn, rel_path, is_apex=0):
    """Canonicalize a NEW root: allocate a root_id and open its spine row.

    Refuses (raises ValueError) when a CURRENT spine row already occupies
    `rel_path` (compared COLLATE NOCASE — case-variant paths are one directory on
    this mount): an existing identity there is a relink, not a mint. Records
    change_reason='canonicalized'. Returns the new root_id.
    """
    _begin(conn)
    clash = conn.execute(
        "SELECT root_id FROM roots_register"
        " WHERE rel_path = ? COLLATE NOCASE AND valid_to IS NULL",
        (rel_path,)).fetchone()
    if clash is not None:
        raise ValueError(
            "a current root (root_id=%d) already occupies rel_path %r — that is a "
            "relink, not a mint" % (clash["root_id"], rel_path))
    root_id = next_root_id(conn)
    conn.execute(
        "INSERT INTO roots_register (root_id, rel_path, is_apex, change_reason,"
        " valid_from, valid_to) VALUES (?, ?, ?, 'canonicalized', ?, NULL)",
        (root_id, rel_path, 1 if is_apex else 0, _now_iso()))
    return root_id


# ── @name claims ─────────────────────────────────────────────────────

def open_claim(conn, root_id, agent_name, source_folder, agent_file,
               deconflicted_from=None, change_reason="opted-in", *,
               requested_name=None, description=None, decided_by="prompt"):
    """Open a current agent_registry claim for `root_id` and record the opt-in.

    Inserts a current (`valid_to IS NULL`) claim keyed on `root_id`, freezing the
    root's CURRENT spine `rel_path` as the claim-time location. Also upserts the
    `agent_optin` decision for `root_id` to enabled=1.

    The positional signature is the contract; the keyword-only extras honour the
    documented override points ("decided_by='prompt' unless caller overrides")
    without disturbing it. `requested_name` defaults to `agent_name`, and
    `description` (nullable) is written to both rows so the NOT-NULL columns are
    satisfied without asserting a value the caller did not give.
    """
    _begin(conn)
    rel_path = _spine_rel_path(conn, root_id)
    stamp = _now_iso()
    conn.execute(
        "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
        " deconflicted_from, description, agent_file, valid_from, valid_to,"
        " change_reason, close_reason, root_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)",
        (agent_name, rel_path, source_folder, deconflicted_from, description,
         agent_file, stamp, change_reason, root_id))
    conn.execute(
        "INSERT INTO agent_optin (root_id, rel_path, enabled, requested_name,"
        " description, decided_at, decided_by)"
        " VALUES (?, ?, 1, ?, ?, ?, ?)"
        " ON CONFLICT(root_id) DO UPDATE SET"
        " enabled = 1, rel_path = excluded.rel_path,"
        " requested_name = excluded.requested_name,"
        " description = excluded.description,"
        " decided_at = excluded.decided_at, decided_by = excluded.decided_by",
        (root_id, rel_path,
         agent_name if requested_name is None else requested_name,
         description, stamp, decided_by))


def accept(conn, root_id, *, requested_name=None, description=None,
           decided_by="prompt"):
    """Record an ACCEPT decision for `root_id`: agent_optin enabled=1, no claim.

    The enabled complement of `decline`, and the decision half of `open_claim`
    without the @name claim. Boot's first-touch opt-in calls this to record the
    human's YES; the projection pass (`generate_agents`) later derives + de-
    conflicts the @name and opens the claim via `open_claim`. Splitting the
    decision from the claim is what keeps de-confliction (which needs the whole
    live agents directory) in the projection pass rather than the prompt — a claim
    pre-opened here would make every enabled root read as already-claimed.

    The `agent_optin` row for `root_id` is upserted to enabled=1, freezing the
    root's CURRENT spine `rel_path` as the decision-time location. Opens a guarded
    transaction and leaves the commit to the caller, like every writer here.
    """
    _begin(conn)
    rel_path = _spine_rel_path(conn, root_id)
    stamp = _now_iso()
    conn.execute(
        "INSERT INTO agent_optin (root_id, rel_path, enabled, requested_name,"
        " description, decided_at, decided_by)"
        " VALUES (?, ?, 1, ?, ?, ?, ?)"
        " ON CONFLICT(root_id) DO UPDATE SET"
        " enabled = 1, rel_path = excluded.rel_path,"
        " requested_name = excluded.requested_name,"
        " description = excluded.description,"
        " decided_at = excluded.decided_at, decided_by = excluded.decided_by",
        (root_id, rel_path, requested_name, description, stamp, decided_by))


def decline(conn, root_id, *, requested_name=None, description=None,
            decided_by="prompt"):
    """Record a DECLINE decision for `root_id`: agent_optin enabled=0, no claim.

    The disabled complement of `open_claim`'s enabled opt-in. A declined root has
    no @name claim, so this writes ONLY the durable decision — it never touches
    `agent_registry`. The `agent_optin` row for `root_id` is upserted to enabled=0,
    freezing the root's CURRENT spine `rel_path` as the decision-time location.
    `requested_name` and `description` are nullable: a decline records no chosen
    name by default. Like the other writers it opens a guarded transaction and
    leaves the commit to the caller.
    """
    _begin(conn)
    rel_path = _spine_rel_path(conn, root_id)
    stamp = _now_iso()
    conn.execute(
        "INSERT INTO agent_optin (root_id, rel_path, enabled, requested_name,"
        " description, decided_at, decided_by)"
        " VALUES (?, ?, 0, ?, ?, ?, ?)"
        " ON CONFLICT(root_id) DO UPDATE SET"
        " enabled = 0, rel_path = excluded.rel_path,"
        " requested_name = excluded.requested_name,"
        " description = excluded.description,"
        " decided_at = excluded.decided_at, decided_by = excluded.decided_by",
        (root_id, rel_path, requested_name, description, stamp, decided_by))


def close_claim(conn, root_id, close_reason):
    """Close the current agent_registry claim for `root_id`.

    Sets valid_to=now and `close_reason` on the open claim (a no-op if none is
    open — the SCD2 history is left intact either way). When `close_reason` is a
    HUMAN disable (see `_DISABLE_REASONS`: 'opted-out' / 'disabled') the durable
    opt-in decision is also flipped to enabled=0; a 'root-removed' / 'renamed' /
    'write-failed' close leaves the decision to be an agent standing.
    """
    _begin(conn)
    conn.execute(
        "UPDATE agent_registry SET valid_to = ?, close_reason = ?"
        " WHERE root_id = ? AND valid_to IS NULL",
        (_now_iso(), close_reason, root_id))
    if close_reason in _DISABLE_REASONS:
        conn.execute(
            "UPDATE agent_optin SET enabled = 0 WHERE root_id = ?", (root_id,))


def rename_claim(conn, root_id, new_agent_name, new_agent_file,
                 deconflicted_from=None):
    """Rename a live claim: close the current one and open a new one, same id.

    The current claim is closed (close_reason='renamed', which is NOT a disable,
    so the opt-in decision is untouched) and a fresh claim opened under
    `new_agent_name` (change_reason='renamed'). The claim-time source folder and
    description carry forward from the row being closed. Grandfather/reserved
    re-checking is the caller's job — it derives `new_agent_name` via `deconflict`
    and passes the resulting `deconflicted_from`.
    """
    _begin(conn)
    held = conn.execute(
        "SELECT source_folder, description FROM agent_registry"
        " WHERE root_id = ? AND valid_to IS NULL", (root_id,)).fetchone()
    if held is None:
        raise ValueError("no current claim for root_id %r to rename" % (root_id,))
    close_claim(conn, root_id, "renamed")
    open_claim(conn, root_id, new_agent_name, held["source_folder"],
               new_agent_file, deconflicted_from=deconflicted_from,
               change_reason="renamed", requested_name=new_agent_name,
               description=held["description"])


# ── Relink (a move — identity preserved) ─────────────────────────────

def relink(conn, root_id, new_rel_path, *, home=None):
    """Move a root to `new_rel_path`, identity preserved, transcripts following.

    The current spine row is closed and a new current one opened with the SAME
    `root_id` (change_reason='relinked'); the agent_registry claim is left
    untouched — its root_id is stable, so a live project's agent survives the
    move. THEN the Claude Code transcript store is re-slugged to follow.

    A DESTINATION-store collision is refused, not clobbered. If a store already
    exists at the new slug (the user opened Claude in the new location before
    relinking), `os.rename` cannot merge the two and silently overwriting one would
    destroy real session history — so this raises a clear, catchable `ValueError`
    with the DB half untouched (the check runs BEFORE any write). Callers report it
    and carry on (`/roots` `_do_relink`, boot's first-touch relink), never crash.

    Order is otherwise load-bearing: the DB writes happen FIRST, the filesystem
    rename SECOND. Should the rename still fail (a race that created the
    destination after the pre-check, a permission error), the DB half is rolled
    back and a `ValueError` raised, so the identity is never left moved while its
    transcripts stayed put. The rename is a COLD `os.rename` (this mount ghosts
    hot-tree renames) and is skipped silently when the old store does not exist.

    `home` overrides `Path.home()` (the store lives under `~/.claude/projects/`),
    for hermetic testing. The apex directory is derived from the connection's own
    database file, so the module needs no apex argument.
    """
    _begin(conn)
    spine = _current_spine(conn, root_id)
    if spine is None:
        raise ValueError(
            "no current roots_register row for root_id %r to relink" % (root_id,))
    old_rel_path = spine["rel_path"]

    # Resolve both transcript stores up front and REFUSE a destination collision
    # BEFORE any DB write, so a pre-existing store is never clobbered and the DB is
    # never left with identity moved but transcripts un-moved.
    apex = _apex_root(conn)
    home_dir = Path(home) if home is not None else Path.home()
    projects = home_dir / ".claude" / "projects"
    slug = _ts().project_slug
    old_store = projects / slug(apex / old_rel_path)
    new_store = projects / slug(apex / new_rel_path)
    move_store = old_store != new_store and old_store.exists()
    if move_store and new_store.exists():
        raise ValueError(
            "cannot relink root_id %r onto %r: a transcript store already exists at "
            "the destination (%s). os.rename cannot merge two stores; move or remove "
            "the existing store, then relink." % (root_id, new_rel_path, new_store))

    stamp = _now_iso()
    conn.execute("UPDATE roots_register SET valid_to = ? WHERE id = ?",
                 (stamp, spine["id"]))
    conn.execute(
        "INSERT INTO roots_register (root_id, rel_path, is_apex, change_reason,"
        " valid_from, valid_to) VALUES (?, ?, ?, 'relinked', ?, NULL)",
        (root_id, new_rel_path, spine["is_apex"], stamp))

    # Re-slug the transcript store: DB first (above), FS second (here).
    if move_store:
        try:
            os.rename(old_store, new_store)
        except OSError as e:
            # A rename that fails after the DB writes (a race, a permission error)
            # must not strand the identity at the new path with its transcripts
            # left behind. Roll the DB half back and surface a catchable error.
            conn.rollback()
            raise ValueError(
                "relink of root_id %r to %r could not move its transcript store "
                "(%s -> %s): %s — the move was rolled back." %
                (root_id, new_rel_path, old_store, new_store, e)) from e


def _apex_root(conn):
    """The apex directory: the parent of the `.state/` that holds this roots.db.

    Read from the connection's own `PRAGMA database_list` (the resolved main
    database file), so relink needs no apex argument and cannot disagree with the
    db it is writing.
    """
    for row in conn.execute("PRAGMA database_list"):
        # row: (seq, name, file)
        if row[1] == "main" and row[2]:
            return Path(row[2]).resolve().parent.parent
    raise ValueError("connection has no on-disk main database (cannot relink)")


# ── De-confliction (grandfathers win) ────────────────────────────────

def deconflict(base, taken, reserved):
    """The first non-colliding variant of `base`. Grandfathers win.

    `taken` is the collection of @names already held by CURRENT claims and files;
    `reserved` the names Claude Code forbids. If `base` collides with neither it
    is returned unchanged — the incumbent keeps its name — otherwise `-2`, `-3`, …
    are appended until one is free, in whatever (already-suffixed) space `base` is
    expressed. Comparison is case-folded because the mount is case-insensitive, so
    `Foo` and `foo` are one name (matching `agent_ownership._key`).

    This is the boot Pass-A/Pass-B logic (`cboot._free_name`) relocated, returning
    just the chosen name; a caller that needs the `deconflicted_from` provenance
    compares the result against `base`.
    """
    low = {t.casefold() for t in taken} | {r.casefold() for r in reserved}
    if base and base.casefold() not in low:
        return base
    stem = base or "agent"
    n = 2
    while ("%s-%d" % (stem, n)).casefold() in low:
        n += 1
    return "%s-%d" % (stem, n)
