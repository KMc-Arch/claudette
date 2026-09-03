#!/usr/bin/env python3
"""Hermetic tests for /move-project. Builds a real post-spine roots.db in a temp
apex + a fake ~, then exercises dry-run, execute, guards, blockers, rollback."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REAL_APEX = Path(__file__).resolve().parent   # apex root (this harness lives here)
MP_PATH = REAL_APEX / ".codex" / "explicit" / "move-project" / "move_project.py"
RR_PATH = REAL_APEX / ".codex" / "reactive" / "roots-register" / "roots_register.py"
SQLITE_PATH = REAL_APEX / ".codex" / "reactive" / "sqlite" / "sqlite.py"
CBOOT_PATH = REAL_APEX / "cboot.py"


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mp = _load(MP_PATH)
rr = _load(RR_PATH)
sq = _load(SQLITE_PATH)
cb = _load(CBOOT_PATH)

_fails = []
_passes = []


def check(name, cond, detail=""):
    (_passes if cond else _fails).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + detail) if detail and not cond else ""))


def make_store(home, abs_path):
    d = home / ".claude" / "projects" / mp._slug(abs_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "marker.jsonl").write_text("x\n")
    return d


def store_dir(home, abs_path):
    return home / ".claude" / "projects" / mp._slug(abs_path)


def build_apex():
    """A temp apex with proj + proj/sub as registered roots; a fake ~ with their
    transcript stores and a paused session under proj. Returns (apex, home)."""
    base = Path(tempfile.mkdtemp(prefix="mvpj-")).resolve()
    apex = base / "apex"
    home = base / "home"
    for p in (apex / ".state", home / ".claude" / "projects", home / ".claude" / "sessions"):
        p.mkdir(parents=True, exist_ok=True)
    (apex / "CLAUDE.md").write_text("---\nroot: true\napex-root: true\n---\n")
    proj = apex / "proj"
    sub = proj / "sub"
    sub.mkdir(parents=True)
    (proj / "CLAUDE.md").write_text("---\nroot: true\n---\n")
    (sub / "CLAUDE.md").write_text("---\nroot: true\n---\n")

    db = apex / ".state" / "roots.db"
    conn = sq.connect(str(db))
    cb._ensure_agent_tables(conn)    # self-migrates: apex minted as root_id=1, rel "."
    conn.commit()
    rid_proj = rr.mint(conn, "proj")
    rr.open_claim(conn, rid_proj, "proj-pj", "proj", ".claude/agents/proj-pj.md")
    rid_sub = rr.mint(conn, "proj/sub")
    rr.open_claim(conn, rid_sub, "sub-pj", "proj/sub", ".claude/agents/sub-pj.md")
    conn.commit()
    conn.close()

    make_store(home, proj)
    make_store(home, sub)
    (home / ".claude" / "sessions" / "100.json").write_text(
        json.dumps({"pid": 424242, "cwd": str(proj)}) + "\n")  # dead pid → rewrite target
    return apex, home


def current_rel(apex, root_id):
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    row = conn.execute(
        "SELECT rel_path FROM roots_register WHERE root_id=? AND valid_to IS NULL",
        (root_id,)).fetchone()
    conn.close()
    return row["rel_path"] if row else None


def claim_current(apex, root_id):
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    row = conn.execute(
        "SELECT agent_name FROM agent_registry WHERE root_id=? AND valid_to IS NULL",
        (root_id,)).fetchone()
    conn.close()
    return row["agent_name"] if row else None


def t_dry_run():
    apex, home = build_apex()
    rc = mp.run(["proj", "moved", "--project-root", str(apex), "--home", str(home)])
    check("T1 dry-run exit 0", rc == 0)
    check("T1 tree not moved", (apex / "proj").is_dir() and not (apex / "moved").exists())
    check("T1 spine unchanged", current_rel(apex, 2) == "proj")
    check("T1 store unmoved", store_dir(home, apex / "proj").exists()
          and not store_dir(home, apex / "moved").exists())
    sess = json.loads((home / ".claude" / "sessions" / "100.json").read_text())
    check("T1 session unchanged", sess["cwd"] == str(apex / "proj"))


def t_execute():
    apex, home = build_apex()
    rc = mp.run(["proj", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T2 execute exit 0", rc == 0)
    check("T2 tree moved", (apex / "moved" / "sub").is_dir() and not (apex / "proj").exists())
    check("T2 proj relinked (same root_id 2)", current_rel(apex, 2) == "moved")
    check("T2 sub relinked (same root_id 3)", current_rel(apex, 3) == "moved/sub")
    check("T2 proj claim survives move", claim_current(apex, 2) == "proj-pj")
    check("T2 sub claim survives move", claim_current(apex, 3) == "sub-pj")
    check("T2 proj store followed", store_dir(home, apex / "moved").exists()
          and not store_dir(home, apex / "proj").exists())
    check("T2 sub store followed", store_dir(home, apex / "moved" / "sub").exists()
          and not store_dir(home, apex / "proj" / "sub").exists())
    sess = json.loads((home / ".claude" / "sessions" / "100.json").read_text())
    check("T2 session cwd rewritten", sess["cwd"] == str(apex / "moved"))
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    closed = conn.execute("SELECT COUNT(*) FROM roots_register "
                          "WHERE root_id=2 AND valid_to IS NOT NULL").fetchone()[0]
    conn.close()
    check("T2 old spine row closed (SCD2 history)", closed == 1)


def t_guards():
    apex, home = build_apex()
    outside = str(apex.parent / "escape")
    rc = mp.run(["proj", outside, "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T3 egress dest refused", rc == 2 and (apex / "proj").exists())
    rc = mp.run([".", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T3 moving apex refused", rc == 2)
    rc = mp.run(["proj", "proj/inside", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T3 dest-inside-source refused", rc == 2 and (apex / "proj").exists())
    rc = mp.run(["proj", "_hidden", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T3 underscore dest refused", rc == 2)


def t_collision():
    apex, home = build_apex()
    make_store(home, apex / "moved")   # pre-existing store at the destination slug
    rc = mp.run(["proj", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T4 store collision blocks execute", rc == 2 and (apex / "proj").exists())
    check("T4 collision leaves spine intact", current_rel(apex, 2) == "proj")


def t_live_session():
    apex, home = build_apex()
    import os as _os
    (home / ".claude" / "sessions" / "200.json").write_text(
        json.dumps({"pid": _os.getpid(), "cwd": str(apex / "proj" / "sub")}) + "\n")
    rc = mp.run(["proj", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T5 live session blocks execute", rc == 2 and (apex / "proj").exists())


def t_rollback():
    apex, home = build_apex()
    src = (apex / "proj").resolve()
    dst = (apex / "moved").resolve()
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    plan = mp._preflight(conn, apex.resolve(), src, dst, home.resolve())
    # Race: create the SECOND identity's destination store AFTER preflight, so the
    # sub relink's os.rename collides mid-execute (proj already moved + relinked).
    sub_new_store = store_dir(home, dst / "sub")
    sub_new_store.mkdir(parents=True, exist_ok=True)
    (sub_new_store / "intruder.jsonl").write_text("x\n")
    rc = mp._execute(conn, plan, apex.resolve(), home.resolve())
    # On the SAME live connection: prove conn.rollback() actually reverted (a passing
    # assertion via a fresh connection would also hold if rollback were absent, since
    # uncommitted writes are invisible cross-connection). Here the live conn would
    # still be mid-transaction and see the mutated spine if rollback had not run.
    same_conn = conn.execute("SELECT rel_path FROM roots_register "
                             "WHERE root_id=2 AND valid_to IS NULL").fetchone()
    check("T6 DB rolled back on the live conn", same_conn is not None
          and same_conn["rel_path"] == "proj" and not conn.in_transaction)
    conn.close()
    check("T6 execute reports failure", rc == 1)
    check("T6 tree rolled back", src.exists() and not dst.exists())
    check("T6 proj spine rolled back", current_rel(apex, 2) == "proj")
    check("T6 sub spine rolled back", current_rel(apex, 3) == "proj/sub")
    check("T6 proj store rolled back", store_dir(home, src).exists()
          and not store_dir(home, dst).exists())


def _nondocstring_strings(path):
    """Every NON-docstring string-literal value in a Python file, via AST.

    Docstrings (module/class/func first-statement Expr strings) carry prose like
    `immutable=1&mode=ro` and are excluded. A real SQL string or a real read-only
    connection URI is a string used as an argument/expression, so it survives here
    — which is exactly what makes the structural check have teeth. (The prior
    tokenize approach stripped ALL strings, so the check could never fail: the very
    thing it looked for only ever lives inside a string.)"""
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())
    doc_ids = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                doc_ids.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in doc_ids]


def t_unregistered():
    """A nested root: true dir with NO spine identity — its transcript store must
    follow best-effort, and it must NOT be minted (re-canonicalizes on next boot)."""
    apex, home = build_apex()
    orphan = apex / "proj" / "orphan"
    orphan.mkdir()
    (orphan / "CLAUDE.md").write_text("---\nroot: true\n---\n")
    make_store(home, orphan)
    rc = mp.run(["proj", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T8 execute exit 0", rc == 0)
    check("T8 unregistered store followed", store_dir(home, apex / "moved" / "orphan").exists()
          and not store_dir(home, apex / "proj" / "orphan").exists())
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    n = conn.execute("SELECT COUNT(*) FROM roots_register "
                     "WHERE rel_path IN ('proj/orphan','moved/orphan')").fetchone()[0]
    conn.close()
    check("T8 unregistered NOT minted (no spine row)", n == 0)


def t_lock_diagnostic():
    """On an EACCES tree-move, the failure path prints the why + names the locked
    descendant(s) via the (mocked here) Windows scan, and still rolls back."""
    import io
    import contextlib
    apex, home = build_apex()
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    plan = mp._preflight(conn, apex.resolve(), (apex / "proj").resolve(),
                         (apex / "moved").resolve(), home.resolve())
    orig_rename = mp.os.rename
    orig_scan = mp._win_locked_descendants

    def fake_rename(a, b, *rest):
        if str(a).endswith("/proj") and str(b).endswith("/moved"):
            raise PermissionError(13, "Permission denied")
        return orig_rename(a, b, *rest)

    mp.os.rename = fake_rename
    mp._win_locked_descendants = lambda src: [str(src / "~outbox" / "held-open")]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mp._execute(conn, plan, apex.resolve(), home.resolve())
    finally:
        mp.os.rename = orig_rename
        mp._win_locked_descendants = orig_scan
        conn.close()
    out = buf.getvalue()
    check("T9 EACCES reported failure", rc == 1)
    check("T9 prints the why", "EACCES on the tree move" in out)
    check("T9 names the locked descendant", "held-open" in out)
    check("T9 tree not moved", (apex / "proj").is_dir() and not (apex / "moved").exists())
    check("T9 spine unchanged", current_rel(apex, 2) == "proj")


def t_structural():
    import re
    lits = _nondocstring_strings(MP_PATH)
    strings = "\n".join(lits)
    # Any raw write verb reaching an identity table (INSERT / INSERT OR REPLACE /
    # REPLACE / UPDATE / DELETE FROM), not just INSERT/UPDATE.
    sql = re.compile(r"\b(INSERT|REPLACE|UPDATE|DELETE)\b.{0,40}?\b(roots_register|agent_registry|agent_optin)\b", re.I | re.S)
    ro = re.compile(r"immutable\s*=\s*1|mode\s*=\s*ro", re.I)
    # Positive control: the extractor is non-empty and captured real SQL (the SELECT).
    check("T7 extractor non-empty (control)", "roots_register" in strings)
    # Meta: the guards fire on every raw-write form + the RO URI (not vacuous regexes).
    for bad in ("INSERT INTO roots_register", "INSERT OR REPLACE INTO agent_optin",
                "REPLACE INTO roots_register", "DELETE FROM roots_register",
                "UPDATE agent_registry SET"):
        check("T7 SQL guard catches %r" % bad, sql.search("conn.execute('%s ...')" % bad) is not None)
    check("T7 RO-URI guard has teeth", ro.search("connect('file:x?immutable=1&mode=ro')") is not None)
    # The real checks, over non-docstring string literals only.
    check("T7 no raw identity-table writes (single-writer)", sql.search(strings) is None)
    check("T7 no immutable=ro reader (WAL discipline)", ro.search(strings) is None)


def t_confirm_gate():
    """--execute WITHOUT --yes and no TTY must refuse (the CONFIRMED-HOLD gate)."""
    apex, home = build_apex()
    rc = mp.run(["proj", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute"])   # no --yes; not a tty under test
    check("T10 execute without --yes refuses", rc == 1)
    check("T10 unconfirmed move did nothing", (apex / "proj").is_dir()
          and not (apex / "moved").exists() and current_rel(apex, 2) == "proj")


def t_nondict_session():
    """A valid-JSON non-object session file must not crash the command (incl dry-run)."""
    apex, home = build_apex()
    (home / ".claude" / "sessions" / "num.json").write_text("42\n")
    (home / ".claude" / "sessions" / "list.json").write_text("[]\n")
    (home / ".claude" / "sessions" / "nul.json").write_text("null\n")
    rc = mp.run(["proj", "moved", "--project-root", str(apex), "--home", str(home)])
    check("T11 dry-run survives non-object session files", rc == 0)
    rc = mp.run(["proj", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T11 execute survives non-object session files",
          rc == 0 and (apex / "moved").is_dir())


def t_session_prefix_and_nested():
    """_under must not sweep a prefix-sibling session; nested-cwd slice must be right."""
    apex, home = build_apex()
    (apex / "projX").mkdir()   # shares the 'proj' name prefix but is a sibling
    (home / ".claude" / "sessions" / "sib.json").write_text(
        json.dumps({"pid": 555001, "cwd": str(apex / "projX")}) + "\n")
    (home / ".claude" / "sessions" / "nested.json").write_text(
        json.dumps({"pid": 555002, "cwd": str(apex / "proj" / "sub")}) + "\n")
    rc = mp.run(["proj", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T12 execute exit 0", rc == 0)
    sib = json.loads((home / ".claude" / "sessions" / "sib.json").read_text())
    check("T12 prefix-sibling session NOT rewritten", sib["cwd"] == str(apex / "projX"))
    nested = json.loads((home / ".claude" / "sessions" / "nested.json").read_text())
    check("T12 nested-cwd session rewritten (correct slice)",
          nested["cwd"] == str(apex / "moved" / "sub"))


def t_case_insensitive():
    """Path comparisons fold case (drvfs is case-insensitive). Unit-tested because the
    tmp fs (ext4) is case-SENSITIVE and cannot exercise it via real dirs."""
    check("T13 _under folds case", mp._under("/a/PROJ/x", "/a/proj"))
    check("T13 _under respects the boundary", not mp._under("/a/projX", "/a/proj"))
    check("T13 _is_within folds case",
          mp._is_within(Path("/a/SomeChild/sub"), Path("/a/somechild")))
    check("T13 _is_within respects the boundary",
          not mp._is_within(Path("/a/foobar"), Path("/a/foo")))
    apex, home = build_apex()
    (home / ".claude" / "sessions" / "cv.json").write_text(
        json.dumps({"pid": 556001, "cwd": "/x/proj/sub"}) + "\n")
    rw = mp._sessions_to_rewrite(home, Path("/x/PROJ"), Path("/x/moved"))
    check("T13 session rewrite matches a case-variant source",
          any(new == "/x/moved/sub" for (_f, _c, new) in rw))


def t_unreg_collision_nonblocking():
    """An unregistered nested root whose dest store slug is occupied must NOT block
    the whole move (best-effort per start.md) — registered identities still move."""
    apex, home = build_apex()
    orphan = apex / "proj" / "orphan"
    orphan.mkdir()
    (orphan / "CLAUDE.md").write_text("---\nroot: true\n---\n")
    make_store(home, orphan)                        # the orphan's source store
    make_store(home, apex / "moved" / "orphan")     # pre-existing dest store => collision
    rc = mp.run(["proj", "moved", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T14 unreg-store collision does NOT block the move", rc == 0)
    check("T14 registered identity still relinked", current_rel(apex, 2) == "moved")
    check("T14 tree moved despite unreg collision", (apex / "moved" / "sub").is_dir())
    check("T14 orphan source store left in place (collision, not clobbered)",
          store_dir(home, apex / "proj" / "orphan").exists()
          and store_dir(home, apex / "moved" / "orphan").exists())


def t_framework_guard():
    """Refuse moving a dot-prefixed (framework) path such as .state / .codex, as
    either source or dest."""
    apex, home = build_apex()
    rc = mp.run([".state", "moved-state", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T15 refuses framework dir as source (.state)", rc == 2 and (apex / ".state").is_dir())
    rc = mp.run(["proj", ".hidden-dest", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T15 refuses dot-prefixed dest", rc == 2 and not (apex / ".hidden-dest").exists())


def t_ghost_verification():
    """A post-rename ghost (rename 'succeeds' but nothing moved) trips the rollback,
    never a false success + DB commit over a broken destination."""
    import io
    import contextlib
    apex, home = build_apex()
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    plan = mp._preflight(conn, apex.resolve(), (apex / "proj").resolve(),
                         (apex / "moved").resolve(), home.resolve())
    orig = mp.os.rename

    def noop_forward(a, b, *r):
        if str(a).endswith("/proj") and str(b).endswith("/moved"):
            return          # simulate a 9p ghost: "succeeds" but nothing moved
        return orig(a, b, *r)

    mp.os.rename = noop_forward
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mp._execute(conn, plan, apex.resolve(), home.resolve())
    finally:
        mp.os.rename = orig
        conn.close()
    out = buf.getvalue()
    check("T16 ghost trips failure", rc == 1)
    check("T16 ghost message shown", "post-rename verification" in out)
    check("T16 ghost leaves tree at source", (apex / "proj").is_dir()
          and not (apex / "moved").exists())
    check("T16 ghost spine unchanged", current_rel(apex, 2) == "proj")


def t_rollback_incomplete():
    """When an undo step itself fails, the tool reports 'rollback INCOMPLETE', never
    a false clean revert."""
    import io
    import contextlib
    apex, home = build_apex()
    src = (apex / "proj").resolve()
    dst = (apex / "moved").resolve()
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    plan = mp._preflight(conn, apex.resolve(), src, dst, home.resolve())
    sub_new = store_dir(home, dst / "sub")      # force the sub relink to fail
    sub_new.mkdir(parents=True, exist_ok=True)
    (sub_new / "x.jsonl").write_text("x\n")
    orig = mp.os.rename

    def reverse_fails(a, b, *r):
        if str(a).endswith("/moved") and str(b).endswith("/proj"):
            raise OSError(13, "reverse rename blocked")   # the tree-undo fails
        return orig(a, b, *r)

    mp.os.rename = reverse_fails
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mp._execute(conn, plan, apex.resolve(), home.resolve())
    finally:
        mp.os.rename = orig
        conn.close()
    out = buf.getvalue()
    check("T17 execute failed", rc == 1)
    check("T17 reports INCOMPLETE", "rollback was INCOMPLETE" in out)
    check("T17 does NOT claim a clean revert", "move aborted and rolled back" not in out)


def t_confirm_interactive():
    """The interactive confirmation accepts only an exact destination-path match."""
    import builtins
    dest = Path("/x/dest/here")

    class FakeTTY:   # forwards real IO (so print still works), but claims to be a tty
        def __init__(self, real):
            self._real = real

        def isatty(self):
            return True

        def __getattr__(self, n):
            return getattr(self._real, n)

    orig_in, orig_stdin, orig_stdout = builtins.input, mp.sys.stdin, mp.sys.stdout
    mp.sys.stdin, mp.sys.stdout = FakeTTY(orig_stdin), FakeTTY(orig_stdout)
    try:
        builtins.input = lambda *a: str(dest)
        check("T18 confirm accepts exact dest", mp._confirm(dest) is True)
        # A PREFIX of dest: `ans in str(dest)` would wrongly accept it; only `==`
        # rejects — so this pins the exact-match contract against that weakening.
        builtins.input = lambda *a: str(dest)[:-3]
        check("T18 confirm rejects a prefix near-miss", mp._confirm(dest) is False)
        builtins.input = lambda *a: str(dest) + "x"
        check("T18 confirm rejects a superstring", mp._confirm(dest) is False)
    finally:
        builtins.input, mp.sys.stdin, mp.sys.stdout = orig_in, orig_stdin, orig_stdout


def t_true_case():
    """_true_case (full-path) recovers on-disk casing — for a mis-cased ARG and a
    mis-cased --project-root/apex — even on the case-sensitive test fs (it folds
    itself), so a mis-cased path never silently orphans a store. Also proves _under
    uses the length-preserving ASCII fold (no casefold slice corruption)."""
    apex, home = build_apex()
    ap = apex.resolve()
    check("T19 _true_case recovers on-disk casing", mp._true_case(ap / "PROJ") == ap / "proj")
    check("T19 _true_case keeps a not-yet-existing leaf as typed",
          mp._true_case(ap / "proj" / "NewLeaf") == ap / "proj" / "NewLeaf")
    check("T19 _true_case canonicalises a mis-cased apex component",
          mp._true_case(ap.parent / ap.name.upper()) == ap)
    check("T19 _under does not casefold-overmatch (ss vs ß)", not mp._under("/p/SS/x", "/p/ß"))
    # mis-cased source arg + unregistered nested root → store still follows.
    orphan = apex / "proj" / "Orphan"
    orphan.mkdir()
    (orphan / "CLAUDE.md").write_text("---\nroot: true\n---\n")
    make_store(home, orphan)
    rc = mp.run(["PROJ/ORPHAN", "moved-orphan", "--project-root", str(apex),
                 "--home", str(home), "--execute", "--yes"])
    check("T19 mis-cased source arg executes (canonicalised)", rc == 0)
    check("T19 unregistered store followed despite mis-cased arg",
          store_dir(home, ap / "moved-orphan").exists()
          and not store_dir(home, ap / "proj" / "Orphan").exists())
    # mis-cased --project-root (apex) → registered store still follows.
    apex2, home2 = build_apex()
    ap2 = apex2.resolve()
    rc = mp.run(["proj", "movedX", "--project-root", str(ap2.parent / ap2.name.upper()),
                 "--home", str(home2), "--execute", "--yes"])
    check("T19 mis-cased --project-root canonicalised (registered store follows)",
          rc == 0 and store_dir(home2, ap2 / "movedX").exists()
          and not store_dir(home2, ap2 / "proj").exists())


def t_nonascii_refused():
    """A non-ASCII path in the move set is refused (the fold is ASCII-only; a case
    difference could silently fork an identity)."""
    apex, home = build_apex()
    grp = apex / "grüppe"
    grp.mkdir()
    (grp / "CLAUDE.md").write_text("---\nroot: true\n---\n")
    rc = mp.run(["grüppe", "moved", "--project-root", str(apex),
                 "--home", str(home)])   # dry-run: still refused at preflight
    check("T24 non-ASCII source refused", rc == 2 and grp.is_dir())
    rc = mp.run(["proj", "dést", "--project-root", str(apex), "--home", str(home)])
    check("T24 non-ASCII dest refused", rc == 2)


def t_symlink_walk_skipped():
    """The FS walk skips symlinked dirs — no recursion, no external-root store pulled
    in. is_symlink() is MOCKED (no real symlink is created — the symlink ABSOLUTE
    HOLD forbids creating one, even a transient test one)."""
    apex, home = build_apex()
    alias = apex / "proj" / "alias"
    alias.mkdir()                      # a real dir; we mock is_symlink() True for it
    (alias / "CLAUDE.md").write_text("---\nroot: true\n---\n")
    src = (apex / "proj").resolve()
    orig = Path.is_symlink

    def fake_is_symlink(self):
        return self.name == "alias" or orig(self)

    # control: a real dir under the source IS walked
    check("T25 control: a real nested root IS walked",
          any(w.name == "alias" for w in mp._discover_child_roots(src)))
    Path.is_symlink = fake_is_symlink
    try:
        walked = mp._discover_child_roots(src)
    finally:
        Path.is_symlink = orig
    check("T25 a symlinked dir is skipped by the walk",
          all(w.name != "alias" for w in walked))


def t_ghost_estale():
    """A ghosted dirent can raise (ESTALE) from is_dir() rather than return False; the
    post-rename check must catch OSError and treat it as a failed verification."""
    import io
    import contextlib
    apex, home = build_apex()
    conn = sq.connect(str(apex / ".state" / "roots.db"))
    plan = mp._preflight(conn, apex.resolve(), (apex / "proj").resolve(),
                         (apex / "moved").resolve(), home.resolve())
    orig_is_dir = Path.is_dir

    def fake_is_dir(self):
        if str(self).endswith("/moved"):
            raise OSError(116, "Stale file handle")   # ESTALE
        return orig_is_dir(self)

    Path.is_dir = fake_is_dir
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mp._execute(conn, plan, apex.resolve(), home.resolve())
    finally:
        Path.is_dir = orig_is_dir
        conn.close()
    out = buf.getvalue()
    check("T23 ESTALE ghost trips failure", rc == 1)
    check("T23 ESTALE ghost message shown", "post-rename verification" in out)
    check("T23 ESTALE ghost rolled back", (apex / "proj").is_dir()
          and not (apex / "moved").exists())


def t_missing_db():
    """No roots.db at the project-root → exit 2, nothing created."""
    import tempfile as _tf
    empty = Path(_tf.mkdtemp(prefix="mvpj-nodb-")).resolve()
    (empty / "target").mkdir()
    rc = mp.run(["target", "moved", "--project-root", str(empty), "--home", str(empty)])
    check("T26 missing db exits 2", rc == 2 and not (empty / ".state" / "roots.db").exists())


def t_reconcile_subprocess():
    """The post-commit cboot --materialize-only reconcile actually runs; a failing
    reconcile warns but never fails a committed move."""
    import io
    import contextlib
    apex, home = build_apex()
    marker = apex / "cboot-called.txt"
    (apex / "cboot.py").write_text(
        "import sys\nopen(%r, 'w').write(' '.join(sys.argv))\nsys.exit(0)\n" % str(marker))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mp.run(["proj", "moved", "--project-root", str(apex),
                     "--home", str(home), "--execute", "--yes"])
    check("T22 move succeeded", rc == 0)
    check("T22 reconcile subprocess ran", marker.exists())
    check("T22 reconcile passed --materialize-only", marker.exists()
          and "--materialize-only" in marker.read_text())
    check("T22 reconcile success reported", "reconciled agent files" in buf.getvalue())
    apex2, home2 = build_apex()
    (apex2 / "cboot.py").write_text("import sys\nsys.exit(3)\n")
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc2 = mp.run(["proj", "moved", "--project-root", str(apex2),
                      "--home", str(home2), "--execute", "--yes"])
    check("T22 failing cboot does NOT fail the committed move", rc2 == 0)
    check("T22 failing cboot warned to run by hand", "run it by hand" in buf2.getvalue())


def t_rel_case_variant():
    """_rel must not crash on a case-variant absolute apex prefix (fold-robust)."""
    check("T20 _rel folds a case-variant apex prefix",
          mp._rel(Path("/mnt/claudette"), Path("/mnt/Claudette/fooProj")) == "fooProj")
    check("T20 _rel handles nesting", mp._rel(Path("/a/b"), Path("/A/B/c/d")) == "c/d")


def main():
    for t in (t_dry_run, t_execute, t_guards, t_collision, t_live_session,
              t_rollback, t_unregistered, t_lock_diagnostic, t_structural,
              t_confirm_gate, t_nondict_session, t_session_prefix_and_nested,
              t_case_insensitive, t_unreg_collision_nonblocking, t_framework_guard,
              t_ghost_verification, t_rollback_incomplete, t_confirm_interactive,
              t_true_case, t_rel_case_variant, t_reconcile_subprocess,
              t_nonascii_refused, t_symlink_walk_skipped, t_ghost_estale, t_missing_db):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception:
            import traceback
            traceback.print_exc()
            _fails.append(t.__name__ + " (threw)")
    print("\n%d passed, %d failed" % (len(_passes), len(_fails)))
    if _fails:
        print("FAILURES:", _fails)
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
