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
    "claims_for",
    "owns",
    "derive_agent_name",
    "render_marker",
    "_purge_agents_dir",
    "_ensure_agent_tables",
    "marker_matches",
    "_root_is_gone",
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
    eq(cols, {"id", "name", "abs_path", "rel_path", "parent_path", "depth",
              "is_apex", "contains_roots", "agent_enabled", "agent_name",
              "agent_file", "generated_at"}, "roots schema")
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


def ag_optin(apex, rows):
    """Record opt-in decisions the way the interactive prompt would."""
    conn = _sqlite_factory().connect(str(apex / ".state" / "roots.db"))
    cboot._ensure_agent_tables(conn)
    for rel, enabled, name, desc in rows:
        conn.execute(
            "INSERT OR REPLACE INTO agent_optin VALUES (?,?,?,?,"
            "'2026-01-01T00:00:00Z','prompt')", (rel, enabled, name, desc))
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
        truthy((ag / "drawio.md").exists(), "switched-on root has an agent file")
        truthy(not (ag / "zMisc.md").exists(), "declined root has no agent file")


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
        forged = apex / ".claude" / "agents" / "drawio.md"
        forged.write_text('---\nname: drawio\n---\n\n'
                          '<!-- cboot:agent root="drawio" generated="2026-01-01T00:00:00Z" -->\n'
                          'hand-written body\n')
        keep = forged.read_bytes()
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        eq(forged.read_bytes(), keep, "the forged file is not adopted or overwritten")
        truthy((apex / ".claude" / "agents" / "drawio-2.md").exists(),
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
        f = apex / ".claude" / "agents" / "drawio.md"
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
        f = apex / ".claude" / "agents" / "drawio.md"
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
        f = apex / ".claude" / "agents" / "drawio.md"
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
        f = apex / ".claude" / "agents" / "drawio.md"
        _shutil.rmtree(apex / "drawio")
        ag_boot(apex)
        truthy(not f.exists(), "file removed when the root is gone")


@test("AG-09", "generate_agents")
def _():
    """A foreign file holding the name forces de-confliction; it is not evicted."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        (apex / ".claude" / "agents" / "drawio.md").write_text(
            "---\nname: drawio\n---\n\nmine, hand-authored\n")
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        truthy("mine, hand-authored" in (ag / "drawio.md").read_text(),
               "pre-existing file always wins")
        truthy((ag / "drawio-2.md").exists(),
               "newcomer de-conflicted: %s" % sorted(p.name for p in ag.iterdir()))


@test("AG-10", "generate_agents")
def _():
    """YAML-hostile names are emitted quoted, so they read back as strings."""
    with scratch_apex([("2025", "A year.\n"), ("null", "Nothing.\n")]) as apex:
        ag_optin(apex, [("2025", 1, "2025", "A year."), ("null", 1, "null", "Nothing.")])
        ag_boot(apex)
        ag = apex / ".claude" / "agents"
        truthy('name: "2025"' in (ag / "2025.md").read_text(), "numeric name quoted")
        truthy('name: "null"' in (ag / "null.md").read_text(), "null name quoted")


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
                conn.execute(
                    "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
                    " description, agent_file, valid_from, change_reason)"
                    " VALUES (?,?,?,'d',?,'2026-01-01T00:00:00Z','opted-in')",
                    (n, n, n, ".claude/agents/%s.md" % n))
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
    """Revert ownership to a content heuristic and AG-03's file IS overwritten.

    A real mutant, not a simulation: owns() is replaced in a loaded copy of the
    module by the rule the design removed — "carries a marker, therefore ours".
    If AG-03 still passed under that, AG-03 would be proving nothing.
    """
    ao = cboot._agent_ownership()
    real_owns = ao.owns

    def content_owns(path, claims):
        return ao.read_marker(path) is not None

    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        forged = apex / ".claude" / "agents" / "drawio.md"
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
        truthy("hand-written body" not in forged.read_text(),
               "the mutation must destroy the file — otherwise AG-03 proves nothing")


@test("MU-02", "generate_agents")
def _():
    """Treat an undecodable CLAUDE.md as readable -> AG-07's file is deleted."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "A tool.")])
        ag_boot(apex)
        f = apex / ".claude" / "agents" / "drawio.md"
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
        eq(sorted(p.name for p in ag.iterdir()), ["alpha.md", "beta.md"], "setup")
        rep = cboot.BootReport()
        cboot.generate_agents(rep, [])            # what `return []` used to feed
        eq(sorted(p.name for p in ag.iterdir()), ["alpha.md", "beta.md"],
           "both agents survive an empty inventory")
        truthy(any("still present" in w for w in rep.warnings),
               "and the skip is reported: %r" % (rep.warnings,))


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
        truthy((apex / ".claude" / "agents" / "alpha.md").exists(), "agent still generated")


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
        f = ag / "tools.md"
        truthy(f.exists(), "setup: tools.md claimed by old-home")

        f.write_text("---\nname: tools\n---\n\n%s\n" % HUMAN)   # a human edits it
        _shutil.rmtree(apex / "old-home")                        # its project goes away
        ag_optin(apex, [("new-home", 1, "tools", "New tools.")])  # newcomer wants the name
        ag_boot(apex)

        truthy(f.exists() and HUMAN in f.read_text(), "the human's edit survives")
        truthy((ag / "tools-2.md").exists(),
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
            "SELECT valid_to, close_reason FROM agent_registry").fetchone()
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
            truthy((apex / ".claude" / "agents" / "outsider.md").exists(),
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
        eq(sorted(p.name for p in ag.iterdir()), ["aa.md", "bb.md"], "setup")

        (apex / "grp" / "CLAUDE.md").write_bytes(
            "---\nroot: true\nname: grp\n---\n\ncafé\n".encode("utf-16"))
        rep = ag_boot(apex)
        eq(sorted(p.name for p in ag.iterdir()), ["aa.md", "bb.md"],
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
        truthy((ag / "shared.md").exists(),
               "the live project gets the name the dead one was holding: %s"
               % sorted(p.name for p in ag.iterdir()))


@test("AG-27", "generate_agents")
def _():
    """A description containing the marker placeholder text cannot break the file."""
    with scratch_apex([("drawio", "A tool.\n")]) as apex:
        ag_optin(apex, [("drawio", 1, "drawio", "Handles @@MARKER@@ tokens in text.")])
        ag_boot(apex)
        text = (apex / ".claude" / "agents" / "drawio.md").read_text()
        truthy('description: "Handles @@MARKER@@ tokens in text."' in text,
               "the description survives verbatim")
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
        f = apex / ".claude" / "agents" / "delivery.md"
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
