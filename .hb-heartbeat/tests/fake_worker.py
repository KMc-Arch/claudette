#!/usr/bin/env python3
"""Fake worker for Heartbeat tests. Stands in for `cboot.py --project SANDBOX --exec-file PROMPT`.

argv: SANDBOX PROMPT_FILE. Behaviour via HB_FAKE_MODE:
  converged  (default) commit a file on the branch, write RESULT/{outcome,context,state}.md, print ok envelope
  exhausted  same but terminus: exhausted / qa_result: exhausted
  none       do work, write NO RESULT, print ok envelope           -> runner classifies "unexpected"
  quota      print error envelope mentioning a rate limit           -> runner classifies "quota"
  sleep      sleep past the cap (caller sets CBOOT_EXEC_TIMEOUT)     -> "cap"
  crash      exit 3 with garbage on stdout
Prints a cboot-style JSON envelope on stdout.
"""
import json, os, subprocess, sys, time
from pathlib import Path

sandbox = Path(sys.argv[1]); prompt_file = Path(sys.argv[2])
mode = os.environ.get("HB_FAKE_MODE", "converged")
prompt = prompt_file.read_text(encoding="utf-8")
assert "## The item" in prompt and "{{" not in prompt, "prompt not fully rendered"
result_dir = sandbox / ".hb-heartbeat" / "state" / "RESULT"

def envelope(**kw):
    base = {"kind": "result", "mode": "hard", "session_id": "fake-session-0001", "result": "done",
            "is_error": False, "cost_usd": 0.01, "duration_ms": 1234, "num_turns": 3}
    base.update(kw); print(json.dumps(base));

if mode == "quota":
    print(json.dumps({"kind": "result", "mode": "hard", "session_id": "fake-session-0002",
                      "result": "You've hit your usage limit (rate limit) — resets at 5am", "is_error": True}))
    sys.exit(1)
if mode == "crash":
    print("not json at all"); sys.exit(3)
if mode == "sleep":
    cap = int(os.environ.get("CBOOT_EXEC_TIMEOUT", "5"))
    time.sleep(cap + 2)
    print(json.dumps({"kind": "error", "mode": "hard", "is_error": True, "error": f"headless claude timed out after {cap}s"}))
    sys.exit(1)

if mode == "envdump":
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "outcome.md").write_text(f"---\nitem_id: {os.environ.get('HB_ITEM_ID')}\nterminus: converged\nqa_result: n/a\nsummary: env dump\n---\nenv dumped.\n", encoding="utf-8")
    keep = {k: v for k, v in os.environ.items() if k.startswith(("GIT_", "GH_", "HB_", "CBOOT_", "XDG_", "GITHUB"))}
    (result_dir / "context.md").write_text(json.dumps(keep), encoding="utf-8")
    envelope(); sys.exit(0)

if mode == "nocommit":
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "outcome.md").write_text(f"---\nitem_id: {os.environ.get('HB_ITEM_ID')}\nterminus: converged\nqa_result: n/a\nsummary: nothing to do\n---\nNothing needed.\n", encoding="utf-8")
    envelope(); sys.exit(0)

# do some work on the branch
(sandbox / "HB_FAKE_WORK.md").write_text(f"fake work for {os.environ.get('HB_ITEM_ID')} at {time.time_ns()}\n", encoding="utf-8")
subprocess.run(["git", "-C", str(sandbox), "add", "-f", "HB_FAKE_WORK.md"], check=True, capture_output=True)
subprocess.run(["git", "-C", str(sandbox), "-c", "user.name=fake", "-c", "user.email=fake@x", "commit", "-qm", "fake worker commit"], check=True, capture_output=True)

# emulate a worker filing a backlog item in its (discarded) sandbox state
bl = sandbox / ".state" / "work" / "backlog.md"
if bl.exists():
    bl.write_text(bl.read_text() + "\n### BL-FAKE filed by fake worker\n", encoding="utf-8")

if mode == "none":
    envelope(); sys.exit(0)

term = "exhausted" if mode == "exhausted" else "converged"
result_dir.mkdir(parents=True, exist_ok=True)
(result_dir / "outcome.md").write_text(f"---\nitem_id: {os.environ.get('HB_ITEM_ID')}\nterminus: {term}\nqa_result: {term}\npr: null\nsummary: fake\n---\nFake worker did fake work.\n", encoding="utf-8")
(result_dir / "context.md").write_text("fake context\n", encoding="utf-8")
(result_dir / "state.md").write_text("fake state\n", encoding="utf-8")
envelope()
