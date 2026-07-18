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
    p, err = cboot._resolve_target("majel")
    eq(err, None, "valid child resolves"); truthy(p and p.name == "majel")

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
    code, j, _ = run_exec("majel", "   ", [])   # empty prompt, valid target
    eq(code, 1); eq(j["error"], "empty prompt")
    truthy(j["root"] and j["root"]["name"] == "Majel", "empty-prompt error carries the resolved root")

@test("EX-05", "exec_in_project")
def _():
    with claude_stub():
        code, j, _ = run_exec("majel", "hello", [])
    eq(code, 0); truthy(j is not None, "stdout is a single parseable JSON object")
    eq(j["kind"], "result")

@test("EX-06", "exec_in_project")
def _():
    with claude_stub():
        _, j, _ = run_exec("majel", "hello", [])
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
            run_exec("majel", "hello", [])
            data = rec.read_text()
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
    child = str((ROOT / "majel"))
    truthy(f"CWD: {child}" in data, f"cwd not fenced at child:\n{data}")
    truthy(f"CPD: {child}" in data, f"CLAUDE_PROJECT_DIR not overridden to child:\n{data}")

@test("EX-08", "exec_in_project")
def _():
    with claude_stub() as rec:
        _, _, err = run_exec("majel", "hello", ["--resume", "r1", "--dangerously-skip-permissions"])
        argv = rec.read_text()
    truthy("--resume r1" in argv, f"allowlisted passthrough not forwarded:\n{argv}")
    truthy("--dangerously-skip-permissions" not in argv, "governance flag reached claude")
    truthy("dropped disallowed passthrough" in err, "drop not reported on stderr")

@test("EX-09", "exec_in_project")
def _():
    # is_error:true on a parseable (kind:"result") envelope — message in `result`,
    # NO top-level `error` key, exit 1.
    with claude_stub('{"is_error":true,"result":"boom","session_id":"s9"}'):
        code, j, _ = run_exec("majel", "hello", [])
    eq(code, 1); eq(j["kind"], "result"); eq(j["is_error"], True)
    eq(j["result"], "boom"); truthy("error" not in j, "kind:result must not carry an `error` key")

@test("EX-10", "exec_in_project")
def _():
    with claude_stub("this is not json") as rec:
        code, j, _ = run_exec("majel", "hello", [])
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
            code, j, _ = run_exec("majel", None, [], prompt_file=str(d / "req.txt"))
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
        code = cboot.switch_command("majel")
    line = out.getvalue().strip()
    eq(code, 0)
    eq(line, f'python cboot.py --project "{(ROOT/"majel").as_posix()}" --launch')

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
              "is_apex", "contains_roots", "generated_at"}, "roots schema")
    apex = list(conn.execute("SELECT rel_path,depth,parent_path FROM roots WHERE is_apex=1"))
    eq(len(apex), 1, "exactly one apex row")
    eq(tuple(apex[0]), (".", 0, None), "apex row shape")
    conn.close()


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
