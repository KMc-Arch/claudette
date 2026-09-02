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
    conn.close()
    check("T6 execute reports failure", rc == 1)
    check("T6 tree rolled back", src.exists() and not dst.exists())
    check("T6 proj spine rolled back", current_rel(apex, 2) == "proj")
    check("T6 sub spine rolled back", current_rel(apex, 3) == "proj/sub")
    check("T6 proj store rolled back", store_dir(home, src).exists()
          and not store_dir(home, dst).exists())


def _code_only(path):
    """Source with docstrings + comments stripped, so a structural grep sees CODE."""
    import io
    import tokenize
    out = []
    with open(path, "rb") as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type in (tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE):
                continue
            out.append(tok.string)
    return " ".join(out)


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


def t_structural():
    code = _code_only(MP_PATH)
    check("T7 no immutable=ro reader (WAL discipline)",
          "immutable" not in code and "sqlite3" not in code.split())
    import re
    raw = re.search(r"(INSERT|UPDATE)\s+(INTO\s+)?(roots_register|agent_registry|agent_optin)",
                    code, re.I)
    check("T7 no raw identity-table writes (single-writer)", raw is None)


def main():
    for t in (t_dry_run, t_execute, t_guards, t_collision, t_live_session,
              t_rollback, t_unregistered, t_structural):
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
