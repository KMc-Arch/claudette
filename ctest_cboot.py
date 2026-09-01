#!/usr/bin/env python3
"""Function-level tests for cboot.py's worker modes (--exec / --switch), arg
parsing, target resolution, and the root inventory.

Complements ctest.py (which verifies cboot's *outputs* and imports nothing) and
mirrors chooks.py's registry + bidirectional coverage pattern: every worker
function in COVERED must have at least one test, and every test must name a
covered target.

All tests are deterministic and NON-BILLABLE. The `exec_in_project` tests use a
temp-dir `claude` stub on PATH that records argv/cwd/$CLAUDE_PROJECT_DIR and
emits canned JSON — no model, no cost. Run:

    python ctest_cboot.py            # exit 1 on any failure
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_cboot():
    spec = importlib.util.spec_from_file_location("cboot", ROOT / "cboot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cboot = _load_cboot()

# ── Tiny test registry ───────────────────────────────────────────────

TESTS = []           # list of (id, target, fn)
_TARGETS_SEEN = set()

# cboot worker-mode functions this harness is responsible for covering.
COVERED = {
    "_extract_project_arg",
    "_resolve_target",
    "exec_in_project",
    "switch_command",
    "_filter_exec_passthrough",
    "build_root_inventory",
    # Addressable agents. The ownership entries live in the shared module
    # (.codex/reactive/agent-ownership) but are covered here because cboot and
    # purge are the only two callers and they must never diverge.
    "decide_agent_optin",
    "generate_agents",
    "_write_agent_file",
    "suffixed",
    "claims_for",
    "owns",
    "derive_agent_name",
    "render_marker",
    "_purge_agents_dir",
    "_ensure_agent_tables",
    "marker_matches",
    "_root_is_gone",
    "_classify_root",
    "_select_roots",
    "_walk_candidate_roots",
    "RootRows",
    "_reached_via_symlink",
    # The shared identity/claim mutation module
    # (.codex/reactive/roots-register/roots_register.py) — the SOLE writer of
    # roots_register/agent_registry/agent_optin identity rows. Covered here
    # because boot, the /roots command, and /move-project all CALL it and must
    # never diverge from a second copy.
    "next_root_id",
    "mint",
    "open_claim",
    "close_claim",
    "rename_claim",
    "relink",
    "deconflict",
    "accept",
    "decline",
    # The `/roots` reconfigure command
    # (.codex/explicit/roots/roots.py) — a THIN wrapper that dispatches every
    # mutation to the roots-register module. Covered here because its drift
    # computation and dispatch functions are the reconfigure complement of boot's
    # first-touch prompt and must stay consistent with the writer module.
    "compute_drift",
    "op_disable",
    "op_enable",
    "op_rename",
    "op_relink",
    "op_canonicalize",
    "roots_run",
}


def test(test_id, target):
    def deco(fn):
        TESTS.append((test_id, target, fn))
        _TARGETS_SEEN.add(target)
        return fn
    return deco


class Fail(AssertionError):
    pass


def eq(actual, expected, msg=""):
    if actual != expected:
        raise Fail(f"{msg}\n    expected: {expected!r}\n    actual:   {actual!r}")


def truthy(cond, msg=""):
    if not cond:
        raise Fail(msg or "expected truthy")


# ── live-child fixture ───────────────────────────────────────────────

def _discover_live_child():
    """First direct child of the apex that is itself a root: true context.

    Deliberately discovered, not hardcoded: this harness spent a while red on
    main because it named a folder (`majel`) that had since been renamed
    (`~majel`), and nothing in the failure said so.
    """
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        cm = d / "CLAUDE.md"
        try:
            head = cm.read_text(encoding="utf-8-sig")[:400]
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(r"^root:\s*true\s*$", head, re.M):
            return d.name
    return None


LIVE_CHILD = _discover_live_child()


def need_live_child():
    if LIVE_CHILD is None:
        raise Fail("no root: true child under the apex to test against")
    return LIVE_CHILD


# ── claude stub fixture ──────────────────────────────────────────────

@contextlib.contextmanager
def claude_stub(out_json='{"is_error":false,"result":"ok","session_id":"stub-1",'
                         '"total_cost_usd":0.01,"duration_ms":5,"num_turns":1}'):
    """Put a fake `claude` first on PATH. It records its argv/cwd/env to a file
    ($CBOOT_STUB_REC) and prints out_json. Yields the record-file Path."""
    d = Path(tempfile.mkdtemp(prefix="cboot-stub-"))
    rec = d / "rec.txt"
    stub = d / "claude"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [ -n "$CBOOT_STUB_REC" ]; then\n'
        '  { echo "ARGV: $*"; echo "CWD: $PWD"; echo "CPD: $CLAUDE_PROJECT_DIR"; } > "$CBOOT_STUB_REC"\n'
        "fi\n"
        'printf "%s" "$CBOOT_STUB_OUT"\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    saved = {k: os.environ.get(k) for k in ("PATH", "CBOOT_STUB_REC", "CBOOT_STUB_OUT")}
    os.environ["PATH"] = f"{d}{os.pathsep}{os.environ.get('PATH','')}"
    os.environ["CBOOT_STUB_REC"] = str(rec)
    os.environ["CBOOT_STUB_OUT"] = out_json
    try:
        yield rec
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run_exec(target, prompt, passthrough, prompt_file=None):
    """Call exec_in_project capturing stdout+stderr. Returns (code, json|None, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cboot.exec_in_project(target, prompt, passthrough, prompt_file=prompt_file)
    raw = out.getvalue().strip()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    return code, parsed, err.getvalue()


# ── _extract_project_arg (EP) ────────────────────────────────────────

@test("EP-01", "_extract_project_arg")
def _():
    t = cboot._extract_project_arg(["--project", "majel", "--exec", "do X", "--resume", "abc"])
    eq(t, ("majel", False, "do X", None, False, ["--resume", "abc"]), "6-tuple + passthrough")

@test("EP-02", "_extract_project_arg")
def _():
    for argv in (["--project", "majel"], ["-p", "majel"], ["--project=majel"]):
        eq(cboot._extract_project_arg(argv)[0], "majel", f"target from {argv}")

@test("EP-03", "_extract_project_arg")
def _():
    eq(cboot._extract_project_arg(["--exec", "P"])[2], "P", "--exec value")
    eq(cboot._extract_project_arg(["--exec=P"])[2], "P", "--exec= value")

@test("EP-04", "_extract_project_arg")
def _():
    _, launch, _, _, switch, _ = cboot._extract_project_arg(["--switch", "--launch"])
    eq((launch, switch), (True, True), "flags consume no value")

@test("EP-05", "_extract_project_arg")
def _():
    eq(cboot._extract_project_arg(["--exec"])[2], "", "--exec last token -> ''")
    eq(cboot._extract_project_arg(["--project"])[0], "", "--project last token -> ''")

@test("EP-06", "_extract_project_arg")
def _():
    t = cboot._extract_project_arg(["--project", "m", "--exec", "p", "--resume", "id", "--foo", "-v"])
    eq(t[5], ["--resume", "id", "--foo", "-v"], "passthrough order preserved")

@test("EP-07", "_extract_project_arg")
def _():
    nasty = '$(id); rm -rf /; `whoami`; "quote"\nnewline'
    eq(cboot._extract_project_arg(["--project", "m", "--exec", nasty])[2], nasty,
       "shell-metachar prompt survives byte-for-byte as one arg")

@test("EP-08", "_extract_project_arg")
def _():
    # value never leaks into passthrough; project value consumed
    t = cboot._extract_project_arg(["--resume", "abc", "--project", "majel"])
    eq((t[0], t[5]), ("majel", ["--resume", "abc"]), "project value not swallowed by passthrough")

@test("EP-09", "_extract_project_arg")
def _():
    t = cboot._extract_project_arg(["--project", "m", "--exec-file", "/t/r.txt"])
    eq(t[3], "/t/r.txt", "--exec-file path captured (index 3)")
    eq(t[2], None, "--exec-file does not set exec_prompt")
    eq(cboot._extract_project_arg(["--exec-file=/t/r.txt"])[3], "/t/r.txt", "--exec-file= form")


# ── _resolve_target (RT) ─────────────────────────────────────────────

@test("RT-01", "_resolve_target")
def _():
    child = need_live_child()
    p, err = cboot._resolve_target(child)
    eq(err, None, "valid child resolves"); truthy(p and p.name == child)

@test("RT-02", "_resolve_target")
def _():
    p, err = cboot._resolve_target("nonexistent-xyz")
    eq(p, None); truthy(err and "not found" in err, f"got {err!r}")

@test("RT-03", "_resolve_target")
def _():
    p, err = cboot._resolve_target(".")   # apex
    eq(p, None); truthy(err and "outside apex" in err, f"apex must be rejected; got {err!r}")

@test("RT-04", "_resolve_target")
def _():
    p, err = cboot._resolve_target("/tmp")
    eq(p, None); truthy(err and "outside apex" in err, f"got {err!r}")

@test("RT-05", "_resolve_target")
def _():
    p, err = cboot._resolve_target(".state")   # under apex, no root:true CLAUDE.md
    eq(p, None); truthy(err and "root: true" in err, f"got {err!r}")

@test("RT-06", "_resolve_target")
def _():
    p, err = cboot._resolve_target("agentic/Agentic Primitives")  # space in rel_path
    eq(err, None, "space-containing rel_path resolves"); truthy(p and p.name == "Agentic Primitives")


# ── _filter_exec_passthrough (FP) ────────────────────────────────────

@test("FP-01", "_filter_exec_passthrough")
def _():
    a, d = cboot._filter_exec_passthrough(
        ["--resume", "abc", "--dangerously-skip-permissions", "--model", "sonnet",
         "--add-dir", "/x", "--settings", "/e.json"])
    eq(a, ["--resume", "abc", "--model", "sonnet"], "only allowlisted flags+values kept")
    truthy("--dangerously-skip-permissions" in d and "--settings" in d, "governance flags dropped")

@test("FP-02", "_filter_exec_passthrough")
def _():
    a, d = cboot._filter_exec_passthrough(["--resume=xyz"])
    eq((a, d), (["--resume=xyz"], []), "--flag=value form kept")

@test("FP-03", "_filter_exec_passthrough")
def _():
    # a bare, value-less --resume must be DROPPED (would resume an unrelated session)
    eq(cboot._filter_exec_passthrough(["--resume"]), ([], ["--resume"]), "bare --resume dropped")
    eq(cboot._filter_exec_passthrough(["--resume", "--model", "s"]),
       (["--model", "s"], ["--resume"]), "value-less --resume before another flag dropped")


# ── exec_in_project (EX) ─────────────────────────────────────────────

@test("EX-01", "exec_in_project")
def _():
    code, j, _ = run_exec("nonexistent-xyz", "hi", [])
    eq(code, 1); eq(j["kind"], "error"); eq(j["root"], None)

@test("EX-02", "exec_in_project")
def _():
    code, j, _ = run_exec(need_live_child(), "   ", [])   # empty prompt, valid target
    eq(code, 1); eq(j["error"], "empty prompt")
    truthy(j["root"] and j["root"]["rel_path"] == need_live_child(),
           "empty-prompt error carries the resolved root")

@test("EX-05", "exec_in_project")
def _():
    with claude_stub():
        code, j, _ = run_exec(need_live_child(), "hello", [])
    eq(code, 0); truthy(j is not None, "stdout is a single parseable JSON object")
    eq(j["kind"], "result")

@test("EX-06", "exec_in_project")
def _():
    with claude_stub():
        _, j, _ = run_exec(need_live_child(), "hello", [])
    for k in ("kind", "mode", "root", "session_id", "result", "is_error",
              "cost_usd", "duration_ms", "num_turns"):
        truthy(k in j, f"envelope missing key {k}")
    eq(j["mode"], "hard"); eq(j["session_id"], "stub-1")

@test("EX-07", "exec_in_project")
def _():
    # The load-bearing hard-root: cwd AND CLAUDE_PROJECT_DIR both fenced at the
    # child, overriding an inherited (wrong) apex value.
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = "/WRONG/apex"
    try:
        with claude_stub() as rec:
            run_exec(need_live_child(), "hello", [])
            data = rec.read_text()
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
    child = str((ROOT / need_live_child()))
    truthy(f"CWD: {child}" in data, f"cwd not fenced at child:\n{data}")
    truthy(f"CPD: {child}" in data, f"CLAUDE_PROJECT_DIR not overridden to child:\n{data}")

@test("EX-08", "exec_in_project")
def _():
    with claude_stub() as rec:
        _, _, err = run_exec(need_live_child(), "hello",
                             ["--resume", "r1", "--dangerously-skip-permissions"])
        argv = rec.read_text()
    truthy("--resume r1" in argv, f"allowlisted passthrough not forwarded:\n{argv}")
    truthy("--dangerously-skip-permissions" not in argv, "governance flag reached claude")
    truthy("dropped disallowed passthrough" in err, "drop not reported on stderr")

@test("EX-09", "exec_in_project")
def _():
    # is_error:true on a parseable (kind:"result") envelope — message in `result`,
    # NO top-level `error` key, exit 1.
    with claude_stub('{"is_error":true,"result":"boom","session_id":"s9"}'):
        code, j, _ = run_exec(need_live_child(), "hello", [])
    eq(code, 1); eq(j["kind"], "result"); eq(j["is_error"], True)
    eq(j["result"], "boom"); truthy("error" not in j, "kind:result must not carry an `error` key")

@test("EX-10", "exec_in_project")
def _():
    with claude_stub("this is not json") as rec:
        code, j, _ = run_exec(need_live_child(), "hello", [])
    eq(code, 1); eq(j["kind"], "error")
    truthy("no parseable JSON" in j["error"], f"got {j.get('error')!r}")

@test("EX-11", "exec_in_project")
def _():
    # --exec-file: content read from a file reaches the worker LITERALLY even with
    # shell metacharacters AND the old heredoc delimiter — the delimiter-collision
    # blocker cannot exist when the request never sits in shell syntax.
    sentinel = Path(tempfile.gettempdir()) / "cboot_NOPE_ex11"
    sentinel.unlink(missing_ok=True)
    payload = "l1 $(touch " + str(sentinel) + ") `id`\n__ASK_REQUEST_EOF__\nrm -rf x\n"
    d = Path(tempfile.mkdtemp(prefix="cboot-req-"))
    (d / "req.txt").write_text(payload)
    try:
        with claude_stub() as rec:
            code, j, _ = run_exec(need_live_child(), None, [], prompt_file=str(d / "req.txt"))
            argv = rec.read_text()
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    eq(code, 0); eq(j["kind"], "result")
    truthy(not sentinel.exists(), "file content must NOT be shell-executed")
    truthy(str(sentinel) in argv, "prompt forwarded to worker argv literally")


# ── switch_command (SW) ──────────────────────────────────────────────

@test("SW-01", "switch_command")
def _():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cboot.switch_command(need_live_child())
    line = out.getvalue().strip()
    eq(code, 0)
    eq(line, f'python cboot.py --project "{(ROOT/LIVE_CHILD).as_posix()}" --launch')

@test("SW-04", "switch_command")
def _():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cboot.switch_command("nonexistent-xyz")
    eq(code, 1); eq(out.getvalue().strip(), "", "stdout must stay empty on error (else-handoff contract)")
    truthy("cboot --switch:" in err.getvalue(), "error to stderr")


# ── build_root_inventory output (RI) ─────────────────────────────────

@test("RI-01", "build_root_inventory")
def _():
    db = ROOT / ".state" / "roots.db"
    if not db.exists():
        raise Fail("roots.db missing — run cboot boot first")
    sf = ROOT / ".codex" / "reactive" / "sqlite" / "sqlite.py"
    spec = importlib.util.spec_from_file_location("s", sf)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    conn = m.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(roots)")}
    # Superset, not equality: the live db may be pre-migration (no canonical_id)
    # or post-migration (roots is rebuilt each boot WITH the walk->spine link
    # column canonical_id). Assert only the stable minimum is PRESENT; do not
    # reject the extra canonical_id column a migrated boot adds.
    stable = {"id", "name", "abs_path", "rel_path", "parent_path", "depth",
              "is_apex", "contains_roots", "agent_enabled", "agent_name",
              "agent_file", "generated_at"}
    truthy(stable <= cols,
           "roots schema missing %s (have %s)" % (sorted(stable - cols), sorted(cols)))
    apex = list(conn.execute("SELECT rel_path,depth,parent_path FROM roots WHERE is_apex=1"))
    eq(len(apex), 1, "exactly one apex row")
    eq(tuple(apex[0]), (".", 0, None), "apex row shape")
    # roots/meta are rebuilt each boot; these two are DURABLE and must be present
    # regardless, because every file in .claude/agents/ depends on them.
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    truthy({"agent_optin", "agent_registry"} <= tables,
           "durable agent tables present: %s" % sorted(tables))
    conn.close()


# ── Addressable agents (AG) ──────────────────────────────────────────
#
# Every AG test builds a throwaway apex in a temp dir and redirects cboot's
# module globals at it. Nothing here reads or writes the live /mnt/claudette
# .claude/agents/ or .state/roots.db — so there is no ring-fence to roll back
# and no way for a test run to leave the live apex altered.

import shutil as _shutil

_PURGE_PY = ROOT / ".codex" / "explicit" / "purge" / "purge.py"


def _load_purge():
    spec = importlib.util.spec_from_file_location("purge_mod", _PURGE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sqlite_factory():
    sf = ROOT / ".codex" / "reactive" / "sqlite" / "sqlite.py"
    spec = importlib.util.spec_from_file_location("sqlite_factory", sf)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@contextlib.contextmanager
def scratch_apex(children=()):
    """A disposable apex with cboot's globals pointed at it.

    children: iterable of (relative_folder, body_text_after_frontmatter).
    """
    tmp = Path(tempfile.mkdtemp(prefix="ctest-ag-"))
    saved = (cboot.ROOT, cboot.STATE, cboot.CLAUDE, cboot.AGENTS_DIR)
    try:
        (tmp / ".claude" / "agents").mkdir(parents=True)
        (tmp / ".state").mkdir(parents=True)
        (tmp / "CLAUDE.md").write_text(
            "---\nroot: true\napex-root: true\nname: apex\n---\n")
        for rel, body in children:
            d = tmp / rel
            d.mkdir(parents=True, exist_ok=True)
            (d / "CLAUDE.md").write_text(
                "---\nroot: true\nname: %s\n---\n\n%s" % (rel.lstrip("~"), body))
        cboot.ROOT = tmp
        cboot.STATE = tmp / ".state"
        cboot.CLAUDE = tmp / ".claude"
        cboot.AGENTS_DIR = tmp / ".claude" / "agents"
        yield tmp
    finally:
        cboot.ROOT, cboot.STATE, cboot.CLAUDE, cboot.AGENTS_DIR = saved
        _shutil.rmtree(tmp, ignore_errors=True)


def _rid_for(conn, rel):
    """The current spine root_id for `rel`, minting one through the module if the
    root has none yet. The single way this harness gives a test root a real
    root_id — used by ag_optin and by every hand-crafted agent_registry insert, so
    a re-keyed row's root_id always names a real identity in roots_register.
    """
    rr = _load_roots_register()
    row = conn.execute(
        "SELECT root_id FROM roots_register WHERE rel_path = ? COLLATE NOCASE"
        " AND valid_to IS NULL", (rel,)).fetchone()
    return row["root_id"] if row else rr.mint(conn, rel)


def ag_optin(apex, rows):
    """Record opt-in decisions the way the interactive prompt would.

    Routed through the identity mutation module so every test root gets a real
    root_id (forward-compatible with the WP-E boot rewire): each root is minted a
    spine row if it has none, then the DECISION is recorded keyed on that root_id
    — a decline through the module's `decline` writer, an enabled decision written
    to agent_optin in the re-keyed (root_id-PK) shape.

    Only the decision is written here — NOT the agent_registry claim. Opening the
    claim (name derivation, the -pj suffix, de-confliction against foreign files)
    is still generate_agents' job in the un-rewired boot, exactly as the AG/WK/MQ
    tests exercise it; pre-opening a claim via open_claim would make every enabled
    root read as `held`, skipping the de-confliction those tests assert and
    colliding two roots that share a base @name on the current-name unique index.
    Once WP-E rewires boot, that claim-open moves behind the module too.
    """
    rr = _load_roots_register()
    conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
    cboot._ensure_agent_tables(conn)
    for rel, enabled, name, desc in rows:
        root_id = _rid_for(conn, rel)
        if enabled:
            conn.execute(
                "INSERT INTO agent_optin (root_id, rel_path, enabled,"
                " requested_name, description, decided_at, decided_by)"
                " VALUES (?, ?, 1, ?, ?, '2026-01-01T00:00:00Z', 'prompt')"
                " ON CONFLICT(root_id) DO UPDATE SET"
                " enabled = 1, rel_path = excluded.rel_path,"
                " requested_name = excluded.requested_name,"
                " description = excluded.description,"
                " decided_at = excluded.decided_at, decided_by = excluded.decided_by",
                (root_id, rel, name, desc))
        else:
            rr.decline(conn, root_id, requested_name=name, description=desc)
    conn.commit()
    conn.close()


def ag_boot(apex):
    rep = cboot.BootReport()
    rows = cboot.build_root_inventory(rep)
    cboot.generate_agents(rep, rows)
    return rep


@test("AG-01", "generate_agents")
def _():
    """Only switched-on roots get a file; a declined root gets none."""
    with scratch_apex([("drawio", "A tool.\n"), ("zMisc", "Misc.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool."), ("zMisc", 0, None, None)])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        truthy((ag / "drawio-pj.md").exists(), "switched-on root has an agent file")
        truthy(not (ag / "zMisc-pj.md").exists(), "declined root has no agent file")


@test("AG-02", "generate_agents")
def _():
    """Nothing is written into the child. Its CLAUDE.md is read, never edited."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        child = apex / "drawio" / "CLAUDE.md"
        before = child.read_bytes()
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        eq(child.read_bytes(), before, "child CLAUDE.md must be byte-identical")


@test("AG-03", "generate_agents")
def _():
    """A forged marker confers nothing, on the one stem the code actually visits.

    The file is planted on the exact name an about-to-be-claimed root will ask
    for, and its marker names that root — so a content-based ownership rule would
    recognise it as cboot's own and overwrite it. Only the registry lookup treats
    it as foreign. Planting it on some unrelated stem would prove nothing: no code
    path visits a name nobody wants.
    """
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        forged = apex / ".claude" / "agents" / "drawio-pj.md"
        forged.write_text('---\nname: drawio\n---\n\n'
                          '<!-- cboot:agent root="drawio" generated="2026-01-01T00:00:00Z" -->\n'
                          'hand-written body\n')
        keep = forged.read_bytes()
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        eq(forged.read_bytes(), keep, "the forged file is not adopted or overwritten")
        truthy((apex / ".claude" / "agents" / "drawio-pj-2.md").exists(),
               "and it blocks the name: %s"
               % sorted(p.name for p in (apex / ".claude" / "agents").iterdir()))


@test("AG-04", "generate_agents")
def _():
    """A non-UTF-8 file in agents/ neither crashes the pass nor is touched."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        blob = apex / ".claude" / "agents" / "cp1252.md"
        blob.write_bytes(b"---\nname: x\n---\n\ncaf\xe9 hand-written\n")
        raw = blob.read_bytes()
        ag_boot(apex)          # must not raise
        eq(blob.read_bytes(), raw, "non-UTF-8 file untouched")


@test("AG-05", "generate_agents")
def _():
    """Our own file, marker stripped by a human: warned, never overwritten."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        f.write_text("---\nname: drawio\n---\n\nI edited this by hand.\n")
        rep = ag_boot(apex)
        truthy("I edited this by hand." in f.read_text(), "hand edit preserved")
        truthy(any("diverged" in w for w in rep.warnings),
               "divergence warned: %r" % (rep.warnings,))


@test("AG-06", "generate_agents")
def _():
    """Opting out closes the claim and removes our file, keeping SCD2 history."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        truthy(f.exists(), "file created first")
        ag_optin(apex, [("drawio", 0, None, None)])
        ag_boot(apex)
        truthy(not f.exists(), "file removed on opt-out")
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        row = conn.execute("SELECT valid_to, close_reason, change_reason"
                           " FROM agent_registry").fetchone()
        conn.close()
        truthy(row[0] is not None, "row closed")
        eq(row[1], "opted-out", "close_reason")
        eq(row[2], "opted-in", "opening change_reason is never rewritten")


@test("AG-07", "generate_agents")
def _():
    """An undecodable child CLAUDE.md is NOT an opt-out — skip, keep, warn."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        before = f.read_bytes()
        (apex / "drawio" / "CLAUDE.md").write_bytes(
            "---\nroot: true\nname: drawio\n---\n\ncafé\n".encode("utf-16"))
        rep = ag_boot(apex)
        truthy(f.exists(), "agent file survives an undecodable child CLAUDE.md")
        eq(f.read_bytes(), before, "agent file unchanged")
        truthy(any("unreadable" in w for w in rep.warnings),
               "skip is reported: %r" % (rep.warnings,))


@test("AG-08", "generate_agents")
def _():
    """A removed root closes the claim and removes the file."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        _shutil.rmtree(apex / "drawio")
        ag_boot(apex)
        truthy(not f.exists(), "file removed when the root is gone")


@test("AG-09", "generate_agents")
def _():
    """A foreign file holding the name forces de-confliction; it is not evicted."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        (apex / ".claude" / "agents" / "drawio-pj.md").write_text(
            "---\nname: drawio\n---\n\nmine, hand-authored\n")
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        truthy("mine, hand-authored" in (ag / "drawio-pj.md").read_text(),
               "pre-existing file always wins")
        truthy((ag / "drawio-pj-2.md").exists(),
               "newcomer de-conflicted: %s" % sorted(p.name for p in ag.iterdir()))


@test("AG-10", "generate_agents")
def _():
    """YAML-hostile names are emitted quoted, so they read back as strings."""
    with scratch_apex([("2025", "A year.\n"), ("null", "Nothing.\n")]) as apex:
        ag_optin(apex, [("2025", 1, "2025", "A year."), ("null", 1, "null", "Nothing.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        truthy('name: "2025-pj"' in (ag / "2025-pj.md").read_text(), "numeric name quoted")
        truthy('name: "null-pj"' in (ag / "null-pj.md").read_text(), "null name quoted")


@test("AG-11", "generate_agents")
def _():
    """cboot's own .md.tmp staging leftovers are swept."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        stale = apex / ".claude" / "agents" / "drawio.md.tmp"
        stale.write_text("interrupted write\n")
        ag_boot(apex)
        truthy(not stale.exists(), ".md.tmp leftover removed")


@test("AG-12", "generate_agents")
def _():
    """Two consecutive materializations are a no-op on agent-file mtimes."""
    with scratch_apex([("drawio", "A tool.\n"), ("~majel", "Steward.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool."),
                        ("~majel", 1, "majel", "Steward.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        before = {p.name: p.stat().st_mtime_ns for p in ag.iterdir()}
        ag_boot(apex)
        after = {p.name: p.stat().st_mtime_ns for p in ag.iterdir()}
        eq(after, before, "no rewrite on an unchanged boot")


@test("AG-13", "decide_agent_optin")
def _():
    """Outside a terminal nothing is prompted and no decision is invented."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        rep = cboot.BootReport()
        rows = cboot.build_root_inventory(rep)
        cboot.decide_agent_optin(rep, rows)     # stdin is not a tty under the runner
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        n = conn.execute("SELECT COUNT(*) FROM agent_optin").fetchone()[0]
        conn.close()
        eq(n, 0, "no decision recorded without a human")
        truthy(any("awaiting a decision" in w for w in rep.warnings),
               "undecided roots reported: %r" % (rep.warnings,))


@test("AG-14", "claims_for")
def _():
    """A missing registry raises rather than returning a partial answer."""
    ao = cboot._agent_ownership()
    with scratch_apex() as apex:
        raised = False
        try:
            ao.claims_for(apex / ".state" / "nope.db", apex / ".claude" / "agents")
        except ao.RegistryUnavailable:
            raised = True
        truthy(raised, "missing db must raise RegistryUnavailable")


@test("AG-15", "owns")
def _():
    """owns() is a path lookup — it never opens the file it is asked about."""
    ao = cboot._agent_ownership()
    with scratch_apex() as apex:
        ag = apex / ".claude" / "agents"
        claims = {ao._key(ag / "a.md"): {"agent_name": "a", "rel_path": "a"}}
        truthy(ao.owns(ag / "a.md", claims), "claimed path owned even with no file on disk")
        truthy(not ao.owns(ag / "b.md", claims), "unclaimed path not owned")


@test("AG-16", "derive_agent_name")
def _():
    ao = cboot._agent_ownership()
    eq(ao.derive_agent_name("~majel"), "majel", "leading punctuation stripped")
    eq(ao.derive_agent_name("zMisc"), "zMisc", "case kept")
    eq(ao.derive_agent_name("a #b"), "a-b", "spaces and punctuation collapse")
    eq(ao.derive_agent_name("we:ird"), "we-ird", "a colon can never reach a filename")


@test("AG-17", "render_marker")
def _():
    """A quote in a rel_path round-trips instead of terminating the attribute."""
    ao = cboot._agent_ownership()
    with scratch_apex() as apex:
        f = apex / ".claude" / "agents" / "x.md"
        rel = 'we"ird/path'
        f.write_text("---\nname: x\n---\n\n%s\nbody\n"
                     % ao.render_marker(rel, "2026-01-01T00:00:00Z"))
        eq(ao.read_marker(f), rel, "marker round-trips a double quote")


@test("AG-34", "suffixed")
def _():
    ao = cboot._agent_ownership()
    eq(ao.suffixed("drawio"), "drawio-pj", "base gets the -pj namespace suffix")
    eq(ao.suffixed("zMisc"), "zMisc-pj", "case preserved through the suffix")
    eq(ao.suffixed(""), "", "an empty base stays empty, never a bare suffix")


@test("AG-35", "generate_agents")
def _():
    """A foreign agent file whose extension differs only in CASE still blocks the
    stem: the de-confliction glob is case-folded (PLAT-05, discovery half). On a
    case-sensitive test FS the variant is a distinct file, so this pins the glob
    pattern, not the mount."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag = apex / ".claude" / "agents"
        foreign = ag / "DRAWIO-PJ.MD"          # a hand-authored case variant
        foreign.write_text("---\nname: drawio-pj\n---\n\nmine, upper-case ext\n")
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        truthy("mine, upper-case ext" in foreign.read_text(),
               "case-variant foreign file untouched")
        truthy((ag / "drawio-pj-2.md").exists(),
               "newcomer de-conflicted around the case variant: %s"
               % sorted(p.name for p in ag.iterdir()))


@test("AG-36", "_write_agent_file")
def _():
    """The writer refuses to clobber a file it does not own and rewrites one it
    does: the syscall-level backstop that survives a case-blind de-confliction
    (PLAT-05, write half). open(..., "x") is what the real mount uses to catch a
    case-variant the glob missed."""
    with scratch_apex() as apex:
        ag = apex / ".claude" / "agents"
        target = ag / "victim-pj.md"
        target.write_text("HAND-AUTHORED - must survive\n")
        rep = cboot.BootReport()
        ok = cboot._write_agent_file(target, "GENERATED\n", rep, owned=False)
        eq(ok, False, "refused to write an unowned pre-existing file")
        truthy("HAND-AUTHORED" in target.read_text(), "the file is left intact")
        truthy(any("refused to overwrite unowned" in w for w in rep.warnings),
               "refusal is reported: %r" % (rep.warnings,))
        rep2 = cboot.BootReport()
        ok2 = cboot._write_agent_file(target, "REWRITTEN\n", rep2, owned=True)
        eq(ok2, True, "an owned file is rewritten")
        eq(target.read_text(), "REWRITTEN\n", "owned rewrite lands")


@test("AG-37", "generate_agents")
def _():
    """A claimed agent file deleted by hand is RE-PROJECTED on the next boot.

    Projection is idempotent but not a one-shot: the durable claim/decision are
    the authority, and the .md file is a projection of them. A human (or a purge,
    or a crash) removing the file must not silently un-address a live project — the
    next generate_agents writes it back from the claim.
    """
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        truthy(f.exists(), "setup: the project has an agent file")
        f.unlink()                                   # a human deletes it by hand
        ag_boot(apex)                                # next boot must re-project it
        truthy(f.exists(), "the deleted owned file is re-projected from the claim")
        truthy('<!-- cboot:agent root="drawio"' in f.read_text(),
               "the re-projected file carries the current marker")
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        n = conn.execute("SELECT COUNT(*) FROM agent_registry"
                         " WHERE valid_to IS NULL").fetchone()[0]
        conn.close()
        eq(n, 1, "and no new claim opened — the same one was re-projected")


@test("AG-38", "generate_agents")
def _():
    """A decision flipped disabled THROUGH THE MODULE sweeps the projected file.

    The complement of AG-37: turning the durable answer off (via the sole writer's
    `decline`, no raw UPDATE) makes the next projection close the claim and remove
    the file. Proves the projection tracks the decision in both directions.
    """
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        truthy(f.exists(), "setup: the project has an agent file")

        rr = _load_roots_register()
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        rid = conn.execute("SELECT root_id FROM roots_register"
                           " WHERE rel_path='drawio' AND valid_to IS NULL").fetchone()[0]
        rr.decline(conn, rid)                        # disable via the module
        conn.commit()
        conn.close()

        ag_boot(apex)
        truthy(not f.exists(), "the projected file is swept when the decision goes off")
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        row = conn.execute("SELECT valid_to, close_reason FROM agent_registry"
                           " WHERE root_id = ?", (rid,)).fetchone()
        conn.close()
        truthy(row["valid_to"] is not None and row["close_reason"] == "opted-out",
               "the claim is closed opted-out: %r" % (dict(row),))


@test("AG-39", "generate_agents")
def _():
    """A moved project's agent file is RE-PROJECTED with the new rel_path.

    After a relink the file's marker still names the identity's PRIOR rel_path.
    Projection must tell that apart from a human edit: a marker naming a rel this
    same identity used to hold is ours to refresh (marker + prose follow the move),
    whereas a marker naming a rel this identity never had stays diverged (AG-05).
    """
    ao = cboot._agent_ownership()
    with scratch_apex([("newhome", "Home.\n")]) as apex:
        db = apex / ".state" / "roots.db"
        rr = _load_roots_register()
        conn = _sqlite_factory().connect(str(db))
        cboot._ensure_agent_tables(conn)
        # An identity minted at 'oldhome', claimed, then relinked to 'newhome':
        # its spine history holds both, its current spine is 'newhome'.
        rid = rr.mint(conn, "oldhome")
        rr.open_claim(conn, rid, "home-pj", "oldhome", ".claude/agents/home-pj.md")
        h = Path(tempfile.mkdtemp(prefix="ctest-ag39-home-"))
        try:
            rr.relink(conn, rid, "newhome", home=h)
        finally:
            _shutil.rmtree(h, ignore_errors=True)
        conn.commit()
        conn.close()
        # Plant the agent file exactly as the day-one boot (at 'oldhome') left it:
        # a valid cboot marker naming the OLD rel_path.
        f = apex / ".claude" / "agents" / "home-pj.md"
        f.write_text("---\nname: home-pj\n---\n\n%s\nprose about oldhome\n"
                     % ao.render_marker("oldhome", "2026-01-01T00:00:00Z"))

        rep = ag_boot(apex)
        txt = f.read_text()
        truthy(ao.marker_matches(f, "newhome"),
               "the marker was refreshed to the current spine rel_path: %r"
               % [l for l in txt.splitlines() if "cboot:agent" in l])
        truthy("newhome" in txt and "oldhome" not in txt,
               "the prose followed the move too")
        truthy(not any("diverged" in w for w in rep.warnings),
               "a move is not a divergence: %r" % (rep.warnings,))


@test("AG-40", "_ensure_agent_tables")
def _():
    """A NOCASE-duplicate rel_path fails the migration LOUD ONCE, and a failed
    migration keeps the old rel_path guard (MEDIUM-1).

    Two ASCII case-variant paths (`Testing`/`testing`) are the same directory on
    this case-insensitive mount, so they would collapse to one root_id and the
    re-key would raise on the PK/unique index — rolling back so user_version stays 0
    and RETRYING identically every boot forever (a permanent wedge). The migration
    now detects them first and raises a clear, actionable error naming the paths;
    the DROP of `idx_agent_cur_path` lives inside the ladder (after the re-key), so
    a failed migration does not also lose the old guard.
    """
    with scratch_apex() as apex:
        db = apex / ".state" / "roots.db"
        conn = sqlite3.connect(db)
        # Legacy (user_version stays 0) shape WITH the old rel_path current-unique
        # index, so we can prove a failed migration does not strip it.
        conn.execute(
            "CREATE TABLE agent_registry ( id INTEGER PRIMARY KEY, agent_name TEXT"
            " NOT NULL, rel_path TEXT NOT NULL, source_folder TEXT NOT NULL,"
            " deconflicted_from TEXT, description TEXT, agent_file TEXT NOT NULL,"
            " valid_from TEXT NOT NULL, valid_to TEXT, change_reason TEXT NOT NULL)")
        conn.execute("CREATE UNIQUE INDEX idx_agent_cur_path"
                     " ON agent_registry(rel_path) WHERE valid_to IS NULL")
        conn.execute(
            "CREATE TABLE agent_optin ( rel_path TEXT PRIMARY KEY, enabled INTEGER"
            " NOT NULL, requested_name TEXT, description TEXT, decided_at TEXT NOT"
            " NULL, decided_by TEXT NOT NULL)")
        for rel in ("Testing", "testing"):     # same directory on this mount
            conn.execute(
                "INSERT INTO agent_optin (rel_path, enabled, decided_at, decided_by)"
                " VALUES (?,1,'2026-01-01T00:00:00Z','prompt')", (rel,))
        conn.commit()
        conn.close()

        conn = _sqlite_factory().connect(str(db))
        raised = None
        try:
            cboot._ensure_agent_tables(conn)
        except sqlite3.IntegrityError as e:
            raised = str(e)
        try:
            conn.rollback()                     # exactly what close() would do
        except sqlite3.Error:
            pass
        conn.close()

        truthy(raised is not None, "the migration raised, it did not silently wedge")
        truthy(raised and "Testing" in raised and "testing" in raised,
               "the error names the colliding paths for a human to fix: %r" % (raised,))

        after = sqlite3.connect(db)
        try:
            ver = after.execute("PRAGMA user_version").fetchone()[0]
            idx = {r[0] for r in after.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
        finally:
            after.close()
        eq(ver, 0, "user_version stays 0 — the failed migration rolled back cleanly")
        truthy("idx_agent_cur_path" in idx,
               "the old rel_path guard survives a failed migration: %s" % sorted(idx))


@test("AG-41", "_ensure_agent_tables")
def _():
    """A casefold-equal but NOCASE-DISTINCT pair migrates cleanly (LOW-2).

    `straße`/`STRASSE` are equal under Python str.casefold (ß -> ss) yet distinct
    under SQLite COLLATE NOCASE (which folds ASCII only). The migration dedups its
    mint population with NOCASE semantics, so the two mint DISTINCT root_ids and
    each optin row joins to its own spine — where a casefold dedup would collapse
    them to one root_id and the STRASSE optin, unable to NOCASE-join the straße
    spine, would trip the row-count guard.
    """
    with scratch_apex() as apex:
        db = apex / ".state" / "roots.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE agent_registry ( id INTEGER PRIMARY KEY, agent_name TEXT"
            " NOT NULL, rel_path TEXT NOT NULL, source_folder TEXT NOT NULL,"
            " deconflicted_from TEXT, description TEXT, agent_file TEXT NOT NULL,"
            " valid_from TEXT NOT NULL, valid_to TEXT, change_reason TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE agent_optin ( rel_path TEXT PRIMARY KEY, enabled INTEGER"
            " NOT NULL, requested_name TEXT, description TEXT, decided_at TEXT NOT"
            " NULL, decided_by TEXT NOT NULL)")
        for rel in ("straße", "STRASSE"):
            conn.execute(
                "INSERT INTO agent_optin (rel_path, enabled, decided_at, decided_by)"
                " VALUES (?,0,'2026-01-01T00:00:00Z','prompt')", (rel,))
        conn.commit()
        conn.close()

        conn = _sqlite_factory().connect(str(db))
        cboot._ensure_agent_tables(conn)        # must NOT trip the row-count guard
        conn.commit()
        rows = conn.execute(
            "SELECT rel_path, root_id FROM roots_register"
            " WHERE valid_to IS NULL AND rel_path IN ('straße','STRASSE')"
            " ORDER BY rel_path").fetchall()
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()

        eq(ver, 1, "the migration completed (user_version=1)")
        eq(len(rows), 2, "both NOCASE-distinct paths minted their own spine row")
        truthy(rows[0]["root_id"] != rows[1]["root_id"],
               "each got a DISTINCT root_id — the pair was not collapsed")


@test("AG-42", "generate_agents")
def _():
    """A relink-then-opt-out SWEEPS the moved agent file, not leaves it stale (LOW-3).

    Opted out before its relinked file is re-projected, the file's marker still
    names the OLD rel_path, so marker_matches(current rel) is false. The close-pass
    sweep now applies the same move-aware ownership the held-refresh uses: a marker
    naming a PAST rel of THIS identity is ours, so the file is swept on opt-out
    instead of misclassed 'diverged, left in place' and stranded forever.
    """
    ao = cboot._agent_ownership()
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)                              # projects drawio-pj.md, marker 'drawio'
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        truthy(f.exists() and ao.marker_matches(f, "drawio"),
               "setup: the file was projected at rel 'drawio'")

        # Read the identity's root_id while 'drawio' is still current, then move the
        # directory on disk and relink to follow — WITHOUT re-projecting (so the
        # marker keeps naming the OLD rel) — and opt the root out.
        db = apex / ".state" / "roots.db"
        conn = _sqlite_factory().connect(str(db))
        rid = _rid_for(conn, "drawio")
        (apex / "newdrawio").mkdir()
        (apex / "newdrawio" / "CLAUDE.md").write_text(
            "---\nroot: true\nname: newdrawio\n---\n\nA tool.\n")
        _shutil.rmtree(apex / "drawio")
        h = Path(tempfile.mkdtemp(prefix="ctest-ag42-home-"))
        try:
            _load_roots_register().relink(conn, rid, "newdrawio", home=h)
        finally:
            _shutil.rmtree(h, ignore_errors=True)
        conn.execute("UPDATE agent_optin SET enabled = 0 WHERE root_id = ?", (rid,))
        conn.commit()
        conn.close()

        truthy(ao.marker_matches(f, "drawio"),
               "the moved file still carries the OLD-rel marker (not re-projected)")

        rep = ag_boot(apex)                        # the close pass runs on the opt-out

        truthy(not f.exists(),
               "the moved-then-opted-out file was swept, not left stale")
        truthy(not any("diverged" in w for w in rep.warnings),
               "and it was not misreported as a divergence: %r" % (rep.warnings,))
        conn = _sqlite_factory().connect(str(db))
        closed = conn.execute(
            "SELECT close_reason FROM agent_registry"
            " WHERE root_id = ? ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
        conn.close()
        eq(closed["close_reason"], "opted-out", "the claim was closed opted-out")


# ── purge side of the same rule (PG) ─────────────────────────────────

@contextlib.contextmanager
def purge_rig(claimed=("gen",), with_db=True):
    tmp = Path(tempfile.mkdtemp(prefix="ctest-pg-"))
    try:
        ag = tmp / ".claude" / "agents"
        ag.mkdir(parents=True)
        (tmp / ".claude" / "skills" / "x").mkdir(parents=True)
        (tmp / ".claude" / "skills" / "x" / "SKILL.md").write_text("shim\n")
        (tmp / ".state").mkdir(parents=True)
        if with_db:
            conn = _sqlite_factory().connect(str(tmp / ".state" / "roots.db"))
            cboot._ensure_agent_tables(conn)
            for n in claimed:
                rid = _rid_for(conn, n)
                conn.execute(
                    "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
                    " description, agent_file, valid_from, change_reason, root_id)"
                    " VALUES (?,?,?,'d',?,'2026-01-01T00:00:00Z','opted-in',?)",
                    (n, n, n, ".claude/agents/%s.md" % n, rid))
            conn.commit()
            conn.close()
        yield tmp, ag
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


GEN_BODY = ('<!-- cboot:agent root="%s" generated="2026-01-01T00:00:00Z" -->\n'
            'generated\n')


def pg_run(pg, root):
    purger = pg.Purger(root, dry_run=False)
    pg._purge_claude_dir(purger, root / ".claude", root)
    return purger


@test("PG-01", "_purge_agents_dir")
def _():
    """Claimed files go; hand-authored files stay."""
    pg = _load_purge()
    with purge_rig() as (root, ag):
        (ag / "gen.md").write_text(GEN_BODY % "gen")
        (ag / "hand.md").write_text("hand written\n")
        pg_run(pg, root)
        truthy(not (ag / "gen.md").exists(), "claimed file removed")
        truthy((ag / "hand.md").exists(), "hand-authored file preserved")


@test("PG-02", "_purge_agents_dir")
def _():
    """A marker-shaped first line confers nothing — purge agrees with cboot."""
    pg = _load_purge()
    with purge_rig() as (root, ag):
        (ag / "forged.md").write_text(
            '<!-- cboot:agent root="gen" generated="2026-01-01T00:00:00Z" -->\n'
            'hand written\n')
        pg_run(pg, root)
        truthy((ag / "forged.md").exists(), "unclaimed marker file preserved")


@test("PG-03", "_purge_agents_dir")
def _():
    """A non-UTF-8 file neither crashes the purge nor is deleted."""
    pg = _load_purge()
    with purge_rig() as (root, ag):
        (ag / "gen.md").write_text(GEN_BODY % "gen")
        (ag / "cp1252.md").write_bytes(b"caf\xe9 hand written\n")
        pg_run(pg, root)                       # must not raise
        truthy((ag / "cp1252.md").exists(), "non-UTF-8 file preserved")
        truthy(not (ag / "gen.md").exists(), "purge ran to completion")


@test("PG-04", "_purge_agents_dir")
def _():
    """A symlinked agents/ is never followed or deleted through."""
    pg = _load_purge()
    with purge_rig() as (root, ag):
        _shutil.rmtree(ag)
        real = root / "real-agents"
        real.mkdir()
        (real / "gen.md").write_text("generated\n")
        try:
            os.symlink(real, ag)
        except (OSError, NotImplementedError):
            return                              # platform cannot symlink; nothing to prove
        p = pg_run(pg, root)
        truthy((real / "gen.md").exists(), "link target contents intact")
        truthy(any("PROTECTED" in s and "agents" in s for s in p.skipped),
               "reported PROTECTED: %r" % (p.skipped,))


@test("PG-05", "_purge_agents_dir")
def _():
    """No registry means cboot owns nothing: preserve everything."""
    pg = _load_purge()
    with purge_rig(with_db=False) as (root, ag):
        (ag / "gen.md").write_text("generated\n")
        (ag / "hand.md").write_text("hand written\n")
        p = pg_run(pg, root)
        truthy((ag / "gen.md").exists() and (ag / "hand.md").exists(),
               "nothing deleted without a registry")
        truthy(any("PRESERVED" in s for s in p.skipped),
               "preservation reported: %r" % (p.skipped,))


@test("PG-06", "_purge_agents_dir")
def _():
    """.md.tmp staging leftovers are reachable and removed."""
    pg = _load_purge()
    with purge_rig() as (root, ag):
        (ag / "gen.md").write_text(GEN_BODY % "gen")
        (ag / "gen.md.tmp").write_text("interrupted\n")
        pg_run(pg, root)
        truthy(not (ag / "gen.md.tmp").exists(), ".md.tmp removed")


@test("PG-07", "_purge_agents_dir")
def _():
    """skills/ is still removed wholesale, and roots.db is on the hard floor."""
    pg = _load_purge()
    with purge_rig() as (root, ag):
        pg_run(pg, root)
        truthy(not (root / ".claude" / "skills").exists(), "skills/ removed")
        truthy(pg._is_protected(root / ".state" / "roots.db", root),
               "roots.db protected in every scope")


# ── Mutation proofs (MU) ─────────────────────────────────────────────
#
# Each proof reverts one fix in memory and asserts the behaviour actually
# changes — so the corresponding test above is discriminating, not incidental.

@test("MU-01", "owns")
def _():
    """Revert ownership to a content heuristic and AG-03 stops de-conflicting.

    A real mutant, not a simulation: owns() is replaced in a loaded copy of the
    module by the rule the design removed — "carries a marker, therefore ours".
    Under it the forged file reads as cboot's own, so its stem is NOT blocked and
    the newcomer never de-conflicts: AG-03's `drawio-pj-2.md` never appears.

    The forged file itself now survives the mutation too — `_write_agent_file`'s
    exclusive create refuses to clobber an unowned dirent (a second, syscall-level
    layer). So the observable AG-03 relies on is the de-confliction, and that is
    what this proof flips.
    """
    ao = cboot._agent_ownership()

    def content_owns(path, claims):
        return ao.read_marker(path) is not None

    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        forged = apex / ".claude" / "agents" / "drawio-pj.md"
        forged.write_text('---\nname: drawio\n---\n\n'
                          '<!-- cboot:agent root="drawio" generated="2026-01-01T00:00:00Z" -->\n'
                          'hand-written body\n')
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])

        # generate_agents loads its own instance of the module on every call, so
        # the mutation has to go through the loader, not through this reference.
        class _Mutant:
            def __getattr__(self, k):
                return getattr(ao, k)
            owns = staticmethod(content_owns)
            RegistryUnavailable = ao.RegistryUnavailable
            AGENTS_REL = ao.AGENTS_REL
            RESERVED_NAMES = ao.RESERVED_NAMES

        saved = cboot._agent_ownership
        cboot._agent_ownership = lambda: _Mutant()
        try:
            ag_boot(apex)
        finally:
            cboot._agent_ownership = saved
        truthy(not (apex / ".claude" / "agents" / "drawio-pj-2.md").exists(),
               "content-ownership stops the stem being blocked, so the newcomer "
               "no longer de-conflicts — AG-03's drawio-pj-2.md never appears, "
               "which is what makes AG-03 discriminating")


@test("MU-02", "generate_agents")
def _():
    """Treat an undecodable CLAUDE.md as readable -> AG-07's file is deleted."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        (apex / "drawio" / "CLAUDE.md").write_bytes(
            "---\nroot: true\nname: drawio\n---\n\ncafé\n".encode("utf-16"))
        original = cboot._read_child_text
        cboot._read_child_text = lambda p: ("missing", "")   # the pre-fix reading
        try:
            ag_boot(apex)
            broke = not f.exists()
        finally:
            cboot._read_child_text = original
        truthy(broke, "mutation must delete the file — otherwise AG-07 proves nothing")


@test("MU-03", "_purge_agents_dir")
def _():
    """Drop the shared module -> purge preserves rather than guessing."""
    pg = _load_purge()
    with purge_rig() as (root, ag):
        (ag / "gen.md").write_text(GEN_BODY % "gen")
        original = pg._agent_ownership
        pg._agent_ownership = lambda: None
        try:
            p = pg_run(pg, root)
        finally:
            pg._agent_ownership = original
        truthy((ag / "gen.md").exists(),
               "without the module purge must delete nothing")
        truthy(any("PRESERVED" in s for s in p.skipped), "and must say so")


# ── Round-1 hardening (AG-18.., PG-08, MU-04..) ──────────────────────

@test("AG-18", "build_root_inventory")
def _():
    """A failed walk returns None, not [] — the two must be distinguishable."""
    with scratch_apex([("alpha", "A.\n")]) as apex:
        rep = cboot.BootReport()
        truthy(cboot.build_root_inventory(rep) is not None, "a good walk returns rows")

        class _Boom:
            @staticmethod
            def connect(*a, **k):
                raise sqlite3.OperationalError("simulated inventory write failure")

        saved = cboot._load_module
        cboot._load_module = lambda p: _Boom if p.name == "sqlite.py" else saved(p)
        try:
            rows = cboot.build_root_inventory(cboot.BootReport())
        finally:
            cboot._load_module = saved
        eq(rows, None, "a failed walk must be unusable, not merely empty")


@test("MU-04", "generate_agents")
def _():
    """An empty inventory deletes NOTHING, because absence is not evidence.

    The defence-in-depth half of AG-18. Even if a caller ignored the None guard
    and passed an empty row list, no claim may close: closing requires positive
    evidence the project is gone, and both projects are plainly still on disk.
    Reading walk-absence as deletion was the same defect four times over — a
    failed inventory, an undecodable CLAUDE.md, an undecodable ancestor, and a
    root excluded by a visibility rule — so it is fixed at the source rather than
    guarded at each call site.
    """
    with scratch_apex([("alpha", "A.\n"), ("beta", "B.\n")]) as apex:
        ag_optin(apex, [("alpha", 1, "alpha", "A."), ("beta", 1, "beta", "B.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        eq(sorted(p.name for p in ag.iterdir()), ["alpha-pj.md", "beta-pj.md"], "setup")
        rep = cboot.BootReport()
        cboot.generate_agents(rep, [])            # what `return []` used to feed
        eq(sorted(p.name for p in ag.iterdir()), ["alpha-pj.md", "beta-pj.md"],
           "both agents survive an empty inventory")
        truthy(any("still present" in w for w in rep.warnings),
               "and the skip is reported: %r" % (rep.warnings,))


@test("MU-05", "generate_agents")
def _():
    """Revert re-projection of a deleted owned file -> AG-37's file stays gone.

    A real mutant, not a simulation: `_write_agent_file` is wrapped so that when
    the target is ABSENT it reports success WITHOUT writing — the reverted
    behaviour of a projection that only rewrites a file it can already see. Under
    it, the hand-deleted claimed file is never re-created, so AG-37's `f.exists()`
    flips to False. That is what makes AG-37 discriminating rather than incidental.
    """
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio-pj.md"
        f.unlink()
        real = cboot._write_agent_file

        def skip_absent(target, content, report, *, owned):
            if not target.exists():          # the reverted behaviour: never (re)create
                return True
            return real(target, content, report, owned=owned)

        cboot._write_agent_file = skip_absent
        try:
            ag_boot(apex)
            broke = not f.exists()
        finally:
            cboot._write_agent_file = real
        truthy(broke, "mutation must leave the file gone — otherwise AG-37 proves nothing")


@test("AG-19", "build_root_inventory")
def _():
    """Two dirents resolving to one root must not fail the whole inventory."""
    with scratch_apex([("alpha", "A.\n")]) as apex:
        try:
            os.symlink(apex / "alpha", apex / "alpha-link")
        except (OSError, NotImplementedError):
            return                                        # platform cannot symlink
        ag_optin(apex, [("alpha", 1, "alpha", "A.")])
        rep = cboot.BootReport()
        rows = cboot.build_root_inventory(rep)
        truthy(rows is not None,
               "a convenience symlink inside the apex must not break the walk: %r"
               % (rep.warnings,))
        cboot.generate_agents(rep, rows)
        truthy((apex / ".claude" / "agents" / "alpha-pj.md").exists(), "agent still generated")


@test("AG-20", "generate_agents")
def _():
    """A closed claim stops looking owned, so its file blocks its own @name.

    Without this, a file left in place because it had diverged still reads as
    ours, fails to block its stem, and is clobbered by the next root to want
    that name — silently destroying a human's edit while the report says the
    file was left alone.
    """
    HUMAN = "HUMAN-AUTHORED PARAGRAPH"
    with scratch_apex([("old-home", "Old.\n"), ("new-home", "New.\n")]) as apex:
        ag_optin(apex, [("old-home", 1, "tools", "Old tools."),
                        ("new-home", 0, None, None)])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        f = ag / "tools-pj.md"
        truthy(f.exists(), "setup: tools-pj.md claimed by old-home")

        f.write_text("---\nname: tools\n---\n\n%s\n" % HUMAN)   # a human edits it
        _shutil.rmtree(apex / "old-home")                        # its project goes away
        ag_optin(apex, [("new-home", 1, "tools", "New tools.")])  # newcomer wants the name
        ag_boot(apex)

        truthy(f.exists() and HUMAN in f.read_text(), "the human's edit survives")
        truthy((ag / "tools-pj-2.md").exists(),
               "newcomer de-conflicted: %s" % sorted(p.name for p in ag.iterdir()))


@test("AG-21", "_ensure_agent_tables")
def _():
    """A registry created before close_reason existed is migrated, not left to crash.

    CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so without an
    explicit migration every claim-closing UPDATE fails with "no such column"
    and takes the whole boot down with it.
    """
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        db = apex / ".state" / "roots.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE agent_registry ( id INTEGER PRIMARY KEY, agent_name TEXT NOT NULL,"
            " rel_path TEXT NOT NULL, source_folder TEXT NOT NULL, deconflicted_from TEXT,"
            " description TEXT, agent_file TEXT NOT NULL, valid_from TEXT NOT NULL,"
            " valid_to TEXT, change_reason TEXT NOT NULL)")
        conn.execute("CREATE UNIQUE INDEX agent_registry_current_name"
                     " ON agent_registry(agent_name)")
        conn.execute(
            "INSERT INTO agent_registry (agent_name, rel_path, source_folder, description,"
            " agent_file, valid_from, change_reason) VALUES ('drawio','drawio','drawio',"
            "'A tool.','.claude/agents/drawio.md','2026-01-01T00:00:00Z','opted-in')")
        conn.commit()
        conn.close()
        truthy("close_reason" not in {r[1] for r in sqlite3.connect(db).execute(
            "PRAGMA table_info(agent_registry)")}, "setup: legacy shape")

        ag_boot(apex)
        cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(agent_registry)")}
        truthy("close_reason" in cols, "close_reason added: %s" % sorted(cols))
        idx = {r[0] for r in sqlite3.connect(db).execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='agent_registry'")}
        truthy("agent_registry_current_name" not in idx,
               "superseded unconditional index dropped: %s" % sorted(idx))

        # And the close path now works instead of aborting the boot.
        f = apex / ".claude" / "agents" / "drawio.md"
        truthy(f.exists(), "agent file present before removal")
        _shutil.rmtree(apex / "drawio")
        ag_boot(apex)                                     # must not raise
        truthy(not f.exists(), "file removed")
        row = sqlite3.connect(db).execute(
            "SELECT valid_to, close_reason FROM agent_registry"
            " ORDER BY id DESC LIMIT 1").fetchone()
        truthy(row[0] is not None and row[1] == "root-removed", "row closed: %r" % (row,))


@test("AG-22", "generate_agents")
def _():
    """A registry error degrades to a warning; it does not abort the boot."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        # A schema surprise CREATE TABLE IF NOT EXISTS cannot repair: the table
        # exists, so it is left alone, and the next statement against it fails.
        conn.execute("DROP TABLE agent_optin")
        conn.execute("CREATE TABLE agent_optin (rel_path TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()
        rep = cboot.BootReport()
        rows = cboot.build_root_inventory(rep)
        cboot.generate_agents(rep, rows)                   # must not raise
        truthy(any("Agents" in w for w in rep.warnings),
               "the failure is reported: %r" % (rep.warnings,))


@test("PG-08", "_purge_agents_dir")
def _():
    """purge preserves a claimed file a human has edited, matching cboot.

    Ownership is still the registry lookup; the marker is consulted only to
    DECLINE a deletion, which can never widen what purge removes.
    """
    pg = _load_purge()
    with purge_rig() as (root, ag):
        marked = ag / "gen.md"
        marked.write_text(
            '<!-- cboot:agent root="gen" generated="2026-01-01T00:00:00Z" -->\ngenerated\n')
        pg_run(pg, root)
        truthy(not marked.exists(), "an untouched generated file is still removed")

    with purge_rig() as (root, ag):
        edited = ag / "gen.md"
        edited.write_text("---\nname: gen\n---\n\nI edited this by hand.\n")
        p = pg_run(pg, root)
        truthy(edited.exists(), "a claimed file whose marker is gone is preserved")
        truthy(any("hand-edited" in s for s in p.skipped),
               "and reported: %r" % (p.skipped,))


# ── Round-2 hardening (AG-23.., PG-09..) ─────────────────────────────

@test("AG-23", "build_root_inventory")
def _():
    """A root symlinked in from outside the apex is ADMITTED, by its dirent path.

    discover_roots follows directory symlinks, so a root's target can sit outside
    the apex; resolving the row's path then broke relative_to() with an uncaught
    ValueError that killed the boot. Excluding such roots instead was worse — it
    made the close loop read a live project as deleted. A project a user
    symlinked into the apex is a real project at a real in-apex path, and
    child_propagate already provisions it.
    """
    outside = Path(tempfile.mkdtemp(prefix="ctest-outside-"))
    try:
        (outside / "CLAUDE.md").write_text("---\nroot: true\nname: outsider\n---\n\nO.\n")
        with scratch_apex([("alpha", "A.\n")]) as apex:
            try:
                os.symlink(outside, apex / "linked")
            except (OSError, NotImplementedError):
                return
            rep = cboot.BootReport()
            rows = cboot.build_root_inventory(rep)          # must not raise
            truthy(rows is not None, "the walk completes")
            rels = {r["rel_path"] for r in rows}
            truthy("linked" in rels, "the symlinked root is admitted: %s" % sorted(rels))
            ag_optin(apex, [("linked", 1, "outsider", "O.")])
            cboot.generate_agents(cboot.BootReport(), cboot.build_root_inventory(rep))
            truthy((apex / ".claude" / "agents" / "outsider-pj.md").exists(),
                   "and it can be addressable like any other project")
    finally:
        _shutil.rmtree(outside, ignore_errors=True)


@test("AG-24", "build_root_inventory")
def _():
    """A symlink pointing at a `_` or `.` directory does not launder it in.

    discover_roots filters on the DIRENT name, so an ordinarily-named link to an
    invisible or Claude-internal directory would otherwise make it addressable.
    Visibility is not negotiable, so this exclusion stays — and it is safe only
    because a claim now closes on positive evidence of removal rather than on
    absence from the walk.
    """
    for target_name in ("_private", ".internal"):
        with scratch_apex([]) as apex:
            hidden = apex / target_name
            hidden.mkdir()
            (hidden / "CLAUDE.md").write_text(
                "---\nroot: true\nname: hidden\n---\n\nH.\n")
            try:
                os.symlink(hidden, apex / "visible")
            except (OSError, NotImplementedError):
                return
            rep = cboot.BootReport()
            rows = cboot.build_root_inventory(rep)
            rels = {r["rel_path"] for r in rows}
            truthy("visible" not in rels and target_name not in rels,
                   "%s stays out of the inventory: %s" % (target_name, sorted(rels)))


@test("AG-25", "generate_agents")
def _():
    """An undecodable PARENT CLAUDE.md must not delete its nested roots' agents.

    An unreadable CLAUDE.md removes its whole subtree from the walk, not just
    itself. Reading that as "these projects were deleted" closed the claims of
    perfectly healthy children.
    """
    with scratch_apex([("grp", "Group.\n"), ("grp/a", "A.\n"), ("grp/b", "B.\n")]) as apex:
        ag_optin(apex, [("grp", 0, None, None),
                        ("grp/a", 1, "aa", "A."), ("grp/b", 1, "bb", "B.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        eq(sorted(p.name for p in ag.iterdir()), ["aa-pj.md", "bb-pj.md"], "setup")

        (apex / "grp" / "CLAUDE.md").write_bytes(
            "---\nroot: true\nname: grp\n---\n\ncafé\n".encode("utf-16"))
        rep = ag_boot(apex)
        eq(sorted(p.name for p in ag.iterdir()), ["aa-pj.md", "bb-pj.md"],
           "the children's agents survive their parent being unreadable")
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        n = conn.execute("SELECT COUNT(*) FROM agent_registry"
                         " WHERE valid_to IS NULL").fetchone()[0]
        conn.close()
        eq(n, 2, "both claims stay open")


@test("AG-26", "generate_agents")
def _():
    """A stale decision does not reserve an @name forever.

    A renamed or deleted project left an agent_optin row nothing ever cleaned up,
    and the prompt kept treating its name as taken.
    """
    with scratch_apex([("beta", "B.\n")]) as apex:
        ag_optin(apex, [("gone-away", 1, "shared", "Old."), ("beta", 1, "shared", "New.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        truthy((ag / "shared-pj.md").exists(),
               "the live project gets the name the dead one was holding: %s"
               % sorted(p.name for p in ag.iterdir()))


@test("AG-27", "generate_agents")
def _():
    """A description containing the marker placeholder text cannot break the file."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "Handles @@MARKER@@ tokens in text.")])
        ag_boot(apex)
        text = (apex / ".claude" / "agents" / "drawio-pj.md").read_text()
        truthy('description: "Project agent for drawio \u2014 Handles @@MARKER@@ tokens in text."' in text,
               "the description survives verbatim under the role prefix")
        eq(text.count("<!-- cboot:agent root="), 1, "exactly one marker in the file")


@test("AG-28", "marker_matches")
def _():
    """marker_matches treats a missing and a retargeted marker the same way."""
    ao = cboot._agent_ownership()
    with scratch_apex() as apex:
        f = apex / ".claude" / "agents" / "x.md"
        f.write_text("---\nname: x\n---\n\n%s\nbody\n"
                     % ao.render_marker("drawio", "2026-01-01T00:00:00Z"))
        truthy(ao.marker_matches(f, "drawio"), "our own marker matches")
        truthy(not ao.marker_matches(f, "other"), "a marker for another root does not")
        f.write_text("---\nname: x\n---\n\nhand written\n")
        truthy(not ao.marker_matches(f, "drawio"), "no marker does not")


@test("PG-09", "_purge_agents_dir")
def _():
    """purge preserves a claimed file whose marker was ALTERED, matching cboot.

    The first version of this rule only caught a marker that was GONE. A marker
    edited to name a different root is the same act — a human in the file — and
    the two callers disagreed on it until the predicate moved into the module.
    """
    pg = _load_purge()
    with purge_rig() as (root, ag):
        f = ag / "gen.md"
        f.write_text('<!-- cboot:agent root="somewhere-else" generated="2026-01-01T00:00:00Z" -->\n'
                     'and my own paragraph\n')
        p = pg_run(pg, root)
        truthy(f.exists(), "a retargeted marker is preserved, not deleted")
        truthy(any("hand-edited" in s for s in p.skipped), "and reported: %r" % (p.skipped,))


@test("PG-10", "_purge_agents_dir")
def _():
    """cboot and purge agree on every marker state for a claimed file."""
    pg = _load_purge()
    ao = cboot._agent_ownership()
    cases = [
        ('<!-- cboot:agent root="gen" generated="2026-01-01T00:00:00Z" -->\nbody\n', True),
        ('<!-- cboot:agent root="elsewhere" generated="2026-01-01T00:00:00Z" -->\nbody\n', False),
        ("no marker at all\n", False),
        ("", False),
    ]
    for body, purge_should_delete in cases:
        with purge_rig() as (root, ag):
            f = ag / "gen.md"
            f.write_text(body)
            cboot_would_rewrite = ao.marker_matches(f, "gen")
            pg_run(pg, root)
            deleted = not f.exists()
            eq(deleted, purge_should_delete, "purge verdict for %r" % body[:40])
            eq(deleted, cboot_would_rewrite,
               "purge and cboot must agree for %r" % body[:40])


@test("AG-29", "_root_is_gone")
def _():
    """A live project excluded from the walk keeps its agent, across repeated boots.

    The exact scenario that made excluding out-of-apex roots worse than crashing:
    the project is still on disk, its CLAUDE.md still reads, its opt-in row still
    says yes — and it silently lost its agent file and had its claim closed, with
    only an inventory warning that never mentioned agents. It never self-healed.
    """
    with scratch_apex([("delivery", "D.\n")]) as apex:
        ag_optin(apex, [("delivery", 1, "delivery", "D.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "delivery-pj.md"
        truthy(f.exists(), "setup: the project has an agent")

        # Exclude it from the walk without deleting it, exactly as a visibility
        # rule would. Three consecutive boots must all leave it alone.
        real = cboot.build_root_inventory

        def without_delivery(report):
            rows = real(report)
            return None if rows is None else [r for r in rows if r["rel_path"] != "delivery"]

        cboot.build_root_inventory = without_delivery
        try:
            for i in range(3):
                rep = cboot.BootReport()
                cboot.generate_agents(rep, cboot.build_root_inventory(rep))
                truthy(f.exists(), "agent survives boot %d of the exclusion" % (i + 1))
        finally:
            cboot.build_root_inventory = real

        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        n = conn.execute("SELECT COUNT(*) FROM agent_registry"
                         " WHERE valid_to IS NULL").fetchone()[0]
        conn.close()
        eq(n, 1, "and its claim stays open")


@test("AG-30", "_root_is_gone")
def _():
    """A project that really was deleted still gets its claim closed."""
    with scratch_apex([("alpha", "A.\n")]) as apex:
        eq(cboot._root_is_gone("alpha")[0], False, "a live root is not gone")
        _shutil.rmtree(apex / "alpha")
        eq(cboot._root_is_gone("alpha")[0], True, "a deleted root is gone")

    with scratch_apex([("beta", "B.\n")]) as apex:
        (apex / "beta" / "CLAUDE.md").unlink()
        eq(cboot._root_is_gone("beta")[0], True, "a root with no CLAUDE.md is gone")

    with scratch_apex([("gamma", "G.\n")]) as apex:
        (apex / "gamma" / "CLAUDE.md").write_text("---\nname: gamma\n---\n\nno longer a root\n")
        eq(cboot._root_is_gone("gamma")[0], True, "dropping root: true is a real removal")

    with scratch_apex([("delta", "D.\n")]) as apex:
        (apex / "delta" / "CLAUDE.md").write_bytes(
            "---\nroot: true\nname: delta\n---\n\ncafé\n".encode("utf-16"))
        eq(cboot._root_is_gone("delta")[0], False, "an unreadable CLAUDE.md is not evidence")


@test("AG-31", "build_root_inventory")
def _():
    """An apex under a dot- or underscore-prefixed directory still finds its roots.

    The visibility check must be APEX-RELATIVE. Scanning the whole absolute
    resolved path made the apex's own ancestors decide the verdict, so an install
    at ~/.local/share/claudette — or this repo's own mirror apex under .tmp/ —
    dropped every descendant on every boot, permanently.
    """
    for holder in (".local", "_vault", "normal"):
        base = Path(tempfile.mkdtemp(prefix="ctest-holder-"))
        try:
            apex = base / holder / "apexroot"
            (apex / ".claude" / "agents").mkdir(parents=True)
            (apex / ".state").mkdir(parents=True)
            (apex / "CLAUDE.md").write_text(
                "---\nroot: true\napex-root: true\nname: apex\n---\n")
            for c in ("alpha", "beta"):
                (apex / c).mkdir()
                (apex / c / "CLAUDE.md").write_text(
                    "---\nroot: true\nname: %s\n---\n\n%s desc.\n" % (c, c))
            saved = (cboot.ROOT, cboot.STATE, cboot.CLAUDE, cboot.AGENTS_DIR)
            cboot.ROOT, cboot.STATE = apex, apex / ".state"
            cboot.CLAUDE, cboot.AGENTS_DIR = apex / ".claude", apex / ".claude" / "agents"
            try:
                rep = cboot.BootReport()
                rows = cboot.build_root_inventory(rep)
                rels = sorted(r["rel_path"] for r in rows)
                eq(rels, [".", "alpha", "beta"],
                   "apex under %r must still see its children (warnings: %r)"
                   % (holder, rep.warnings))
            finally:
                cboot.ROOT, cboot.STATE, cboot.CLAUDE, cboot.AGENTS_DIR = saved
        finally:
            _shutil.rmtree(base, ignore_errors=True)


@test("AG-32", "build_root_inventory")
def _():
    """A symlink alias beside its target does not evict the real project."""
    with scratch_apex([("alpha", "A.\n")]) as apex:
        try:
            os.symlink(apex / "alpha", apex / "zzz-alias")
        except (OSError, NotImplementedError):
            return
        for _attempt in range(3):
            rep = cboot.BootReport()
            rows = cboot.build_root_inventory(rep)
            rels = sorted(r["rel_path"] for r in rows)
            eq(rels, [".", "alpha"],
               "the real directory survives dedup, not the alias: %s" % rels)


@test("AG-33", "_resolve_target")
def _():
    """--project accepts exactly the roots the inventory admits.

    A project symlinked into the apex is in the inventory and has an @name; if
    _resolve_target resolved through the link it rejected that same project as
    "outside apex", so the two disagreed on what counts as a project.
    """
    outside = Path(tempfile.mkdtemp(prefix="ctest-outside-"))
    try:
        (outside / "CLAUDE.md").write_text("---\nroot: true\nname: outsider\n---\n\nO.\n")
        with scratch_apex([]) as apex:
            try:
                os.symlink(outside, apex / "linked")
            except (OSError, NotImplementedError):
                return
            saved = cboot.ROOT
            cboot.ROOT = apex
            try:
                p, err = cboot._resolve_target("linked")
                eq(err, None, "a symlinked-in project resolves: %r" % (err,))
                # And traversal is still refused.
                _, err2 = cboot._resolve_target("../escape")
                truthy(err2 is not None, "`..` traversal is still rejected")
            finally:
                cboot.ROOT = saved
    finally:
        _shutil.rmtree(outside, ignore_errors=True)


# ── Round 3: the walk, separated (WK) ────────────────────────────────

@test("WK-01", "_classify_root")
def _():
    """Policy is a pure function of paths — testable with no filesystem at all.

    This is the point of separating it. Every regression in this area came from
    policy being tangled with discovery and de-duplication inside one loop, where
    it could only be exercised through a full boot.
    """
    apex = Path("/apex")
    cases = [
        (Path("/apex/alpha"),            "alpha",       None),
        (Path("/apex/a/b"),              "a/b",         None),
        (Path("/apex/_private"),         "_private",    "resolves into `_private`"),
        (Path("/apex/.internal"),        ".internal",   "resolves into `.internal`"),
        (Path("/apex/a/_x/b"),           "a/_x/b",      "resolves into `_x`"),
        (Path("/apex/a/.x/b"),           "a/.x/b",      "resolves into `.x`"),
        (Path("/elsewhere/alpha"),       None,          "not under the apex"),
    ]
    for dirent, want_rel, want_reason in cases:
        rel, reason = cboot._classify_root(dirent, apex)
        eq(rel, want_rel, "rel for %s" % dirent)
        if want_reason is None:
            eq(reason, None, "reason for %s" % dirent)
        else:
            truthy(reason and want_reason in reason,
                   "reason for %s: %r" % (dirent, reason))


@test("WK-02", "_classify_root")
def _():
    """The apex's OWN ancestors never decide the verdict.

    An apex at ~/.local/share/claudette, or this repo's mirror apex under .tmp/,
    dropped every descendant on every boot when this check went absolute.
    """
    for apex in (Path("/home/u/.local/share/claudette"),
                 Path("/mnt/claudette/.tmp/mut-ag/apex"),
                 Path("/srv/_vault/claudette")):
        rel, reason = cboot._classify_root(apex / "alpha", apex)
        eq(rel, "alpha", "rel under %s" % apex)
        eq(reason, None, "apex ancestors must not exclude a child (apex=%s)" % apex)


@test("WK-03", "_select_roots")
def _():
    """Selection returns BOTH what it admitted and what it excluded, by reason."""
    with scratch_apex([("alpha", "A.\n")]) as apex:
        hidden = apex / "_private"
        hidden.mkdir()
        (hidden / "CLAUDE.md").write_text("---\nroot: true\nname: p\n---\n\nP.\n")
        try:
            os.symlink(hidden, apex / "visible")
        except (OSError, NotImplementedError):
            return
        admitted, excluded = cboot._select_roots(cboot.BootReport(), apex.resolve())
        eq(sorted(d.name for d in admitted), ["alpha"], "admitted")
        eq(sorted(excluded), ["visible"], "excluded, keyed by rel_path")
        truthy("_private" in excluded["visible"], "with a reason: %r" % excluded)


@test("WK-04", "_walk_candidate_roots")
def _():
    """Discovery is deterministic, and prefers a real directory over an alias."""
    with scratch_apex([("alpha", "A.\n")]) as apex:
        try:
            os.symlink(apex / "alpha", apex / "aaa-alias")
        except (OSError, NotImplementedError):
            return
        seen = [tuple(p.name for p in cboot._walk_candidate_roots(apex.resolve()))
                for _ in range(3)]
        eq(len(set(seen)), 1, "stable across runs: %r" % (seen,))
        # The alias sorts first alphabetically; the real directory must still win.
        eq(seen[0][0], "alpha", "real directory ordered ahead of the alias: %r" % (seen[0],))


@test("WK-05", "generate_agents")
def _():
    """An excluded root can NEVER cause a deletion — proven by excluding everything.

    The structural guarantee the redesign exists to provide. The policy is
    replaced with one that rejects every root, which is the most hostile
    filtering change possible; not one agent file may be removed, and no claim
    may close, across repeated boots.
    """
    with scratch_apex([("alpha", "A.\n"), ("beta", "B.\n")]) as apex:
        ag_optin(apex, [("alpha", 1, "alpha", "A."), ("beta", 1, "beta", "B.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        eq(sorted(p.name for p in ag.iterdir()), ["alpha-pj.md", "beta-pj.md"], "setup")

        real = cboot._classify_root
        cboot._classify_root = lambda d, apex_abs: (
            d.relative_to(apex_abs).as_posix(), "excluded by a hostile policy")
        try:
            for i in range(3):
                rep = cboot.BootReport()
                rows = cboot.build_root_inventory(rep)
                cboot.generate_agents(rep, rows)
                eq(sorted(p.name for p in ag.iterdir()), ["alpha-pj.md", "beta-pj.md"],
                   "no file removed on boot %d of a total exclusion" % (i + 1))
        finally:
            cboot._classify_root = real

        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        n = conn.execute("SELECT COUNT(*) FROM agent_registry"
                         " WHERE valid_to IS NULL").fetchone()[0]
        conn.close()
        eq(n, 2, "and no claim closed")


@test("WK-06", "RootRows")
def _():
    """RootRows behaves as the row list every existing caller expects."""
    rows = cboot.RootRows([{"rel_path": "a"}, {"rel_path": "b"}], {"c": "why"})
    eq(len(rows), 2, "len")
    eq([r["rel_path"] for r in rows], ["a", "b"], "iteration")
    eq(rows.excluded, {"c": "why"}, "exclusions carried alongside")
    eq(cboot.RootRows([]).excluded, {}, "defaults to empty")


@test("WK-07", "_select_roots")
def _():
    """An unreadable directory under the apex never aborts the boot.

    iterdir/is_dir/exists propagate EACCES and EIO — Python swallows only
    ENOENT/ENOTDIR/EBADF/ELOOP — so one unreadable directory used to kill the
    whole boot with a bare traceback, before the report, the git hooks or the
    launch. Reachable here without any chmod: this apex admits symlinked-in
    external projects on a drvfs mount.
    """
    with scratch_apex([("alpha", "A.\n"), ("beta", "B.\n")]) as apex:
        ag_optin(apex, [("alpha", 1, "alpha", "A."), ("beta", 1, "beta", "B.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        eq(sorted(p.name for p in ag.iterdir()), ["alpha-pj.md", "beta-pj.md"], "setup")

        try:
            os.chmod(apex / "beta", 0o000)
            blocked = not os.access(apex / "beta" / "CLAUDE.md", os.R_OK)
        except OSError:
            blocked = False
        if not blocked:
            return                      # running as root, or chmod is a no-op here

        try:
            for i in range(2):
                rep = cboot.BootReport()
                rows = cboot.build_root_inventory(rep)     # must not raise
                truthy(rows is not None, "the walk completes despite an unreadable dir")
                cboot.generate_agents(rep, rows)
                eq(sorted(p.name for p in ag.iterdir()), ["alpha-pj.md", "beta-pj.md"],
                   "no agent removed on boot %d" % (i + 1))
        finally:
            os.chmod(apex / "beta", 0o755)


@test("WK-08", "_root_is_gone")
def _():
    """A directory that cannot be stat'd is not a directory known to be gone."""
    with scratch_apex([("alpha", "A.\n"), ("grp", "G.\n"), ("grp/kid", "K.\n")]) as apex:
        try:
            os.chmod(apex / "grp", 0o000)
            blocked = not os.access(apex / "grp" / "kid", os.R_OK)
        except OSError:
            blocked = False
        if not blocked:
            return
        try:
            gone, why = cboot._root_is_gone("grp/kid")      # must not raise
            eq(gone, False, "unreadable is never evidence of removal (%s)" % why)
        finally:
            os.chmod(apex / "grp", 0o755)


@test("WK-09", "_select_roots")
def _():
    """A nested root reached through a symlinked ancestor loses to its real path.

    is_symlink() tests only the LAST component, so `alias/sub` and `real/sub` are
    both non-symlinks and the tie broke on the name alone — an alias sorting
    first took the row, forking one project into two identities that never
    reconciled across boots.
    """
    with scratch_apex([("real", "R.\n"), ("real/sub", "S.\n")]) as apex:
        ag_optin(apex, [("real", 1, "real", "R."), ("real/sub", 1, "sub", "S.")])
        ag_boot(apex)
        try:
            os.symlink(apex / "real", apex / "aaa-alias")   # sorts BEFORE "real"
        except (OSError, NotImplementedError):
            return
        for i in range(3):
            rep = cboot.BootReport()
            rows = cboot.build_root_inventory(rep)
            rels = sorted(r["rel_path"] for r in rows)
            truthy("real/sub" in rels,
                   "the real nested path keeps the row on boot %d: %s" % (i + 1, rels))
            truthy("aaa-alias/sub" not in rels,
                   "the aliased path does not take it: %s" % rels)
            cboot.generate_agents(rep, rows)


@test("WK-10", "_select_roots")
def _():
    """A de-duplicated alias is RECORDED in .excluded, not dropped silently.

    De-duplication is the third way a discovered root leaves the row set. An
    unrecorded drop is invisible to generate_agents, leaving only the weaker
    positive test between it and a deletion — so the structural guarantee is
    only worth having if every exit from the row set goes through .excluded.
    """
    with scratch_apex([("real", "R.\n")]) as apex:
        try:
            os.symlink(apex / "real", apex / "zz-alias")
        except (OSError, NotImplementedError):
            return
        rep = cboot.BootReport()
        rows = cboot.build_root_inventory(rep)
        eq(sorted(r["rel_path"] for r in rows), [".", "real"], "the real path is admitted")
        truthy("zz-alias" in rows.excluded,
               "the alias is recorded, not silently dropped: %r" % (dict(rows.excluded),))
        truthy("real" in rows.excluded["zz-alias"],
               "with a reason naming what it duplicates: %r" % (rows.excluded,))


@test("WK-11", "_reached_via_symlink")
def _():
    """True if ANY component below the apex is a symlink, not just the last."""
    with scratch_apex([("real", "R.\n"), ("real/sub", "S.\n")]) as apex:
        a = apex.resolve()
        eq(cboot._reached_via_symlink(apex / "real", a), False, "a real directory")
        eq(cboot._reached_via_symlink(apex / "real" / "sub", a), False, "a real nested dir")
        try:
            os.symlink(apex / "real", apex / "alias")
        except (OSError, NotImplementedError):
            return
        eq(cboot._reached_via_symlink(apex / "alias", a), True, "the link itself")
        eq(cboot._reached_via_symlink(apex / "alias" / "sub", a), True,
           "a path THROUGH the link — the case is_symlink() alone misses")


@test("WK-12", "generate_agents")
def _():
    """A traversal in a stored requested_name cannot escape the agents directory.

    Only the derived fallback was sanitized, so a row written by hand or by
    future tooling reached the filename raw — and `../..` made the write clobber
    a user file outside the directory that ownership checks and purge ever look
    at, with no warning.
    """
    with scratch_apex([("three", "T.\n")]) as apex:
        victim = apex / "VICTIM.md"
        victim.write_text("# the user's own notes\n")
        ag_optin(apex, [("three", 1, "../../VICTIM", "T.")])
        ag_boot(apex)
        eq(victim.read_text(), "# the user's own notes\n", "the user's file is untouched")
        for f in (apex / ".claude" / "agents").iterdir():
            truthy(f.parent.resolve() == (apex / ".claude" / "agents").resolve(),
                   "every written file is inside the agents directory: %s" % f)


@test("WK-13", "generate_agents")
def _():
    """A claim held by a root skipped this boot still reserves its @name.

    Otherwise a newcomer takes a case-variant of it — the same file on a
    case-insensitive mount — overwriting the skipped project's agent in a way
    that never repairs itself.
    """
    with scratch_apex([("one", "O.\n"), ("two", "T.\n")]) as apex:
        ag_optin(apex, [("one", 1, "shared", "O."), ("two", 0, None, None)])
        ag_boot(apex)
        truthy((apex / ".claude" / "agents" / "shared-pj.md").exists(), "setup")

        # `one` drops out of the walk but keeps its claim.
        (apex / "one" / "CLAUDE.md").write_bytes(
            "---\nroot: true\nname: one\n---\n\ncafé\n".encode("utf-16"))
        ag_optin(apex, [("two", 1, "Shared", "T.")])
        rep = ag_boot(apex)

        ag = apex / ".claude" / "agents"
        names = sorted(p.name for p in ag.iterdir())
        truthy("shared-pj.md" in names, "the skipped project keeps its file: %s" % names)
        truthy("Shared-pj.md" not in names,
               "the newcomer does not get a case-variant of a live claim: %s" % names)


# ── mileqa round-1 fixes (2026-08-23) ────────────────────────────────

@test("MQ-01", "_walk_candidate_roots")
def _():
    """discover_roots TERMINATES when a root holds symlinks resolving to itself.

    is_dir() follows symlinks, so `l0 -> .`/`l1 -> .` re-enter the directory;
    ELOOP caps resolution depth, not branching, so two such links used to grow
    the walk until OOM. The ancestor-stack cut breaks the back-edge onto the
    current path while still appending the alias for downstream de-duplication.
    """
    cp = cboot._load_module(cboot.PREBOOT_DIR / "child_propagate.py")
    with scratch_apex([("A", "a\n")]) as apex:
        try:
            os.symlink(apex / "A", apex / "A" / "l0")
            os.symlink(apex / "A", apex / "A" / "l1")
        except (OSError, NotImplementedError):
            return
        roots = cp.discover_roots(apex)   # must return, not hang/OOM
        truthy(1 <= len(roots) <= 4, "the walk is bounded: %d roots" % len(roots))
        truthy(any(r.name == "A" for r in roots), "the real root A is present")


@test("MQ-02", "_root_is_gone")
def _():
    """A live project with ordinary YAML frontmatter is never read as removed.

    The deletion oracle _has_root_true used a naive `find('---')` plus exact
    string equality; a `---` inside a value, a capitalised True, or a trailing
    comment made a present project look gone and unlinked its agent file.
    """
    with scratch_apex([("p", "P.\n")]) as apex:
        cm = apex / "p" / "CLAUDE.md"
        for fm in (
            "---\ndescription: cost --- benefit\nroot: true\nname: p\n---\n",
            "---\nroot: True\nname: p\n---\n",
            "---\nroot: true  # addressable\nname: p\n---\n",
        ):
            cm.write_text(fm)
            gone, why = cboot._root_is_gone("p")
            truthy(not gone, "%r must NOT read as gone (why=%r)" % (fm, why))


@test("MQ-03", "generate_agents")
def _():
    """The close path refuses to unlink a claim file outside the agents dir.

    A hand-edited/restored row whose agent_file carries `..` used to be unlinked:
    owns() is self-consistent by construction (its key comes from that same
    string) and the delete path had no containment belt.
    """
    with scratch_apex([]) as apex:
        victim = apex / "VICTIM_OUTSIDE.md"
        victim.write_text(GEN_BODY % "ghost")   # carries a cboot marker for 'ghost'
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        cboot._ensure_agent_tables(conn)
        rid = _rid_for(conn, "ghost")
        conn.execute(
            "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
            " description, agent_file, valid_from, change_reason, root_id)"
            " VALUES ('ghost','ghost','ghost','d',"
            "'.claude/agents/../../VICTIM_OUTSIDE.md','2026-01-01T00:00:00Z','opted-in',?)",
            (rid,))
        conn.commit()
        conn.close()
        rep = cboot.BootReport()
        rows = cboot.build_root_inventory(rep)
        cboot.generate_agents(rep, rows)       # 'ghost' absent from walk -> close path
        truthy(victim.exists(),
               "a claim file resolving outside .claude/agents/ is not unlinked")


@test("MQ-04", "_write_agent_file")
def _():
    """The write belt refuses a target outside the agents directory (kills M11)."""
    with scratch_apex([]) as apex:
        escaped = cboot.AGENTS_DIR / ".." / ".." / "ESCAPED.md"
        rep = cboot.BootReport()
        ok = cboot._write_agent_file(escaped, "x", rep, owned=False)
        truthy(not ok, "an escaping write is refused")
        truthy(not (apex / "ESCAPED.md").exists(), "no file is written outside the agents dir")


@test("MQ-05", "_write_agent_file")
def _():
    """A failed new-claim write leaves no orphan (AT2).

    open('x') creates the dirent; if the write then fails (ENOSPC/EIO) the
    truncated file used to be left behind — unclaimed, so purge mislabels it
    'hand-authored' forever and it blocks its own stem, bumping the real project.
    """
    import builtins
    with scratch_apex([]) as apex:
        target = cboot.AGENTS_DIR / "orphan-pj.md"
        real_open = builtins.open

        def flaky(path, mode="r", *a, **k):
            if "x" in mode:
                real_open(path, "w").close()                  # create the dirent...
                raise OSError(28, "No space left on device")  # ...then fail the write
            return real_open(path, mode, *a, **k)

        cboot.open = flaky
        try:
            rep = cboot.BootReport()
            ok = cboot._write_agent_file(target, "content", rep, owned=False)
        finally:
            del cboot.open
        truthy(not ok, "the write reports failure")
        truthy(not target.exists(), "the truncated orphan was removed")


@test("MQ-06", "generate_agents")
def _():
    """A folder that transliterates to an empty base is skipped, never `agent-2`.

    deconflict's 'agent' fallback would escape the -pj namespace; the guard now
    skips such a root before it can reach that fallback.
    """
    with scratch_apex([("日本語", "J.\n")]) as apex:
        ag_optin(apex, [("日本語", 1, None, "J.")])
        ag_boot(apex)
        names = sorted(p.name for p in (apex / ".claude" / "agents").iterdir())
        truthy("agent-2.md" not in names, "no bare agent-2 file: %s" % names)
        truthy(names == [], "nothing materialized for an unaddressable folder: %s" % names)


@test("MQ-07", "owns")
def _():
    """owns() matches a case-variant dirent — the agents mount is case-insensitive."""
    ao = cboot._agent_ownership()
    claims = {ao._key(cboot.AGENTS_DIR / "zMisc-pj.md"): {"agent_name": "z", "rel_path": "zMisc"}}
    truthy(ao.owns(cboot.AGENTS_DIR / "zmisc-pj.md", claims),
           "a lowercase dirent is owned by the mixed-case claim")
    truthy(ao.owns(cboot.AGENTS_DIR / "ZMISC-PJ.MD", claims), "an uppercase dirent too")


@test("MQ-08", "generate_agents")
def _():
    """De-confliction sees a hand-authored agent in a subdirectory (AT4).

    Claude Code discovers .claude/agents/** recursively; a top-level-only glob let
    cboot generate a duplicate @name that silently shadowed the human's file.
    """
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        sub = apex / ".claude" / "agents" / "mine"
        sub.mkdir(parents=True)
        (sub / "drawio-pj.md").write_text("---\nname: drawio-pj\n---\nhand\n")
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        truthy((sub / "drawio-pj.md").read_text().endswith("hand\n"),
               "the hand-authored nested file is untouched")
        truthy(not (ag / "drawio-pj.md").exists(),
               "cboot did not generate a top-level duplicate of the nested @name")
        truthy((ag / "drawio-pj-2.md").exists(), "it de-conflicted to a fresh name instead")


@test("MQ-09", "build_root_inventory")
def _():
    """A duplicate current row must not destroy the roots/meta cache (R3).

    DROP TABLE autocommits; the durable-table CREATE UNIQUE INDEX then raising on
    a legacy/restored/hand-edited duplicate used to leave roots/meta permanently
    gone, self-perpetuating every boot.
    """
    with scratch_apex([("a", "A.\n")]) as apex:
        db = apex / ".state" / "roots.db"
        conn = _sqlite_factory().connect(str(db))
        cboot._ensure_agent_tables(conn)
        conn.execute("DROP INDEX IF EXISTS idx_agent_cur_path")
        conn.execute("DROP INDEX IF EXISTS idx_agent_cur_name")
        # These two current rows are a "legacy/restored/hand-edited duplicate" — the
        # exact case where root_id is legitimately ABSENT (such rows predate the
        # spine). Left NULL on purpose: a shared real root_id would trip the current
        # root_id unique index at insert, and claims_for's LEFT JOIN + COALESCE owns
        # a NULL-root_id row by its frozen rel_path regardless.
        for i in (1, 2):
            conn.execute(
                "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
                " description, agent_file, valid_from, change_reason)"
                " VALUES (?,?,?,'d',?,'2026-01-01T00:00:00Z','opted-in')",
                ("dup%d" % i, "a", "a", ".claude/agents/dup%d.md" % i))
        conn.commit()
        conn.close()

        rep = cboot.BootReport()
        rows = cboot.build_root_inventory(rep)
        conn = _sqlite_factory().connect(str(db))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        truthy("roots" in tables and "meta" in tables,
               "roots/meta survive a durable-table failure: %s" % sorted(tables))
        truthy(rows is not None, "the inventory still returns the rebuilt cache")


@test("MQ-10", "generate_agents")
def _():
    """The structural excluded-guard alone prevents deletion (kills M12).

    Even with _root_is_gone forced to report every project gone, a root the walk
    EXCLUDED must keep its agent — the excluded lookup is a guard independent of
    the positive gone-gate.
    """
    with scratch_apex([("alpha", "A.\n"), ("beta", "B.\n")]) as apex:
        ag_optin(apex, [("alpha", 1, "alpha", "A."), ("beta", 1, "beta", "B.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        eq(sorted(p.name for p in ag.iterdir()), ["alpha-pj.md", "beta-pj.md"], "setup")

        real_classify = cboot._classify_root
        real_gone = cboot._root_is_gone
        cboot._classify_root = lambda d, apex_abs: (
            d.relative_to(apex_abs).as_posix(), "excluded by a hostile policy")
        cboot._root_is_gone = lambda rel: (True, "")   # the positive gate would delete
        try:
            rep = cboot.BootReport()
            rows = cboot.build_root_inventory(rep)
            cboot.generate_agents(rep, rows)
        finally:
            cboot._classify_root = real_classify
            cboot._root_is_gone = real_gone
        eq(sorted(p.name for p in ag.iterdir()), ["alpha-pj.md", "beta-pj.md"],
           "excluded roots are not deleted even when the gone-gate says gone")


@test("MQ-11", "generate_agents")
def _():
    """A held claim whose stored @name escapes the agents dir is closed, not wedged.

    The held branch used to take agent_name raw; a `..`-bearing name re-failed the
    write belt every boot forever. It is now closed 'invalid-name' so the next
    boot reopens a sanitized claim, and no file is written outside the dir.
    """
    with scratch_apex([("a", "A.\n")]) as apex:
        ag_optin(apex, [("a", 1, "a", "A.")])
        db = apex / ".state" / "roots.db"
        conn = _sqlite_factory().connect(str(db))
        cboot._ensure_agent_tables(conn)
        rid = _rid_for(conn, "a")
        conn.execute(
            "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
            " description, agent_file, valid_from, change_reason, root_id)"
            " VALUES ('../../EVIL','a','a','d',"
            "'.claude/agents/../../EVIL.md','2026-01-01T00:00:00Z','opted-in',?)",
            (rid,))
        conn.commit()
        conn.close()

        rep = cboot.BootReport()
        rows = cboot.build_root_inventory(rep)
        cboot.generate_agents(rep, rows)

        conn = _sqlite_factory().connect(str(db))
        closed = conn.execute(
            "SELECT COUNT(*) FROM agent_registry"
            " WHERE rel_path='a' AND close_reason='invalid-name'").fetchone()[0]
        conn.close()
        truthy(not (apex / "EVIL.md").exists(), "no EVIL.md written outside the agents dir")
        truthy(closed == 1, "the corrupt held claim was closed invalid-name")


@test("MQ-12", "build_root_inventory")
def _():
    """A legacy pre-optin claim inherits its decision DURING migration, and the
    inherited backfill PERSISTS the inventory pass.

    The `'inherited'` INSERT lives inside the v1 ladder (LOW-1): it only ever
    mattered for legacy `agent: true` claims that predate the decision table, which
    is exactly the one-time population the ladder handles. This drives a genuine
    legacy (user_version=0) db with a CURRENT claim and NO agent_optin row through
    a boot, and asserts the claim inherits an enabled decision keyed on its minted
    root_id, committed (not discarded by close()).
    """
    with scratch_apex([("x", "X.\n")]) as apex:
        db = apex / ".state" / "roots.db"
        conn = sqlite3.connect(db)
        # Pre-spine (user_version stays 0) legacy shape: a claim, no optin row.
        conn.execute(
            "CREATE TABLE agent_registry ( id INTEGER PRIMARY KEY, agent_name TEXT"
            " NOT NULL, rel_path TEXT NOT NULL, source_folder TEXT NOT NULL,"
            " deconflicted_from TEXT, description TEXT, agent_file TEXT NOT NULL,"
            " valid_from TEXT NOT NULL, valid_to TEXT, change_reason TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE agent_optin ( rel_path TEXT PRIMARY KEY, enabled INTEGER"
            " NOT NULL, requested_name TEXT, description TEXT, decided_at TEXT NOT"
            " NULL, decided_by TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
            " description, agent_file, valid_from, change_reason)"
            " VALUES ('x-pj','x','x','X.','.claude/agents/x-pj.md',"
            "'2026-01-01T00:00:00Z','opted-in')")   # NO agent_optin row -> pre-optin
        conn.commit()
        truthy(conn.execute("PRAGMA user_version").fetchone()[0] == 0,
               "setup: a legacy (pre-spine) db")
        conn.close()

        rep = cboot.BootReport()
        cboot.build_root_inventory(rep)   # migrates 0->1, inheriting the pre-optin claim

        conn = _sqlite_factory().connect(str(db))
        rid = conn.execute("SELECT root_id FROM roots_register"
                           " WHERE rel_path='x' COLLATE NOCASE AND valid_to IS NULL"
                           ).fetchone()["root_id"]
        row = conn.execute("SELECT enabled, decided_by FROM agent_optin"
                           " WHERE root_id = ?", (rid,)).fetchone()
        truthy(row is not None, "the pre-optin claim inherited a decision during migration")
        truthy(row is not None and row["decided_by"] == "inherited", "and is marked inherited")
        truthy(row is not None and row["enabled"] == 1, "an inherited decision is enabled")

        # LOW-1 discriminator: the inherit lives in the ladder, so it runs ONCE and
        # never again. Delete the decision and boot a now-migrated (v1) db: it must
        # NOT be re-created (the old every-boot base INSERT would resurrect it).
        conn.execute("DELETE FROM agent_optin WHERE root_id = ?", (rid,))
        conn.commit()
        conn.close()
        cboot.build_root_inventory(cboot.BootReport())   # v1: ladder does not run
        conn = _sqlite_factory().connect(str(db))
        again = conn.execute("SELECT 1 FROM agent_optin WHERE root_id = ?",
                             (rid,)).fetchone()
        conn.close()
        truthy(again is None,
               "the inherit does not run post-migration (only the one-time ladder)")


# ── roots_register: the single identity/claim writer (RR) ────────────
#
# Every RR test builds a throwaway temp apex, opens the post-WP-A durable schema
# with the house factory, and drives the mutation module directly. Nothing here
# reads or writes the live /mnt/claudette .state/roots.db, and the transcript-
# store re-slug is exercised entirely under a temp HOME via relink's `home=`
# parameter — so a run can never touch the real store or the live registry.

_RR_PY = ROOT / ".codex" / "reactive" / "roots-register" / "roots_register.py"
_ROOTS_PY = ROOT / ".codex" / "explicit" / "roots" / "roots.py"


def _load_roots_register():
    spec = importlib.util.spec_from_file_location("roots_register_mod", _RR_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextlib.contextmanager
def rr_rig():
    """A disposable apex with the migrated (user_version=1) durable schema and an
    open house-factory connection. Yields (rr_module, conn, apex_path).

    _ensure_agent_tables creates and migrates the schema and mints the apex a
    root_id (root_id=1, rel_path='.'), exactly as a first real boot would, so the
    first mint() a test issues gets root_id=2.
    """
    tmp = Path(tempfile.mkdtemp(prefix="ctest-rr-")).resolve()
    try:
        (tmp / ".state").mkdir(parents=True)
        conn = _sqlite_factory().connect(str(tmp / ".state" / "roots.db"))
        cboot._ensure_agent_tables(conn)
        conn.commit()
        try:
            yield _load_roots_register(), conn, tmp
        finally:
            conn.close()
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


@test("RR-00", "next_root_id")
def _():
    """The allocator is monotonic MAX+1 over ALL rows and never reuses an id."""
    with rr_rig() as (rr, conn, apex):
        eq(rr.next_root_id(conn), 2, "next id after the apex bootstrap (root_id=1)")
        a, b = rr.mint(conn, "a"), rr.mint(conn, "b")
        eq((a, b), (2, 3), "successive mints get successive ids")
        # Retire root_id 3 entirely (version its only spine row out). A current-
        # only MAX would now hand 3 back; MAX over ALL rows must still give 4.
        conn.execute("UPDATE roots_register SET valid_to = '2026-01-01T00:00:00Z'"
                     " WHERE root_id = ? AND valid_to IS NULL", (b,))
        eq(rr.next_root_id(conn), 4, "a retired id is still counted — 3 is never reused")


@test("RR-01", "mint")
def _():
    """mint allocates an unused root_id and refuses a duplicate current rel_path."""
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "drawio")
        eq(rid, 2, "first mint after the apex gets root_id 2")
        row = conn.execute(
            "SELECT rel_path, is_apex, change_reason, valid_to FROM roots_register"
            " WHERE root_id = ?", (rid,)).fetchone()
        eq((row["rel_path"], row["is_apex"], row["change_reason"], row["valid_to"]),
           ("drawio", 0, "canonicalized", None), "a current canonicalized spine row")
        for dup in ("drawio", "DRAWIO"):
            raised = False
            try:
                rr.mint(conn, dup)
            except ValueError:
                raised = True
            truthy(raised,
                   "a current rel_path (%r, NOCASE) is a relink, not a mint" % dup)


@test("RR-02", "open_claim")
def _():
    """open_claim opens a current claim keyed on root_id and records the opt-in."""
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "drawio")
        rr.open_claim(conn, rid, "drawio-pj", "drawio",
                      ".claude/agents/drawio-pj.md")
        claim = conn.execute(
            "SELECT agent_name, rel_path, root_id, change_reason, valid_to"
            " FROM agent_registry WHERE root_id = ? AND valid_to IS NULL",
            (rid,)).fetchone()
        eq((claim["agent_name"], claim["rel_path"], claim["root_id"],
            claim["change_reason"], claim["valid_to"]),
           ("drawio-pj", "drawio", rid, "opted-in", None),
           "current claim freezes the spine rel_path as its claim-time location")
        optin = conn.execute(
            "SELECT enabled, requested_name, decided_by FROM agent_optin"
            " WHERE root_id = ?", (rid,)).fetchone()
        eq((optin["enabled"], optin["decided_by"]), (1, "prompt"),
           "the opt-in decision is recorded enabled")


@test("RR-03", "close_claim")
def _():
    """close_claim versions the claim (SCD2 history kept) and, on a user disable,
    flips the opt-in decision off — the opening change_reason is never rewritten."""
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "drawio")
        rr.open_claim(conn, rid, "drawio-pj", "drawio",
                      ".claude/agents/drawio-pj.md")
        rr.close_claim(conn, rid, "opted-out")
        rows = conn.execute(
            "SELECT valid_to, change_reason, close_reason FROM agent_registry"
            " WHERE root_id = ?", (rid,)).fetchall()
        eq(len(rows), 1, "the row is versioned in place, not deleted")
        eq((rows[0]["change_reason"], rows[0]["close_reason"]),
           ("opted-in", "opted-out"), "opening reason kept; close reason recorded")
        truthy(rows[0]["valid_to"] is not None, "the claim is closed")
        n_cur = conn.execute("SELECT COUNT(*) FROM agent_registry"
                             " WHERE root_id = ? AND valid_to IS NULL",
                             (rid,)).fetchone()[0]
        eq(n_cur, 0, "no current claim after close")
        eq(conn.execute("SELECT enabled FROM agent_optin WHERE root_id = ?",
                        (rid,)).fetchone()[0], 0,
           "a user disable also flips the durable opt-in decision off")
        # A non-disable close (the project vanished) leaves the decision standing.
        rid2 = rr.mint(conn, "other")
        rr.open_claim(conn, rid2, "other-pj", "other",
                      ".claude/agents/other-pj.md")
        rr.close_claim(conn, rid2, "root-removed")
        eq(conn.execute("SELECT enabled FROM agent_optin WHERE root_id = ?",
                        (rid2,)).fetchone()[0], 1,
           "root-removed is not a user disable — the decision is left standing")


@test("RR-04", "rename_claim")
def _():
    """rename_claim closes the current claim and reopens under the new name, same
    root_id, carrying the claim-time source folder forward."""
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "drawio")
        rr.open_claim(conn, rid, "drawio-pj", "drawio",
                      ".claude/agents/drawio-pj.md")
        rr.rename_claim(conn, rid, "draw2-pj", ".claude/agents/draw2-pj.md")
        cur = conn.execute(
            "SELECT agent_name, source_folder, change_reason, root_id"
            " FROM agent_registry WHERE root_id = ? AND valid_to IS NULL",
            (rid,)).fetchone()
        eq((cur["agent_name"], cur["source_folder"], cur["change_reason"],
            cur["root_id"]),
           ("draw2-pj", "drawio", "renamed", rid),
           "new current claim: renamed, same id, source folder carried forward")
        eq(conn.execute("SELECT COUNT(*) FROM agent_registry"
                        " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchone()[0],
           1, "exactly one current claim per identity")
        old = conn.execute(
            "SELECT close_reason FROM agent_registry WHERE root_id = ?"
            " AND valid_to IS NOT NULL ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
        eq(old["close_reason"], "renamed", "the prior claim closed 'renamed'")
        eq(conn.execute("SELECT requested_name FROM agent_optin WHERE root_id = ?",
                        (rid,)).fetchone()["requested_name"], "draw2-pj",
           "the opt-in requested_name follows the rename")


@test("RR-05", "relink")
def _():
    """relink keeps the same root_id, versions the spine, leaves the claim alive,
    AND renames the Claude Code transcript store old -> new."""
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "old/home")
        rr.open_claim(conn, rid, "home-pj", "home", ".claude/agents/home-pj.md")
        # A fake transcript store under a temp HOME, keyed on the OLD abs path.
        home = Path(tempfile.mkdtemp(prefix="ctest-rr-home-")).resolve()
        proj = home / ".claude" / "projects"
        proj.mkdir(parents=True)
        slug = rr._ts().project_slug
        old_store = proj / slug(apex / "old/home")
        new_store = proj / slug(apex / "new/home")
        old_store.mkdir()
        (old_store / "session.jsonl").write_text("transcript\n")
        try:
            rr.relink(conn, rid, "new/home", home=home)

            cur = conn.execute(
                "SELECT root_id, rel_path, change_reason FROM roots_register"
                " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchone()
            eq((cur["root_id"], cur["rel_path"], cur["change_reason"]),
               (rid, "new/home", "relinked"),
               "the current spine is the new path under the SAME root_id")
            eq(conn.execute("SELECT COUNT(*) FROM roots_register"
                            " WHERE root_id = ?", (rid,)).fetchone()[0], 2,
               "the old spine row is versioned, not overwritten")
            alive = conn.execute(
                "SELECT agent_name FROM agent_registry"
                " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchone()
            truthy(alive is not None and alive["agent_name"] == "home-pj",
                   "the agent claim survives the move untouched")

            truthy(not old_store.exists(), "the old transcript store is gone")
            truthy((new_store / "session.jsonl").read_text() == "transcript\n",
                   "the transcript store followed the move old -> new")
        finally:
            _shutil.rmtree(home, ignore_errors=True)


@test("RR-06", "deconflict")
def _():
    """deconflict: grandfathers win — the incumbent keeps its name and the
    newcomer takes -2; comparison is case-folded; reserved names are avoided."""
    with rr_rig() as (rr, conn, apex):
        R = rr.reserved_names()
        eq(rr.deconflict("drawio-pj", set(), R), "drawio-pj",
           "a free name is returned unchanged (the grandfather keeps it)")
        eq(rr.deconflict("drawio-pj", {"drawio-pj"}, R), "drawio-pj-2",
           "a newcomer colliding with an incumbent takes -2")
        eq(rr.deconflict("Foo-pj", {"foo-pj"}, R), "Foo-pj-2",
           "collision is case-folded (the mount is case-insensitive)")
        eq(rr.deconflict("drawio-pj", {"drawio-pj", "drawio-pj-2"}, R), "drawio-pj-3",
           "the suffix walks up until a free slot")
        truthy(rr.deconflict("claude", set(), R) != "claude",
               "a reserved name is never handed out")


@test("RR-07", "relink")
def _():
    """Mutation proof: a relink that MINTED a fresh id (the reverted fix) orphans
    the live claim — which is exactly what RR-05's same-root_id assertion catches.

    RR-05 asserts relink preserves root_id. This reverts that one write in place —
    the new spine row is opened under next_root_id(conn) instead of the SAME id —
    and shows the claim, still keyed on the original identity, no longer joins to
    any current spine. So RR-05's preservation check is discriminating, not
    incidental.
    """
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "old/home")
        rr.open_claim(conn, rid, "home-pj", "home", ".claude/agents/home-pj.md")
        stamp = "2026-01-01T00:00:00Z"
        # The MUTANT relink: close the old spine, reopen under a FRESH minted id.
        spine = rr._current_spine(conn, rid)
        conn.execute("UPDATE roots_register SET valid_to = ? WHERE id = ?",
                     (stamp, spine["id"]))
        conn.execute(
            "INSERT INTO roots_register (root_id, rel_path, is_apex, change_reason,"
            " valid_from, valid_to) VALUES (?, 'new/home', 0, 'relinked', ?, NULL)",
            (rr.next_root_id(conn), stamp))
        # The claim still points at the original identity, which now has no current
        # spine, so the ownership join goes empty.
        joined = conn.execute(
            "SELECT ar.agent_name FROM agent_registry ar"
            " JOIN roots_register rr ON rr.root_id = ar.root_id AND rr.valid_to IS NULL"
            " WHERE ar.valid_to IS NULL AND ar.root_id = ?", (rid,)).fetchone()
        truthy(joined is None,
               "minting a fresh id orphans the live claim — the failure RR-05's "
               "same-root_id assertion is built to catch")


@test("RR-08", "claims_for")
def _():
    """WP-B proof: a move is transparent to ownership, and a broken link never
    un-owns a file.

    claims_for's LEFT JOIN + COALESCE sources the CURRENT spine rel_path for each
    claim, so a relink is invisible to the ownership key (the agent_file, hence the
    key, is untouched by the move); and it falls back to the claim's own frozen
    rel_path when the identity has no current spine row, so a broken or absent link
    never drops the claim from ownership. Reverting either half of that SELECT
    fails this test.
    """
    ao = cboot._agent_ownership()
    with rr_rig() as (rr, conn, apex):
        agents = apex / ".claude" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        db = apex / ".state" / "roots.db"
        rid = rr.mint(conn, "old/home")
        rr.open_claim(conn, rid, "home-pj", "home", ".claude/agents/home-pj.md")
        conn.commit()
        key = ao._key(agents / "home-pj.md")

        # claims_for opens the db immutable&mode=ro (the true read-only open), which
        # ignores the WAL of this still-open writer. The AG tests dodge this by
        # CLOSING their write conn (checkpointing) before reading; here the rr_rig
        # conn stays open, so checkpoint the WAL into the main db before each read.
        def _readable():
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            return ao.claims_for(db, agents)

        claims = _readable()
        truthy(key in claims, "the claim is owned")
        eq(claims[key]["rel_path"], "old/home",
           "before the move, claims_for sources the current spine rel_path")

        # Move the root. relink versions the spine under the SAME root_id and leaves
        # the agent_registry claim (its agent_file) untouched.
        home = Path(tempfile.mkdtemp(prefix="ctest-rr08-home-")).resolve()
        try:
            rr.relink(conn, rid, "new/home", home=home)
            conn.commit()
        finally:
            _shutil.rmtree(home, ignore_errors=True)
        moved = _readable()
        truthy(key in moved,
               "the SAME ownership key survives the move (agent_file unchanged)")
        eq(moved[key]["rel_path"], "new/home",
           "claims_for now returns the NEW rel_path from the current spine")

        # LEFT JOIN fallback: version the spine out so the identity has NO current
        # row. The claim must still be owned — by its own frozen rel_path.
        conn.execute("UPDATE roots_register SET valid_to = '2026-01-01T00:00:00Z'"
                     " WHERE root_id = ? AND valid_to IS NULL", (rid,))
        conn.commit()
        orphan = _readable()
        truthy(key in orphan,
               "a claim whose spine row is absent is NOT dropped from ownership")
        eq(orphan[key]["rel_path"], "old/home",
           "it falls back to the claim's own frozen (claim-time) rel_path")


@test("RR-09", "decline")
def _():
    """decline records a DISABLED decision (agent_optin enabled=0) and opens NO
    claim — the disabled complement of open_claim — and upserts idempotently."""
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "declined")
        rr.decline(conn, rid, requested_name="nope", description="not addressable")
        optin = conn.execute(
            "SELECT rel_path, enabled, requested_name, description, decided_by"
            " FROM agent_optin WHERE root_id = ?", (rid,)).fetchone()
        eq((optin["enabled"], optin["rel_path"], optin["requested_name"],
            optin["decided_by"]),
           (0, "declined", "nope", "prompt"),
           "a disabled opt-in keyed on root_id, freezing the spine rel_path")
        eq(conn.execute("SELECT COUNT(*) FROM agent_registry WHERE root_id = ?",
                        (rid,)).fetchone()[0], 0,
           "decline opens no agent_registry claim")

        # A later decline updates the same decision row in place, never a second.
        rr.decline(conn, rid, description="still no")
        rows = conn.execute("SELECT enabled, description FROM agent_optin"
                            " WHERE root_id = ?", (rid,)).fetchall()
        eq(len(rows), 1, "exactly one decision row per root_id")
        eq((rows[0]["enabled"], rows[0]["description"]), (0, "still no"),
           "the decline decision is updated in place")


@test("RR-10", "accept")
def _():
    """accept records an ENABLED decision and opens NO claim — the enabled
    complement of decline (boot's first-touch YES, before the claim is opened)."""
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "keeper")
        rr.accept(conn, rid, requested_name="keep", description="addressable")
        optin = conn.execute(
            "SELECT rel_path, enabled, requested_name, description, decided_by"
            " FROM agent_optin WHERE root_id = ?", (rid,)).fetchone()
        eq((optin["enabled"], optin["rel_path"], optin["requested_name"],
            optin["decided_by"]),
           (1, "keeper", "keep", "prompt"),
           "an enabled opt-in keyed on root_id, freezing the spine rel_path")
        eq(conn.execute("SELECT COUNT(*) FROM agent_registry WHERE root_id = ?",
                        (rid,)).fetchone()[0], 0,
           "accept opens no agent_registry claim (the decision half only)")

        # A later accept updates the same decision row in place, never a second.
        rr.accept(conn, rid, requested_name="keep", description="still yes")
        rows = conn.execute("SELECT enabled, description FROM agent_optin"
                            " WHERE root_id = ?", (rid,)).fetchall()
        eq(len(rows), 1, "exactly one decision row per root_id")
        eq((rows[0]["enabled"], rows[0]["description"]), (1, "still yes"),
           "the accept decision is updated in place")


@test("RR-11", "relink")
def _():
    """A destination-store collision is REFUSED, not clobbered (MEDIUM-2).

    The user opened Claude in the new location before relinking, so a transcript
    store already sits at the destination slug. relink detects it BEFORE any DB
    write and raises a catchable ValueError: it does NOT crash, does NOT touch
    either store, and leaves the identity single-current at the OLD path (rolled
    back). Exercised with BOTH a populated destination (which os.rename would fail
    on) AND an empty one (which os.rename would silently CONSUME) — only the
    pre-existence check refuses the empty case, so this pins that check.
    """
    def _check(dest_files):
        with rr_rig() as (rr, conn, apex):
            rid = rr.mint(conn, "old/home")
            rr.open_claim(conn, rid, "home-pj", "home", ".claude/agents/home-pj.md")
            conn.commit()
            home = Path(tempfile.mkdtemp(prefix="ctest-rr11-home-")).resolve()
            try:
                proj = home / ".claude" / "projects"
                proj.mkdir(parents=True)
                slug = rr._ts().project_slug
                old_store = proj / slug(apex / "old/home")
                new_store = proj / slug(apex / "new/home")
                old_store.mkdir()
                (old_store / "old.jsonl").write_text("OLD transcript\n")
                new_store.mkdir()                          # destination already exists
                for name, body in dest_files:
                    (new_store / name).write_text(body)

                raised = None
                try:
                    rr.relink(conn, rid, "new/home", home=home)
                except ValueError as e:
                    raised = str(e)
                try:                                       # what close() would do
                    conn.rollback()
                except sqlite3.Error:
                    pass

                truthy(raised is not None,
                       "relink raised a catchable ValueError (dest_files=%r)" % (dest_files,))
                truthy(raised and str(new_store) in raised,
                       "the message names the colliding destination: %r" % (raised,))
                truthy((old_store / "old.jsonl").read_text() == "OLD transcript\n",
                       "the OLD store was not moved")
                eq(sorted(p.name for p in new_store.iterdir()),
                   sorted(n for n, _ in dest_files),
                   "the pre-existing destination store was NOT clobbered/merged/consumed")
                cur = conn.execute(
                    "SELECT rel_path FROM roots_register"
                    " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchall()
                eq([r["rel_path"] for r in cur], ["old/home"],
                   "the identity stays single-current at the OLD path (rolled back)")
            finally:
                _shutil.rmtree(home, ignore_errors=True)

    _check([("new.jsonl", "someone else's history\n")])    # populated destination
    _check([])                                             # empty destination stub


# ── /roots reconfigure command (WP-F) ────────────────────────────────

def _load_roots():
    spec = importlib.util.spec_from_file_location("roots_cmd", _ROOTS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _durable_snapshot(db_path):
    """A stable snapshot of the three durable tables — for 'mutated nothing'."""
    conn = _sqlite_factory().connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        snap = {}
        for t in ("roots_register", "agent_registry", "agent_optin"):
            snap[t] = [tuple(r) for r in conn.execute(
                "SELECT * FROM %s ORDER BY rowid" % t)]
        return snap
    finally:
        conn.close()


@test("RS-01", "compute_drift")
def _():
    """A walked root with no current spine row is reported UNLINKED.

    Two boots: the first day-one-mints the population it walks (user_version 0->1),
    the second walks a child ADDED after that mint — which therefore has no spine
    row, so build_root_inventory leaves its roots.canonical_id NULL.
    """
    roots = _load_roots()
    with scratch_apex([("kept", "A kept tool.\n")]) as apex:
        ag_boot(apex)                       # day-one mint: apex + kept get spine rows
        fresh = apex / "fresh"
        fresh.mkdir()
        (fresh / "CLAUDE.md").write_text("---\nroot: true\nname: fresh\n---\n\nNew.\n")
        ag_boot(apex)                       # 'fresh' walked, never minted -> unlinked
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        try:
            drift = roots.compute_drift(conn, apex)
        finally:
            conn.close()
        rels = {u["rel_path"] for u in drift.unlinked}
        truthy("fresh" in rels, "the after-mint child is UNLINKED (canonical_id NULL)")
        truthy("kept" not in rels, "a canonicalized child is not unlinked")
        truthy("." not in rels, "the apex (always minted) is not unlinked")


@test("RS-02", "compute_drift")
def _():
    """A CURRENT spine row whose rel_path is absent from the last walk is ORPHANED.

    After a boot populates `roots`, mint an identity for a rel_path with no walked
    directory (as an out-of-band `mv` would leave behind): its dir is gone from the
    walk, so /roots surfaces it as orphaned — the relink candidate.
    """
    roots = _load_roots()
    rr = _load_roots_register()
    with scratch_apex([("here", "Present.\n")]) as apex:
        ag_boot(apex)
        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        try:
            rr.mint(conn, "moved/away")     # a current spine row with no walked dir
            conn.commit()
            drift = roots.compute_drift(conn, apex)
        finally:
            conn.close()
        orel = {o["rel_path"] for o in drift.orphaned}
        truthy("moved/away" in orel, "an identity whose dir left the walk is ORPHANED")
        truthy("here" not in orel, "a still-walked identity is not orphaned")
        truthy("." not in orel, "the apex (walked) is not orphaned")


@test("RS-03", "compute_drift")
def _():
    """A current claim whose on-disk file lost our marker is reported DIVERGENCE —
    and a healthy claim is not. Report-only: the file is never touched here."""
    roots = _load_roots()
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)                       # projects .claude/agents/drawio-pj.md
        agent_file = apex / ".claude" / "agents" / "drawio-pj.md"
        truthy(agent_file.exists(), "the claim projected a file")

        conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
        try:
            clean = roots.compute_drift(conn, apex)
            truthy(not clean.divergence, "a marker-matching claim is not divergent")

            # A human edits the file, breaking the marker. Nothing in the DB changes.
            agent_file.write_text("---\nname: drawio-pj\n---\n\nhand-authored now\n")
            diverged = roots.compute_drift(conn, apex)
        finally:
            conn.close()
        files = {d["agent_file"] for d in diverged.divergence}
        truthy(".claude/agents/drawio-pj.md" in files,
               "a claim whose file lost our marker is DIVERGENCE")
        # Report-only: the file is left exactly as the human left it.
        eq(agent_file.read_text(), "---\nname: drawio-pj\n---\n\nhand-authored now\n",
           "divergence never rewrites or deletes the file")


@test("RS-04", "op_disable")
def _():
    """op_disable dispatches close_claim('opted-out'): the claim is versioned out,
    the durable opt-in decision flips off, and the un-claimed OWNED file is swept
    while a marker-mismatched (hand-edited) file would be preserved."""
    roots = _load_roots()
    with rr_rig() as (rr, conn, apex):
        (apex / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        rid = rr.mint(conn, "drawio")
        agent_rel = ".claude/agents/drawio-pj.md"
        rr.open_claim(conn, rid, "drawio-pj", "drawio", agent_rel)
        conn.commit()
        ao = cboot._agent_ownership()
        target = apex / agent_rel
        target.write_text("---\nname: drawio-pj\n---\n\n%s\n\nbody\n"
                          % ao.render_marker("drawio", "2026-01-01T00:00:00Z"))

        status = roots.op_disable(conn, rid, apex=apex)

        n_cur = conn.execute("SELECT COUNT(*) FROM agent_registry"
                             " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchone()[0]
        eq(n_cur, 0, "the current claim is closed")
        closed = conn.execute(
            "SELECT close_reason FROM agent_registry WHERE root_id = ?"
            " ORDER BY id DESC LIMIT 1", (rid,)).fetchone()["close_reason"]
        eq(closed, "opted-out", "closed with the human-disable reason")
        eq(conn.execute("SELECT enabled FROM agent_optin WHERE root_id = ?",
                        (rid,)).fetchone()["enabled"], 0, "opt-in decision flipped off")
        eq(status, "removed", "the owned agent file was swept")
        truthy(not target.exists(), "the swept file is gone")

    # A hand-edited (marker-mismatched) file is preserved, not deleted.
    with rr_rig() as (rr, conn, apex):
        (apex / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        rid = rr.mint(conn, "edited")
        agent_rel = ".claude/agents/edited-pj.md"
        rr.open_claim(conn, rid, "edited-pj", "edited", agent_rel)
        conn.commit()
        target = apex / agent_rel
        target.write_text("---\nname: edited-pj\n---\n\nhuman wrote this\n")
        status = roots.op_disable(conn, rid, apex=apex)
        eq(status, "preserved-hand-edited", "a hand-edited file is never deleted")
        truthy(target.exists(), "the preserved file survives")


@test("RS-05", "op_enable")
def _():
    """op_enable dispatches accept: the opt-in decision flips to enabled=1 and NO
    claim is opened (boot's projection pass opens it). Existing decision fields are
    preserved, not clobbered to NULL."""
    roots = _load_roots()
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "declined")
        rr.decline(conn, rid, requested_name="keepname", description="keepdesc")
        conn.commit()
        roots.op_enable(conn, rid)
        row = conn.execute(
            "SELECT enabled, requested_name, description FROM agent_optin"
            " WHERE root_id = ?", (rid,)).fetchone()
        eq(row["enabled"], 1, "the decision is now enabled")
        eq((row["requested_name"], row["description"]), ("keepname", "keepdesc"),
           "the prior requested_name/description are preserved, not NULLed")
        eq(conn.execute("SELECT COUNT(*) FROM agent_registry WHERE root_id = ?",
                        (rid,)).fetchone()[0], 0,
           "op_enable opens no claim — the file is boot's job")


@test("RS-06", "op_rename")
def _():
    """op_rename de-conflicts the new base and dispatches rename_claim: same
    root_id, new suffixed @name, old claim versioned 'renamed'. A collision against
    `taken` bumps the newcomer, grandfathers win."""
    roots = _load_roots()
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "drawio")
        rr.open_claim(conn, rid, "drawio-pj", "drawio", ".claude/agents/drawio-pj.md")
        conn.commit()
        name = roots.op_rename(conn, rid, "draw2", apex=apex)
        eq(name, "draw2-pj", "the new base is suffixed and returned")
        cur = conn.execute(
            "SELECT agent_name, change_reason, root_id FROM agent_registry"
            " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchone()
        eq((cur["agent_name"], cur["change_reason"], cur["root_id"]),
           ("draw2-pj", "renamed", rid), "renamed in place, same identity")
        eq(conn.execute("SELECT COUNT(*) FROM agent_registry"
                        " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchone()[0],
           1, "exactly one current claim after the rename")
        # De-confliction: renaming onto a name another live claim holds bumps to -2.
        bumped = roots.op_rename(conn, rid, "taken", taken={"taken-pj"}, apex=apex)
        eq(bumped, "taken-pj-2", "a colliding rename is de-conflicted (grandfather wins)")


@test("RS-07", "op_relink")
def _():
    """op_relink dispatches relink: the spine is versioned under the SAME root_id,
    the claim survives, and the transcript store follows old -> new (the re-slug)."""
    roots = _load_roots()
    with rr_rig() as (rr, conn, apex):
        rid = rr.mint(conn, "old/home")
        rr.open_claim(conn, rid, "home-pj", "home", ".claude/agents/home-pj.md")
        conn.commit()
        home = Path(tempfile.mkdtemp(prefix="ctest-rs07-home-")).resolve()
        try:
            proj = home / ".claude" / "projects"
            proj.mkdir(parents=True)
            slug = rr._ts().project_slug
            old_store = proj / slug(apex / "old/home")
            new_store = proj / slug(apex / "new/home")
            old_store.mkdir()
            (old_store / "s.jsonl").write_text("t\n")

            roots.op_relink(conn, rid, "new/home", home=home)

            cur = conn.execute(
                "SELECT rel_path, root_id, change_reason FROM roots_register"
                " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchone()
            eq((cur["rel_path"], cur["root_id"], cur["change_reason"]),
               ("new/home", rid, "relinked"), "current spine is the new path, same id")
            eq(conn.execute("SELECT COUNT(*) FROM roots_register WHERE root_id = ?",
                            (rid,)).fetchone()[0], 2, "old spine row versioned, not lost")
            truthy(conn.execute(
                "SELECT agent_name FROM agent_registry"
                " WHERE root_id = ? AND valid_to IS NULL", (rid,)).fetchone() is not None,
                "the claim survives the relink")
            truthy(not old_store.exists() and (new_store / "s.jsonl").exists(),
                   "the transcript store followed the move (re-slug)")
        finally:
            _shutil.rmtree(home, ignore_errors=True)


@test("RS-08", "op_canonicalize")
def _():
    """op_canonicalize dispatches mint: a fresh, never-reused root_id and a current
    'canonicalized' spine row; a second call on the same current rel_path is
    refused (that would be a relink, not a mint)."""
    roots = _load_roots()
    with rr_rig() as (rr, conn, apex):
        rid = roots.op_canonicalize(conn, "brandnew")
        row = conn.execute(
            "SELECT rel_path, change_reason, valid_to, is_apex FROM roots_register"
            " WHERE root_id = ?", (rid,)).fetchone()
        eq((row["rel_path"], row["change_reason"], row["valid_to"], row["is_apex"]),
           ("brandnew", "canonicalized", None, 0), "a fresh current canonicalized spine")
        truthy(rid >= 2, "the minted id is past the apex bootstrap")
        raised = False
        try:
            roots.op_canonicalize(conn, "brandnew")
        except ValueError:
            raised = True
        truthy(raised, "a duplicate current rel_path is a relink, not a mint")


@test("RS-09", "roots_run")
def _():
    """A NON-TTY invocation prints the drift report and mutates nothing.

    run() sees no terminal (the harness process's stdin/stdout are not TTYs), so it
    takes the report-only path: the three durable tables are byte-identical before
    and after, and the drift shows up in stdout.
    """
    roots = _load_roots()
    rr = _load_roots_register()
    with scratch_apex([("here", "Present.\n")]) as apex:
        ag_boot(apex)
        db = apex / ".state" / "roots.db"
        conn = _sqlite_factory().connect(str(db))
        try:
            rr.mint(conn, "moved/away")     # craft an orphan to prove the report runs
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        finally:
            conn.close()

        before = _durable_snapshot(db)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = roots.run(["--project-root", str(apex)])
        after = _durable_snapshot(db)

        eq(rc, 0, "non-TTY run exits 0")
        eq(after, before, "non-TTY run mutates none of the durable tables")
        out = buf.getvalue()
        truthy("ORPHANED" in out and "moved/away" in out,
               "the drift report is printed")
        truthy("report only" in out.lower(),
               "the non-interactive path announces itself")


# ── runner + coverage ────────────────────────────────────────────────

def main():
    passed = failed = 0
    for test_id, target, fn in TESTS:
        try:
            fn()
            passed += 1
        except Exception as e:  # noqa: BLE001 — report any failure
            failed += 1
            print(f"  [FAIL] {test_id} ({target}): {e}")
    # bidirectional coverage
    uncovered = COVERED - _TARGETS_SEEN
    stray = _TARGETS_SEEN - COVERED
    cov_ok = not uncovered and not stray
    if uncovered:
        print(f"  [FAIL] coverage: no test for {sorted(uncovered)}")
    if stray:
        print(f"  [FAIL] coverage: test targets not in COVERED: {sorted(stray)}")

    print(f"\n  {passed}/{passed+failed} tests passed; "
          f"coverage {'OK' if cov_ok else 'INCOMPLETE'} "
          f"({len(_TARGETS_SEEN)}/{len(COVERED)} functions)")
    sys.exit(0 if failed == 0 and cov_ok else 1)


if __name__ == "__main__":
    main()
