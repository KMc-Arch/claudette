#!/usr/bin/env python3
"""roots.py — the `/roots` reconfigure command.

`/roots` RE-configures identity decisions already made — the out-of-band
complement of boot's first-touch prompt. Where boot detects a new root and asks
once, `/roots` lets a human revisit that answer at any quiet moment: turn an
agent off or a declined root on, rename an @name, relink an identity whose
directory moved out of band, or canonicalize a walked root the mint never
reached.

It is a THIN wrapper. It carries NO identity/claim write SQL of its own — every
mutation dispatches to a function in the shared writer module
(`^/.codex/reactive/roots-register/roots_register.py`), the SOLE writer of
`roots_register`/`agent_registry`/`agent_optin` identity rows. Boot calls that
same module, and `/move-project` will once it lands on this branch; three copies of
claim-mutation is exactly the divergence bug the shared module exists to prevent.
`/move-project` will import the module's `relink()` DIRECTLY — never this command —
so nothing here needs to be exported for it.

Apex-only: `.claude/agents/` (and thus the whole addressable-agent inventory) is
never propagated to a child, so a child `/roots` would have nothing to reconfigure.

Drift surface (read-only, computed from the tables — never a re-walk):
  * unlinked   — rows in the transient `roots` walk cache with `canonical_id IS
                 NULL`: a walked directory the mint never canonicalized.
  * orphaned   — CURRENT `roots_register` rows whose `rel_path` is absent from the
                 last walk (`roots`, COLLATE NOCASE): the directory the identity
                 points at is gone.
  * divergence — CURRENT `agent_registry` claims whose on-disk agent file no
                 longer carries our marker. REPORT-ONLY, everywhere: a diverged
                 file is never rewritten or deleted (a human has been in it).

TTY discipline: an interactive mutation requires BOTH stdin and stdout to be a
real terminal (mirroring cboot's `_interactive`). A non-TTY invocation prints the
drift report and exits 0, mutating nothing — safe to run from a hook or a script.

    python .codex/explicit/roots/roots.py [--project-root ^]
"""

from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import sys
from pathlib import Path

# The apex the shared modules live under. roots.py sits at
# ^/.codex/explicit/roots/roots.py, so parents[3] is the apex — the same
# derivation purge.py uses. This locates the framework MODULES; the apex the
# command OPERATES on comes from --project-root (they coincide for an apex
# invocation, which is the only supported one).
_HERE = Path(__file__).resolve()
_APEX = _HERE.parents[3]
_AO_PATH = _APEX / ".codex" / "reactive" / "agent-ownership" / "agent_ownership.py"
_RR_PATH = _APEX / ".codex" / "reactive" / "roots-register" / "roots_register.py"
_SQLITE_PATH = _APEX / ".codex" / "reactive" / "sqlite" / "sqlite.py"

_AGENTS_REL = ".claude/agents"


def _load(path):
    """Load a house meta-script from a filesystem path (mirrors cboot/purge)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AO = _RR = _SQLITE = None


def _ao():
    global _AO
    if _AO is None:
        _AO = _load(_AO_PATH)
    return _AO


def _rr():
    global _RR
    if _RR is None:
        _RR = _load(_RR_PATH)
    return _RR


def _sqlite():
    global _SQLITE
    if _SQLITE is None:
        _SQLITE = _load(_SQLITE_PATH)
    return _SQLITE


def _interactive():
    """A mutation is only ever offered at a real terminal. Mirrors cboot's guard:
    both stdin AND stdout must be a TTY — /roots is also runnable from a hook or a
    script, where a prompt would hang with nobody to answer it."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _connect_ro(db_path):
    """A true read-only connection (immutable=1&mode=ro) for the drift report.

    `mode=ro` alone still creates/updates -wal/-shm sidecars on a WAL database;
    `immutable=1&mode=ro` is the genuinely read-only open (the same the ownership
    module uses). Suitable for a committed roots.db — the single-session invariant
    means no concurrent writer holds an uncheckpointed WAL.
    """
    p = Path(db_path)
    uri = "file:" + p.resolve().as_posix().replace("?", "%3f").replace("#", "%23")
    conn = sqlite3.connect(uri + "?immutable=1&mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


# ── Drift (read-only) ────────────────────────────────────────────────

class DriftReport:
    """The three drift classes computed from the tables (no re-walk).

    Each attribute is a list of plain dicts so callers (the report, the menu, the
    tests) read fields by name without depending on the row_factory.
    """

    def __init__(self, unlinked, orphaned, divergence):
        self.unlinked = unlinked
        self.orphaned = orphaned
        self.divergence = divergence

    def is_clean(self):
        return not (self.unlinked or self.orphaned or self.divergence)


def compute_drift(conn, apex):
    """Compute the three drift classes from the current table state.

    * unlinked   — `roots` rows with `canonical_id IS NULL`.
    * orphaned   — CURRENT `roots_register` rows whose `rel_path` is not present in
                   `roots` (COLLATE NOCASE); the @name of a current claim on that
                   identity, if any, is attached for the report.
    * divergence — CURRENT `agent_registry` claims whose on-disk agent file fails
                   `marker_matches` against the claim's current rel_path (marker
                   altered/removed, or the file is missing). Report-only.

    `apex` resolves each claim's apex-relative `agent_file` to an absolute path.
    A missing `roots` table (boot never ran) yields empty unlinked/orphaned rather
    than raising — the report says so.
    """
    ao = _ao()
    have_roots = _table_exists(conn, "roots")

    unlinked = []
    if have_roots:
        for row in conn.execute(
                "SELECT rel_path, name, abs_path FROM roots"
                " WHERE canonical_id IS NULL ORDER BY rel_path"):
            unlinked.append({"rel_path": row["rel_path"], "name": row["name"],
                             "abs_path": row["abs_path"]})

    orphaned = []
    if have_roots:
        rows = conn.execute(
            "SELECT rr.root_id, rr.rel_path, rr.is_apex,"
            " (SELECT ar.agent_name FROM agent_registry ar"
            "   WHERE ar.root_id = rr.root_id AND ar.valid_to IS NULL) AS agent_name"
            " FROM roots_register rr"
            " WHERE rr.valid_to IS NULL"
            "   AND NOT EXISTS (SELECT 1 FROM roots r"
            "                   WHERE r.rel_path = rr.rel_path COLLATE NOCASE)"
            " ORDER BY rr.rel_path")
        for row in rows:
            orphaned.append({"root_id": row["root_id"], "rel_path": row["rel_path"],
                             "is_apex": row["is_apex"], "agent_name": row["agent_name"]})

    # Spine history so a relinked-but-unprojected file (marker still names a PAST rel
    # of its identity) is recognised as ours and NOT mis-reported as divergence —
    # the same move-aware judgement cboot's projection and the file-sweep use.
    hist = ao.spine_history(conn)
    divergence = []
    for row in conn.execute(
            "SELECT ar.agent_name, ar.agent_file, ar.root_id,"
            " COALESCE(rr.rel_path, ar.rel_path) AS cur_rel"
            " FROM agent_registry ar"
            " LEFT JOIN roots_register rr"
            "   ON rr.root_id = ar.root_id AND rr.valid_to IS NULL"
            " WHERE ar.valid_to IS NULL"):
        p = Path(row["agent_file"])
        target = p if p.is_absolute() else apex / p
        if ao.marker_is_current_or_past_rel(target, row["cur_rel"], row["root_id"], hist):
            continue
        reason = "file missing" if not target.exists() else "marker altered/removed"
        divergence.append({"agent_name": row["agent_name"],
                           "agent_file": row["agent_file"],
                           "root_id": row["root_id"], "rel_path": row["cur_rel"],
                           "reason": reason})

    return DriftReport(unlinked, orphaned, divergence)


def print_drift(drift, have_roots=True, out=None):
    """Render the drift report (the only output on a non-TTY invocation)."""
    out = out or sys.stdout
    p = lambda s="": print(s, file=out)
    p()
    p("  Root inventory drift")
    p("  ────────────────────")
    if not have_roots:
        p("  (no `roots` walk cache — run `python cboot.py --materialize-only` first;")
        p("   unlinked/orphaned cannot be computed without it)")
    if drift.is_clean():
        p("  clean — no unlinked roots, no orphaned identities, no divergence.")
        p()
        return
    if drift.unlinked:
        p()
        p("  UNLINKED — walked, no identity yet (canonicalize or relink):")
        for u in drift.unlinked:
            p(f"    - {u['rel_path']}")
    if drift.orphaned:
        p()
        p("  ORPHANED — identity points at a directory gone from the last walk:")
        for o in drift.orphaned:
            claim = f", @{o['agent_name']}" if o["agent_name"] else ""
            p(f"    - {o['rel_path']}  (root_id {o['root_id']}{claim})")
    if drift.divergence:
        p()
        p("  DIVERGENCE — claimed agent file lost our marker (report-only, never touched):")
        for d in drift.divergence:
            p(f"    - {d['agent_file']}  (@{d['agent_name']}) — {d['reason']}")
    p()


# ── Reconfigure operations (each dispatches to the shared writer) ─────
#
# None of these writes an identity/claim row directly; each calls a
# roots_register.py function and commits. File hygiene (removing an agent file a
# mutation just un-claimed) uses only the shared ownership module — no new SQL —
# and always runs AFTER the DB commit, mirroring relink's "DB first, FS second".

_UNSET = object()


def _sweep_owned_file(apex, agent_file, rel, root_id=None, hist=None):
    """Remove an agent file this session just un-claimed, guarded exactly like
    cboot's delete path: only OUR file, only inside `.claude/agents/`. A hand-edited
    or foreign file is preserved. Returns a status string for the report; never
    raises on a divergent/absent file.

    "OUR file" is the shared MOVE-AWARE judgement (`marker_is_current_or_past_rel`),
    so a relinked-but-not-yet-reprojected file — whose marker still names a PAST rel
    of THIS identity — is swept rather than STRANDED as "preserved-hand-edited". Pass
    `root_id` and `hist` (`agent_ownership.spine_history(conn)`) to enable the
    past-rel arm; omit them (or an empty `hist`) and the judgement degrades to exact
    `marker_matches`, which only ever preserves MORE."""
    if apex is None or not agent_file:
        return "skipped"
    ao = _ao()
    p = Path(agent_file)
    target = p if p.is_absolute() else Path(apex) / p
    try:
        parent = target.resolve().parent
        agents_dir = (Path(apex) / _AGENTS_REL).resolve()
    except OSError:
        return "unresolvable"
    if parent != agents_dir:
        return "outside-agents-dir"
    if not target.exists():
        return "no-file"
    if not ao.marker_is_current_or_past_rel(target, rel, root_id, hist or {}):
        return "preserved-hand-edited"
    try:
        target.unlink()
        return "removed"
    except OSError:
        return "unlink-failed"


def op_disable(conn, root_id, *, apex=None):
    """Turn an agent OFF: close the current claim ('opted-out', which also flips
    the durable opt-in decision to enabled=0) and sweep the now-un-claimed file.

    Dispatches the DB mutation to roots_register.close_claim; the file removal is
    guarded by the ownership marker (a hand-edited file is left in place). Returns
    the file-sweep status.
    """
    rr, ao = _rr(), _ao()
    held = conn.execute(
        "SELECT ar.agent_file, COALESCE(rr.rel_path, ar.rel_path) AS cur_rel"
        " FROM agent_registry ar"
        " LEFT JOIN roots_register rr"
        "   ON rr.root_id = ar.root_id AND rr.valid_to IS NULL"
        " WHERE ar.root_id = ? AND ar.valid_to IS NULL", (root_id,)).fetchone()
    # The identity's spine history, so the sweep recognises a relinked-but-unprojected
    # file (marker still names a PAST rel) as ours. Read BEFORE the close — close_claim
    # never touches roots_register, so it is stable either way.
    hist = ao.spine_history(conn)
    rr.close_claim(conn, root_id, "opted-out")
    conn.commit()
    if held is None:
        return "no-claim"
    return _sweep_owned_file(apex, held["agent_file"], held["cur_rel"],
                             root_id=root_id, hist=hist)


def op_enable(conn, root_id, *, requested_name=_UNSET, description=_UNSET):
    """Turn a declined root ON: record an ENABLED decision (agent_optin) via
    roots_register.accept, WITHOUT opening a claim.

    Projection choice (documented): `/roots` records the enabled decision only and
    leaves the agent FILE to boot — the same split boot itself uses (first-touch
    `accept` records the YES; the projection pass `generate_agents` derives the
    @name, de-conflicts against the whole live agents directory, opens the claim
    and writes the file). Reproducing that de-confliction here would duplicate the
    projection pass in a THIN command, so the caller is told to run
    `python cboot.py --materialize-only` to project the file. The root's existing
    requested_name/description are preserved unless overridden (accept would
    otherwise NULL them).
    """
    rr = _rr()
    prior = conn.execute(
        "SELECT requested_name, description FROM agent_optin WHERE root_id = ?",
        (root_id,)).fetchone()
    rn = (prior["requested_name"] if prior else None) \
        if requested_name is _UNSET else requested_name
    ds = (prior["description"] if prior else None) \
        if description is _UNSET else description
    rr.accept(conn, root_id, requested_name=rn, description=ds)
    conn.commit()


def op_rename(conn, root_id, new_base, *, taken=None, apex=None,
              agents_rel=_AGENTS_REL):
    """Rename an existing @name: de-conflict the requested base, then dispatch to
    roots_register.rename_claim (close 'renamed' + reopen, same root_id).

    `new_base` is a clean base name (the -pj suffix is added here). De-confliction
    is re-checked — grandfathers/reserved win — against `taken` (defaults to the
    @names of every OTHER current claim; the caller may pass an augmented set that
    also blocks foreign files on disk). The old agent file is swept (guarded), so
    the next `cboot --materialize-only` projects the renamed one. Returns the final
    suffixed @name.
    """
    rr, ao = _rr(), _ao()
    base = ao.derive_agent_name(new_base)
    if not base:
        raise ValueError("name empties out after sanitizing: %r" % (new_base,))
    if taken is None:
        taken = {r["agent_name"] for r in conn.execute(
            "SELECT agent_name FROM agent_registry"
            " WHERE valid_to IS NULL AND root_id != ?", (root_id,))}
    old = conn.execute(
        "SELECT ar.agent_file, COALESCE(rr.rel_path, ar.rel_path) AS cur_rel"
        " FROM agent_registry ar"
        " LEFT JOIN roots_register rr"
        "   ON rr.root_id = ar.root_id AND rr.valid_to IS NULL"
        " WHERE ar.root_id = ? AND ar.valid_to IS NULL", (root_id,)).fetchone()
    # Spine history for the move-aware sweep of the OLD file (a relinked-but-
    # unprojected file's marker names a PAST rel of this same identity). rename_claim
    # does not touch roots_register, so reading it up front is stable.
    hist = ao.spine_history(conn)
    want = ao.suffixed(base)
    name = rr.deconflict(want, taken, ao.RESERVED_NAMES)
    deconflicted_from = want if name != want else None
    agent_file = f"{agents_rel}/{name}.md"
    # `base` is the clean, unsuffixed name the human asked for — the value
    # agent_optin.requested_name must store (never the suffixed/de-conflicted
    # @name), so a later re-projection derives `base` again rather than doubling
    # the -pj suffix.
    rr.rename_claim(conn, root_id, name, agent_file,
                    deconflicted_from=deconflicted_from, requested_name=base)
    conn.commit()
    if old is not None and old["agent_file"] != agent_file:
        _sweep_owned_file(apex, old["agent_file"], old["cur_rel"],
                          root_id=root_id, hist=hist)
    return name


def op_relink(conn, root_id, new_rel_path, *, home=None):
    """Relink an orphaned identity to a new location: dispatch to
    roots_register.relink (version the spine under the SAME root_id + re-slug the
    transcript store). The claim is untouched — a live project's agent survives the
    move. `home` overrides ~ for hermetic testing.
    """
    _rr().relink(conn, root_id, new_rel_path, home=home)
    conn.commit()


def op_canonicalize(conn, rel_path):
    """Canonicalize an unlinked walked root as a NEW identity: dispatch to
    roots_register.mint (allocate a fresh root_id, open its spine row). This is the
    'fresh identity' half of re-canonicalizing a first-touch mis-call — the 'it is
    a new project' call. The complementary 'it is the moved-here old project' call
    is `op_relink` of the orphaned identity onto this same rel_path. Returns the
    new root_id.

    (Undoing a relink — SPLITTING a fork wrongly merged into an existing identity —
    would need a new spine-retirement writer in the module; it is out of this thin
    command's scope by construction. See the report.)
    """
    rid = _rr().mint(conn, rel_path)
    conn.commit()
    return rid


# ── Interactive menu (thin TTY wrapper) ──────────────────────────────

def _ask(prompt):
    """input() that turns EOF/Ctrl-C into None (caller treats as cancel)."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _current_claims(conn):
    """(@name, root_id, current rel_path) for every current claim — the disable /
    rename target list."""
    return list(conn.execute(
        "SELECT ar.agent_name, ar.root_id,"
        " COALESCE(rr.rel_path, ar.rel_path) AS rel_path"
        " FROM agent_registry ar"
        " LEFT JOIN roots_register rr"
        "   ON rr.root_id = ar.root_id AND rr.valid_to IS NULL"
        " WHERE ar.valid_to IS NULL ORDER BY ar.agent_name"))


def _declined_roots(conn):
    """(root_id, rel_path, requested_name) for every declined identity with a
    current spine row — the enable target list."""
    return list(conn.execute(
        "SELECT o.root_id, rr.rel_path, o.requested_name"
        " FROM agent_optin o"
        " JOIN roots_register rr ON rr.root_id = o.root_id AND rr.valid_to IS NULL"
        " WHERE o.enabled = 0 ORDER BY rr.rel_path"))


def _pick(items, render):
    """Prompt for a 1-based selection over `items`; None on cancel/empty."""
    if not items:
        print("     (none)")
        return None
    for i, it in enumerate(items, 1):
        print(f"       {i}. {render(it)}")
    raw = _ask("     pick a number (Enter cancels): ")
    if not raw or not raw.strip().isdigit():
        return None
    n = int(raw.strip())
    return items[n - 1] if 1 <= n <= len(items) else None


def _do_disable(conn, apex):
    print("  Turn an agent OFF (close its claim, opt it out):")
    claims = _current_claims(conn)
    pick = _pick(claims, lambda c: f"@{c['agent_name']}  ({c['rel_path']})")
    if pick is None:
        return
    status = op_disable(conn, pick["root_id"], apex=apex)
    print(f"     -> @{pick['agent_name']} disabled; agent file: {status}")


def _do_enable(conn, apex):
    print("  Turn a declined root ON (record the opt-in; boot projects the file):")
    declined = _declined_roots(conn)
    pick = _pick(declined, lambda d: f"{d['rel_path']}"
                 + (f"  (requested @{d['requested_name']})" if d["requested_name"] else ""))
    if pick is None:
        return
    op_enable(conn, pick["root_id"])
    print(f"     -> {pick['rel_path']} enabled. Run "
          f"`python cboot.py --materialize-only` to project its agent file.")


def _do_rename(conn, apex):
    print("  Rename an @name:")
    claims = _current_claims(conn)
    pick = _pick(claims, lambda c: f"@{c['agent_name']}  ({c['rel_path']})")
    if pick is None:
        return
    raw = _ask("     new base @name (without the -pj suffix): ")
    if not raw or not raw.strip():
        return
    try:
        name = op_rename(conn, pick["root_id"], raw.strip(), apex=apex)
    except ValueError as e:
        print(f"     ! {e}")
        return
    print(f"     -> renamed to @{name}. Run "
          f"`python cboot.py --materialize-only` to project the renamed file.")


def _do_relink(conn, apex, drift):
    print("  Relink an orphaned identity to a new location (a move made out of band):")
    if not drift.orphaned:
        print("     (no orphaned identities)")
        return
    src = _pick(drift.orphaned, lambda o: f"{o['rel_path']}  (root_id {o['root_id']}"
                + (f", @{o['agent_name']}" if o["agent_name"] else "") + ")")
    if src is None:
        return
    print("     New location — pick an unlinked walked directory, or type a rel_path:")
    dst = None
    if drift.unlinked:
        chosen = _pick(drift.unlinked, lambda u: u["rel_path"])
        if chosen is not None:
            dst = chosen["rel_path"]
    if dst is None:
        raw = _ask("     rel_path to relink onto (Enter cancels): ")
        if not raw or not raw.strip():
            return
        dst = raw.strip()
    try:
        op_relink(conn, src["root_id"], dst)
    except (ValueError, OSError, sqlite3.Error) as e:
        # A destination-store collision surfaces as ValueError; a stray filesystem
        # error as OSError. Either way, report it and leave the DB untouched — the
        # writer refused (or rolled back) before committing, so a rollback here
        # only clears any empty transaction it opened.
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        print(f"     ! relink failed: {e}")
        return
    print(f"     -> root_id {src['root_id']} relinked to {dst} "
          f"(identity + transcripts kept).")


def _do_canonicalize(conn, apex, drift):
    print("  Canonicalize an unlinked root as a NEW identity (mint a fresh root_id):")
    if not drift.unlinked:
        print("     (no unlinked roots)")
        return
    pick = _pick(drift.unlinked, lambda u: u["rel_path"])
    if pick is None:
        return
    try:
        rid = op_canonicalize(conn, pick["rel_path"])
    except (ValueError, sqlite3.Error) as e:
        print(f"     ! canonicalize failed: {e}")
        return
    print(f"     -> {pick['rel_path']} minted a fresh identity (root_id {rid}). "
          f"Run `python cboot.py --materialize-only` to decide/project it.")


_MENU = (
    ("o", "turn an agent OFF", _do_disable),
    ("e", "turn a declined root ON", _do_enable),
    ("r", "rename an @name", _do_rename),
    ("l", "relink an orphaned identity", _do_relink),
    ("c", "canonicalize an unlinked root (fresh identity)", _do_canonicalize),
)


def _interactive_menu(conn, apex, drift):
    """The TTY reconfigure loop. Re-reads drift after each mutation so the menus
    reflect the new state."""
    while True:
        print()
        print("  Reconfigure — choose an operation (Enter/q quits):")
        for key, label, _ in _MENU:
            print(f"    {key}) {label}")
        raw = _ask("  roots> ")
        if raw is None:
            break
        choice = raw.strip().lower()
        if choice in ("", "q", "quit"):
            break
        action = next((fn for k, _, fn in _MENU if k == choice), None)
        if action is None:
            print("  (unknown choice)")
            continue
        if action in (_do_relink, _do_canonicalize):
            action(conn, apex, drift)
        else:
            action(conn, apex)
        drift = compute_drift(conn, apex)


# ── Entry point ──────────────────────────────────────────────────────

def run(argv=None):
    """Compute and print drift; at a TTY, offer the reconfigure menu. Returns an
    exit code (0 on success). Non-TTY: report and return 0, mutating nothing."""
    parser = argparse.ArgumentParser(
        prog="roots", description="Reconfigure the root inventory (apex-only).")
    parser.add_argument("--project-root", type=Path, default=Path.cwd(),
                        help="Apex project root (default: cwd).")
    args = parser.parse_args(argv)

    apex = args.project_root.resolve()
    db_path = apex / ".state" / "roots.db"
    if not db_path.is_file():
        print(f"  roots.db not found at {db_path} — nothing to reconfigure "
              f"(run `python cboot.py --materialize-only` first).")
        return 0

    if not _interactive():
        # Report-only. True read-only open; mutate nothing.
        try:
            conn = _connect_ro(db_path)
        except sqlite3.Error as e:
            print(f"  roots.db unreadable: {e}")
            return 0
        try:
            have_roots = _table_exists(conn, "roots")
            drift = compute_drift(conn, apex)
        finally:
            conn.close()
        print_drift(drift, have_roots=have_roots)
        print("  (non-interactive: report only — run /roots from a terminal to "
              "reconfigure)")
        return 0

    # Interactive: a writable connection for the dispatch functions to commit on.
    try:
        conn = _sqlite().connect(str(db_path))
    except sqlite3.Error as e:
        print(f"  roots.db unopenable: {e}")
        return 1
    try:
        have_roots = _table_exists(conn, "roots")
        drift = compute_drift(conn, apex)
        print_drift(drift, have_roots=have_roots)
        _interactive_menu(conn, apex, drift)
    finally:
        conn.close()
    return 0


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
