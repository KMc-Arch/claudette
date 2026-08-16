#!/usr/bin/env python3
"""Heartbeat control-plane tests. Zero model calls, zero quota.

Run:  python3 .hb-heartbeat/tests/test_hb.py [-v]
Each test builds a scratch apex (git repo + CLAUDE.md root:true + copied .hb-heartbeat) under
$CLAUDE_JOB_DIR/tmp or the system tmp, points HB_HOME at it, and drives hb.py / runner.py directly.
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent                      # the real .hb-heartbeat
sys.path.insert(0, str(SRC))
FAKE = f"{sys.executable} {HERE / 'fake_worker.py'}"
TMP_BASE = Path(os.environ.get("CLAUDE_JOB_DIR", tempfile.gettempdir())) / "tmp" if os.environ.get("CLAUDE_JOB_DIR") else Path(tempfile.gettempdir())

BACKLOG = """# Backlog

### BL-07 `00-preboot` tier missing from Loading Rules table

**Severity:** low
**Status:** open

Add a `00-preboot` row.

### BL-08 Something else

body 8
"""


def sh(*args, cwd=None, check=True, env=None):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=check, env=env)


class Scratch:
    def __init__(self):
        TMP_BASE.mkdir(parents=True, exist_ok=True)
        self.apex = Path(tempfile.mkdtemp(prefix="hbtest-", dir=str(TMP_BASE)))
        (self.apex / "CLAUDE.md").write_text("---\nroot: true\n---\n# scratch\n", encoding="utf-8")
        (self.apex / ".gitignore").write_text("*\n!/.gitignore\n!/CLAUDE.md\n!/README.md\n", encoding="utf-8")
        (self.apex / "README.md").write_text("scratch\n", encoding="utf-8")
        (self.apex / ".state" / "work").mkdir(parents=True)
        (self.apex / ".state" / "memory").mkdir(parents=True)
        (self.apex / ".state" / "work" / "backlog.md").write_text(BACKLOG, encoding="utf-8")
        (self.apex / ".state" / "prefs.json").write_text("{}", encoding="utf-8")
        hbdir = self.apex / ".hb-heartbeat"
        shutil.copytree(SRC, hbdir, ignore=shutil.ignore_patterns("state", "sandbox", "tests", "__pycache__", "*.bak"))
        (hbdir / "state").mkdir()
        sh("git", "init", "-q", "-b", "main", cwd=self.apex)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=self.apex)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=self.apex)
        self.hb = hbdir
        os.environ["HB_HOME"] = str(hbdir)
        os.environ["HB_WORKER_CMD"] = FAKE
        os.environ.pop("HB_FAKE_MODE", None)
        global hb, runner
        import hb as _hb, runner as _runner
        hb = importlib.reload(_hb)
        runner = importlib.reload(_runner)
        self.cfg = hb.load_config()

    def approve(self, item_id="BL-07", **kw):
        return hb.approve(item_id, None, kw.get("priority"), None, None, self.cfg)

    def cleanup(self):
        try:
            sh("git", "worktree", "prune", cwd=self.apex, check=False)
            shutil.rmtree(self.apex, ignore_errors=True)
        except Exception:
            pass


class Base(unittest.TestCase):
    def setUp(self):
        self.s = Scratch()
        self.cfg = self.s.cfg
        self.apex = self.s.apex

    def tearDown(self):
        self.s.cleanup()

    def flag(self):
        return hb.read_flag()

    def issue(self, minutes=300):
        return hb.issue_flag(hb.now_utc() + timedelta(minutes=minutes))


# ── flag state machine ───────────────────────────────────────────────

class TestFlag(Base):
    def test_absent_claim_none(self):
        self.assertIsNone(hb.claim_flag(111))
        self.assertIsNone(self.flag())

    def test_issue_claim_annotate_release(self):
        self.issue()
        self.assertEqual(self.flag()["status"], "go")
        c = hb.claim_flag(222)
        self.assertEqual(c["status"], "inflight"); self.assertEqual(c["pid"], 222)
        self.assertIsNone(self.flag()["transcript_path"])            # blank preserved as diagnostic
        self.assertTrue(hb.annotate_flag(222, item_id="X", transcript_path="/t.jsonl"))
        self.assertEqual(self.flag()["item_id"], "X")
        self.assertFalse(hb.annotate_flag(999, item_id="Y"))         # wrong pid refused
        self.assertEqual(self.flag()["item_id"], "X")
        self.assertIsNone(hb.claim_flag(333))                        # inflight not claimable
        self.assertFalse(hb.release_flag(999, "go"))                 # wrong pid
        self.assertTrue(hb.release_flag(222, "go"))
        f = self.flag(); self.assertEqual(f["status"], "go"); self.assertNotIn("pid", f)
        self.assertIn("window_closes_at", f)

    def test_release_absent_and_kill_switch(self):
        self.issue(); hb.claim_flag(5)
        self.assertTrue(hb.release_flag(5, "absent")); self.assertIsNone(self.flag())
        self.issue(); hb.claim_flag(6)
        hb.GO.unlink()                                               # human kill switch mid-run
        self.assertFalse(hb.release_flag(6, "go"))                   # never recreates from absent
        self.assertIsNone(self.flag())

    def test_claim_race_exactly_one_winner(self):
        self.issue()
        wins = []
        def go(pid):
            r = hb.claim_flag(pid)
            if r: wins.append(pid)
        ts = [threading.Thread(target=go, args=(1000 + i,)) for i in range(12)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(wins), 1, wins)
        self.assertEqual(self.flag()["pid"], wins[0])

    def test_issue_over_stale_logs_and_overwrites(self):
        self.issue(); hb.claim_flag(7)
        self.issue()
        self.assertEqual(self.flag()["status"], "go")
        self.assertIn("ERROR GO present at window open", hb.LOG.read_text())


# ── items / queue ────────────────────────────────────────────────────

class TestItems(Base):
    def test_approve_from_backlog_and_parse(self):
        p = self.s.approve()
        self.assertEqual(p, hb.outbox(self.apex) / "BL-07.md")
        fm, body, errs = hb.parse_item(p)
        self.assertEqual(errs, [], errs)
        self.assertEqual(fm["id"], "BL-07"); self.assertEqual(fm["recipient"], "hb")
        self.assertIn("00-preboot", body); self.assertNotIn("BL-08", body)
        with self.assertRaises(SystemExit):
            self.s.approve()                                         # duplicate refused
        with self.assertRaises(SystemExit):
            self.s.approve("BL-99")                                  # not in backlog

    def test_invalid_items_detected(self):
        box = hb.outbox(self.apex); box.mkdir(parents=True)
        (box / "X.md").write_text("no frontmatter\n")
        (box / "Y.md").write_text("---\nid: Z\nrecipient: hb\n---\nbody\n")
        valid, invalid = hb.list_candidates()
        self.assertEqual(valid, [])
        errs = {c["path"].name: c["errors"] for c in invalid}
        self.assertIn("no frontmatter", errs["X.md"])
        self.assertTrue(any("filename" in e for e in errs["Y.md"]))
        self.assertTrue(any("missing priority" in e for e in errs["Y.md"]))

    def test_pop_order_priority_then_age(self):
        self.s.approve("BL-07", priority=3)
        time.sleep(1.1)
        self.s.approve("BL-08", priority=3)
        box = hb.outbox(self.apex)
        p9 = box / "BL-09.md"
        fm, body, _ = hb.parse_item(box / "BL-07.md"); fm["id"] = "BL-09"; fm["priority"] = 9
        p9.write_text(hb.render_item(fm, body))
        valid, _ = hb.list_candidates()
        self.assertEqual([c["fm"]["id"] for c in valid], ["BL-09", "BL-07", "BL-08"])

    def test_claim_item_and_orphan_sweep(self):
        p = self.s.approve()
        c = hb.list_candidates()[0][0]
        infl = hb.claim_item(c)
        self.assertTrue(infl.exists()); self.assertFalse(p.exists())
        ev = hb.orphan_sweep(self.cfg)
        self.assertEqual(len(ev), 1); self.assertTrue(p.exists())
        self.assertEqual(hb.parse_item(p)[0]["attempts"], 1)
        # live item is skipped
        c = hb.list_candidates()[0][0]; hb.claim_item(c)
        self.assertEqual(hb.orphan_sweep(self.cfg, live_item_id="BL-07"), [])
        # third strike -> inbox failed-repeatedly
        hb.orphan_sweep(self.cfg); c = hb.list_candidates()[0][0]; hb.claim_item(c)
        ev = hb.orphan_sweep(self.cfg)
        self.assertIn("failed-repeatedly", ev[0])
        out = hb.inbox(self.apex) / "BL-07" / "outcome.md"
        self.assertTrue(out.exists()); self.assertIn("terminus: failed-repeatedly", out.read_text())
        self.assertFalse(p.exists())

    def test_install_idempotent(self):
        first = hb.install()
        self.assertTrue(any("~outbox" in x for x in first))
        self.assertTrue((self.apex / "~outbox" / "start.md").exists())
        self.assertTrue((self.apex / "~inbox" / "hb").is_dir())
        self.assertEqual(hb.install(), [])
        (self.apex / "~outbox" / "start.md").write_text("custom")
        hb.install(); self.assertEqual((self.apex / "~outbox" / "start.md").read_text(), "custom")


# ── tick / window ────────────────────────────────────────────────────

class TestTickWindow(Base):
    def test_tick_absent_is_silent(self):
        self.assertEqual(hb.tick(self.cfg), 0)
        self.assertFalse(hb.LOG.exists())

    def test_tick_expired_removes(self):
        hb.issue_flag(hb.now_utc() - timedelta(minutes=1))
        hb.tick(self.cfg); self.assertIsNone(self.flag())

    def test_tick_near_close_refuses(self):
        self.s.approve()
        hb.issue_flag(hb.now_utc() + timedelta(minutes=10))     # cap 90 > 10 left
        hb.write_night({"runs": []})
        hb.tick(self.cfg)
        self.assertEqual(self.flag()["status"], "go")
        self.assertIn("not spawning", hb.LOG.read_text())

    def test_tick_count_cap(self):
        self.s.approve(); self.issue()
        hb.write_night({"runs": [{"item_id": "prev"}], "count_cap": 1})
        hb.tick(self.cfg)
        self.assertEqual(self.flag()["status"], "go")
        self.assertTrue((hb.outbox(self.apex) / "BL-07.md").exists())

    def test_tick_runs_item_end_to_end_fake_worker(self):
        self.s.approve(); self.issue(); hb.write_night({"runs": []})
        rc = hb.tick(self.cfg)
        self.assertEqual(rc, 0)
        f = self.flag(); self.assertEqual(f["status"], "go")             # released
        n = hb.read_night(); self.assertEqual(len(n["runs"]), 1)
        run = n["runs"][0]
        self.assertEqual(run["terminus"], "converged"); self.assertEqual(run["branch"], "hb/BL-07")
        out = hb.inbox(self.apex) / "BL-07"
        self.assertTrue((out / "outcome.md").exists()); self.assertTrue((out / "context.md").exists())
        self.assertTrue((out / "item.md").exists())
        self.assertFalse((hb.outbox(self.apex) / "inflight" / "BL-07.md").exists())
        self.assertFalse((self.apex / ".hb-heartbeat" / "sandbox" / "BL-07").exists())     # worktree removed
        self.assertEqual(sh("git", "rev-parse", "--verify", "hb/BL-07", cwd=self.apex).returncode, 0)  # branch kept
        files = sh("git", "diff", "--name-only", "main..hb/BL-07", cwd=self.apex).stdout.split()
        self.assertIn("HB_FAKE_WORK.md", files)
        wt = sh("git", "worktree", "list", cwd=self.apex).stdout
        self.assertNotIn("BL-07", wt)
        # second tick: count cap 1 -> no second run
        hb.tick(self.cfg); self.assertEqual(len(hb.read_night()["runs"]), 1)

    def test_window_open_close_quiet_night(self):
        hb.window_open(self.cfg)
        f = self.flag(); self.assertEqual(f["status"], "go")
        self.assertTrue(hb.NIGHT.exists())
        hb.window_close(self.cfg)
        self.assertIsNone(self.flag())
        summ = list((hb.inbox(self.apex)).glob("night-*.md"))
        self.assertEqual(len(summ), 1)
        self.assertIn("No items ran tonight", summ[0].read_text())

    def test_window_close_corpse(self):
        self.s.approve(); hb.window_open(self.cfg)
        c = hb.claim_flag(4999999)                                     # surely-dead pid
        hb.claim_item(hb.list_candidates()[0][0]); hb.annotate_flag(4999999, item_id="BL-07")
        hb.window_close(self.cfg)
        self.assertIsNone(self.flag())
        self.assertTrue(list(hb.DIAG.glob("*corpse*")))
        self.assertTrue((hb.outbox(self.apex) / "BL-07.md").exists())          # orphan returned
        self.assertEqual(hb.parse_item(hb.outbox(self.apex) / "BL-07.md")[0]["attempts"], 1)
        summ = list((hb.inbox(self.apex)).glob("night-*.md"))[0].read_text()
        self.assertIn("CORPSE", summ)

    def test_window_close_alive_overrun_left_alone(self):
        hb.window_open(self.cfg); hb.claim_flag(os.getpid())
        hb.window_close(self.cfg)
        self.assertEqual(self.flag()["status"], "inflight")
        self.assertIn("OVERRUN", hb.read_night()["notes"][-1])


# ── runner paths ─────────────────────────────────────────────────────

class TestRunner(Base):
    def _claim(self):
        self.issue(); hb.write_night({"runs": []})
        return hb.claim_flag(os.getpid())

    def test_queue_empty_releases_absent(self):
        c = self._claim()
        self.assertIsNone(runner.run(c, self.cfg))
        self.assertIsNone(self.flag())

    def test_invalid_rejected_then_valid_runs(self):
        self.s.approve()
        (hb.outbox(self.apex) / "BAD.md").write_text("junk")
        c = self._claim(); e = runner.run(c, self.cfg)
        self.assertEqual(e["terminus"], "converged")
        self.assertTrue((hb.inbox(self.apex) / "BAD" / "outcome.md").exists())
        self.assertIn("rejected", (hb.inbox(self.apex) / "BAD" / "outcome.md").read_text())

    def test_quota_gate_closed_releases_go(self):
        hb.STATE.mkdir(exist_ok=True)
        hb.QUOTA.write_text(json.dumps({"written_at": hb.iso(hb.now_utc()), "rate_limits": {
            "five_hour": {"used_percentage": 95, "resets_at": time.time() + 3600}}}))
        self.s.approve(); c = self._claim()
        self.assertIsNone(runner.run(c, self.cfg))
        self.assertEqual(self.flag()["status"], "go")
        self.assertTrue((hb.outbox(self.apex) / "BL-07.md").exists())
        self.assertIn("quota gate closed", hb.LOG.read_text())

    def test_quota_void_reading_allows(self):
        hb.STATE.mkdir(exist_ok=True)
        hb.QUOTA.write_text(json.dumps({"written_at": hb.iso(hb.now_utc()), "rate_limits": {
            "five_hour": {"used_percentage": 95, "resets_at": time.time() - 10}}}))
        ok, why, _ = runner.quota_gate(self.cfg)
        self.assertTrue(ok); self.assertIn("void", why)

    def test_unexpected_leaves_corpse(self):
        os.environ["HB_FAKE_MODE"] = "none"
        self.s.approve(); c = self._claim(); e = runner.run(c, self.cfg)
        self.assertEqual(e["terminus"], "unexpected")
        self.assertEqual(self.flag()["status"], "inflight")                     # corpse left for sweep
        self.assertTrue((hb.outbox(self.apex) / "inflight" / "BL-07.md").exists())
        self.assertTrue(list(hb.DIAG.glob("*unexpected*")))
        self.assertTrue((hb.inbox(self.apex) / "BL-07" / "outcome.md").exists())  # partial outcome still visible
        self.assertTrue((self.apex / ".hb-heartbeat" / "sandbox" / "BL-07").exists())  # kept for forensics
        # then (after this process is gone) the close sweep does its job — simulate our death
        f = hb.read_flag(); f["pid"] = 4999999; hb.write_atomic(hb.GO, hb.dump_yaml(f))
        hb.window_close(self.cfg)
        self.assertIsNone(self.flag()); self.assertTrue((hb.outbox(self.apex) / "BL-07.md").exists())

    def test_quota_exhausted_midrun(self):
        os.environ["HB_FAKE_MODE"] = "quota"
        self.s.approve(); c = self._claim(); e = runner.run(c, self.cfg)
        self.assertEqual(e["terminus"], "quota")
        self.assertIsNone(self.flag())
        self.assertTrue(list(hb.DIAG.glob("*quota-exhausted*")))
        self.assertTrue((hb.outbox(self.apex) / "BL-07.md").exists())          # back for another night
        self.assertEqual(hb.parse_item(hb.outbox(self.apex) / "BL-07.md")[0]["attempts"], 1)

    def test_cap_terminus_on_timeout(self):
        os.environ["HB_FAKE_MODE"] = "sleep"
        p = self.s.approve()
        fm, body, _ = hb.parse_item(p); fm["time_cap_min"] = 0.05; p.write_text(hb.render_item(fm, body))
        c = self._claim(); e = runner.run(c, self.cfg)
        self.assertEqual(e["terminus"], "cap")
        self.assertEqual(self.flag()["status"], "go")

    def test_exhausted_is_expected(self):
        os.environ["HB_FAKE_MODE"] = "exhausted"
        self.s.approve(); c = self._claim(); e = runner.run(c, self.cfg)
        self.assertEqual((e["terminus"], e["qa_result"]), ("exhausted", "exhausted"))
        self.assertEqual(self.flag()["status"], "go")

    def test_retry_resumes_branch(self):
        self.s.approve(); c = self._claim(); runner.run(c, self.cfg)
        # approve again (new night), same id -> branch exists -> resumed
        self.s.approve(); c = self._claim(); e = runner.run(c, self.cfg)
        self.assertEqual(e["terminus"], "converged")
        log = sh("git", "log", "--oneline", "main..hb/BL-07", cwd=self.apex).stdout.splitlines()
        self.assertEqual(len(log), 2)

    def test_prompt_renders_all_placeholders(self):
        self.s.approve()
        c = hb.list_candidates()[0][0]
        prov = runner.provision(self.cfg, self.apex, "BL-07", c["fm"])
        txt = runner.render_prompt(self.cfg, prov, self.apex, self.apex, c["fm"], c["body"])
        self.assertNotIn("{{", txt); self.assertIn("hb/BL-07", txt); self.assertIn("00-preboot", txt)
        ov = json.loads((prov["sandbox"] / ".claude" / "settings.local.json").read_text())
        self.assertIn("Bash(gh pr merge:*)", ov["permissions"]["deny"])
        self.assertIn("hb-guard.sh", json.dumps(ov["hooks"]))
        runner.cleanup(self.apex, prov["sandbox"])


# ── hb-guard ─────────────────────────────────────────────────────────

class TestGuard(unittest.TestCase):
    def guard(self, cmd):
        r = subprocess.run(["bash", str(SRC / "hb-guard.sh")], input=json.dumps({"tool_input": {"command": cmd}}),
                           capture_output=True, text=True)
        return r.returncode

    def test_blocks(self):
        for c in ["gh pr merge 12", "gh pr close 12 --delete-branch", "gh pr ready 12", "gh pr review 12 --approve",
                  "gh repo delete x", "gh api repos/x", "git push origin --delete hb/BL-07", "git push -d origin x",
                  "git push origin :hb/BL-07", "git push --force origin hb/x", "git push origin main",
                  "git push origin hb/x:main", "git update-ref refs/heads/main abc", "git worktree add ../x",
                  "git branch -D main", "git branch -f main abc", "git checkout main", "git switch master",
                  "cd /x && git push origin :ref", "git -C /p push origin --delete y", "FOO=1 gh pr merge 3"]:
            self.assertEqual(self.guard(c), 2, f"should block: {c}")

    def test_allows(self):
        for c in ["git push -u origin hb/BL-07", "gh pr create --base main --head hb/BL-07 --title t --body b",
                  "gh pr view 12", "gh pr list", "git merge main", "git branch -a", "git status", "ls",
                  "git checkout -b hb/x", "git push origin hb/BL-07:hb/BL-07", "git commit -m 'x'", "echo main"]:
            self.assertEqual(self.guard(c), 0, f"should allow: {c}")


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1, argv=[a for a in sys.argv if a != "-v"])
