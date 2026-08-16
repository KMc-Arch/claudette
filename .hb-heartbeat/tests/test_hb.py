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
        # a local bare "origin" so the RUNNER's push path is exercised for real (gh pr create will fail: no GitHub)
        self.origin = Path(tempfile.mkdtemp(prefix="hborigin-", dir=str(TMP_BASE)))
        sh("git", "init", "-q", "--bare", cwd=self.origin)
        sh("git", "remote", "add", "origin", str(self.origin), cwd=self.apex)
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
            shutil.rmtree(self.origin, ignore_errors=True)
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

    def open(self):
        return hb.window_open(self.cfg, force=True)      # tests run at arbitrary wall-clock; bypass the window check


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

    def test_id_validation_and_project_containment(self):
        box = hb.outbox(self.apex); box.mkdir(parents=True, exist_ok=True)
        p = self.s.approve()
        fm, body, _ = hb.parse_item(p)
        bad = box / "42.md"; fm2 = dict(fm); fm2["id"] = 42; bad.write_text(hb.render_item(fm2, body))
        fm3, _, errs = hb.parse_item(bad)
        self.assertEqual(errs, []); self.assertEqual(fm3["id"], "42"); self.assertIsInstance(fm3["id"], str)
        weird = box / "a b.md"; fm4 = dict(fm); fm4["id"] = "a b"; weird.write_text(hb.render_item(fm4, body))
        self.assertTrue(any("not matching" in e for e in hb.parse_item(weird)[2]))
        fm5 = dict(fm); fm5["project"] = "../../etc"
        with self.assertRaises(ValueError):
            hb.project_root_for(self.apex, fm5)
        self.assertEqual(hb.project_root_for(self.apex, {"project": "."}), self.apex)

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
        infl = hb.claim_item(c, pid=4999999)                                  # a dead runner
        self.assertTrue(infl.exists()); self.assertFalse(p.exists())
        self.assertTrue(hb._pidfile(infl).exists())
        ev = hb.orphan_sweep(self.cfg)
        self.assertEqual(len(ev), 1); self.assertTrue(p.exists())
        self.assertEqual(hb.parse_item(p)[0]["attempts"], 1)
        # live item is skipped (by flag item_id, and independently by a live pidfile)
        c = hb.list_candidates()[0][0]; hb.claim_item(c, pid=4999999)
        self.assertEqual(hb.orphan_sweep(self.cfg, live_item_id="BL-07"), [])
        hb.write_atomic(hb._pidfile(hb.outbox(self.apex) / "inflight" / "BL-07.md"), json.dumps({"pid": os.getpid(), "pid_start": hb.proc_start(os.getpid())}))
        self.assertEqual(hb.orphan_sweep(self.cfg), [])                        # live pidfile → skipped
        hb.write_atomic(hb._pidfile(hb.outbox(self.apex) / "inflight" / "BL-07.md"), json.dumps({"pid": 4999999}))
        # third strike -> inbox failed-repeatedly
        hb.orphan_sweep(self.cfg); c = hb.list_candidates()[0][0]; hb.claim_item(c, pid=4999999)
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
        self.assertTrue((out / "state-delta.diff").exists())            # sandbox backlog edits preserved as a diff
        self.assertIn("BL-FAKE", (out / "state-delta.diff").read_text())
        self.assertFalse((hb.outbox(self.apex) / "inflight" / "BL-07.md").exists())
        self.assertFalse((self.apex / ".hb-heartbeat" / "sandbox" / "BL-07").exists())     # worktree removed
        self.assertEqual(sh("git", "rev-parse", "--verify", "hb/BL-07", cwd=self.apex).returncode, 0)  # branch kept
        files = sh("git", "diff", "--name-only", "main..hb/BL-07", cwd=self.apex).stdout.split()
        self.assertIn("HB_FAKE_WORK.md", files)
        self.assertTrue(run["pushed"])                                       # RUNNER pushed (local bare origin)
        self.assertEqual(sh("git", "rev-parse", "--verify", "hb/BL-07", cwd=self.s.origin).returncode, 0)
        oc = (out / "outcome.md").read_text()
        self.assertIn("pushed: true", oc); self.assertIn("summary: fake", oc)
        wt = sh("git", "worktree", "list", cwd=self.apex).stdout
        self.assertNotIn("BL-07", wt)
        # second tick: count cap 1 -> no second run
        hb.tick(self.cfg); self.assertEqual(len(hb.read_night()["runs"]), 1)

    def test_window_open_close_quiet_night(self):
        self.open()
        f = self.flag(); self.assertEqual(f["status"], "go")
        self.assertTrue(hb.NIGHT.exists())
        f["window_closes_at"] = hb.iso(hb.now_utc() + timedelta(minutes=5)); hb.write_atomic(hb.GO, hb.dump_yaml(f))  # it is closing time
        hb.window_close(self.cfg)
        self.assertIsNone(self.flag())
        summ = list((hb.inbox(self.apex)).glob("night-*.md"))
        self.assertEqual(len(summ), 1)
        self.assertIn("No items ran tonight", summ[0].read_text())

    def test_window_close_corpse(self):
        self.s.approve(); self.open()
        c = hb.claim_flag(4999999)                                     # surely-dead pid
        hb.claim_item(hb.list_candidates()[0][0], pid=4999999); hb.annotate_flag(4999999, item_id="BL-07")
        hb.window_close(self.cfg)
        self.assertIsNone(self.flag())
        self.assertTrue(list(hb.DIAG.glob("*corpse*")))
        self.assertTrue((hb.outbox(self.apex) / "BL-07.md").exists())          # orphan returned
        self.assertEqual(hb.parse_item(hb.outbox(self.apex) / "BL-07.md")[0]["attempts"], 1)
        summ = list((hb.inbox(self.apex)).glob("night-*.md"))[0].read_text()
        self.assertIn("CORPSE", summ)

    def test_window_close_alive_overrun_left_alone(self):
        self.s.approve(); self.open(); hb.claim_flag(os.getpid())
        hb.claim_item(hb.list_candidates()[0][0]); hb.annotate_flag(os.getpid(), item_id="BL-07")
        hb.window_close(self.cfg)
        self.assertEqual(self.flag()["status"], "inflight")
        self.assertTrue(any("OVERRUN" in x for x in hb.read_night()["notes"]))
        self.assertTrue((hb.outbox(self.apex) / "inflight" / "BL-07.md").exists())     # live item NOT swept
        self.assertTrue(hb.read_night().get("closed"))

    def test_window_open_refuses_over_live_runner(self):
        self.s.approve(); self.open(); hb.claim_flag(os.getpid())
        hb.claim_item(hb.list_candidates()[0][0]); hb.annotate_flag(os.getpid(), item_id="BL-07")
        self.open()                                                             # second open while alive
        f = self.flag(); self.assertEqual(f["status"], "inflight"); self.assertEqual(f["pid"], os.getpid())
        self.assertTrue((hb.outbox(self.apex) / "inflight" / "BL-07.md").exists())     # not orphan-swept
        self.assertIn("refusing to re-arm", hb.LOG.read_text())

    def test_window_open_over_dead_inflight_records_corpse(self):
        self.open(); hb.claim_flag(4999999)
        self.open()
        self.assertEqual(self.flag()["status"], "go")
        self.assertTrue(list(hb.DIAG.glob("*corpse*")))

    def test_window_open_outside_window_refuses(self):
        cfg = dict(self.cfg); cfg["window"] = {"open": "00:00", "close": "00:01"}       # a 1-minute window: we're outside
        hb.window_open(cfg)
        self.assertIsNone(self.flag())
        self.assertIn("outside the window", hb.LOG.read_text())
        self.assertFalse(hb.in_window(cfg))
        cfg["window"] = {"open": "00:00", "close": "23:59"}
        self.assertTrue(hb.in_window(cfg) or datetime.now().hour == 23 and datetime.now().minute == 59)
        # overnight window logic
        from datetime import datetime as _dt
        cfg["window"] = {"open": "22:00", "close": "06:00"}
        self.assertTrue(hb.in_window(cfg, _dt.now().astimezone().replace(hour=23, minute=0)))
        self.assertTrue(hb.in_window(cfg, _dt.now().astimezone().replace(hour=3, minute=0)))
        self.assertFalse(hb.in_window(cfg, _dt.now().astimezone().replace(hour=12, minute=0)))

    def test_close_without_open_still_writes_tonight(self):
        hb.write_night({"night": "1999-01-01", "runs": [{"item_id": "old"}]})
        hb.window_close(self.cfg)
        files = sorted(p.name for p in hb.inbox(self.apex).glob("night-*.md"))
        self.assertEqual(files, [f"night-{hb.night_key()}.md"])
        self.assertIn("close without a recorded open", (hb.inbox(self.apex) / files[0]).read_text())

    def test_kill_switch_then_close_respects_live_pidfile(self):
        self.s.approve(); self.open(); hb.claim_flag(os.getpid())
        hb.claim_item(hb.list_candidates()[0][0])
        hb.GO.unlink()                                                          # kill switch mid-run
        hb.window_close(self.cfg)
        self.assertTrue((hb.outbox(self.apex) / "inflight" / "BL-07.md").exists())     # pidfile says alive → not swept

    def test_tick_touches_last_tick(self):
        hb.tick(self.cfg)
        self.assertTrue((hb.STATE / "last-tick").exists())

    def test_runner_crash_leaves_corpse_and_counts(self):
        self.s.approve(); self.issue(); hb.write_night({"runs": []})
        real = runner.run
        def boom(claim, cfg):
            hb.claim_item(hb.list_candidates()[0][0]); hb.annotate_flag(os.getpid(), item_id="BL-07")
            raise RuntimeError("post-spawn explosion")
        runner.run = boom
        try:
            with self.assertRaises(RuntimeError):
                hb.tick(self.cfg)
        finally:
            runner.run = real
        f = self.flag(); self.assertEqual(f["status"], "inflight")              # corpse left, NOT released
        n = hb.read_night(); self.assertEqual(len(n["runs"]), 1); self.assertEqual(n["runs"][0]["terminus"], "crash")
        self.assertTrue(list(hb.DIAG.glob("*runner-crash*")))
        hb.tick(self.cfg)                                                       # count cap / inflight: no respawn
        self.assertEqual(len(hb.read_night()["runs"]), 1)


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
        hb.write_atomic(hb._pidfile(hb.outbox(self.apex) / "inflight" / "BL-07.md"), json.dumps({"pid": 4999999}))
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

    def test_item_cap_never_exceeds_config(self):
        self.assertEqual(runner.item_cap_min(self.cfg, {"time_cap_min": 500}), self.cfg["item_cap_min"])
        self.assertEqual(runner.item_cap_min(self.cfg, {"time_cap_min": 10}), 10)
        self.assertEqual(runner.item_cap_min(self.cfg, {}), self.cfg["item_cap_min"])

    def test_quota_stale_reading_treated_as_missing(self):
        hb.STATE.mkdir(exist_ok=True)
        old = hb.iso(hb.now_utc() - timedelta(hours=40))
        hb.QUOTA.write_text(json.dumps({"written_at": old, "rate_limits": {"five_hour": {"used_percentage": 99, "resets_at": time.time() + 3600}}}))
        ok, why, _ = runner.quota_gate(self.cfg)
        self.assertTrue(ok); self.assertIn("stale", why)                        # policy allow
        cfg = json.loads(json.dumps(self.cfg)); cfg["quota"]["missing_policy"] = "block"
        ok, why, _ = runner.quota_gate(cfg)
        self.assertFalse(ok)
        # seven_day binds too
        hb.QUOTA.write_text(json.dumps({"written_at": hb.iso(hb.now_utc()), "rate_limits": {"seven_day": {"used_percentage": 99, "resets_at": time.time() + 3600}}}))
        ok, why, _ = runner.quota_gate(self.cfg)
        self.assertFalse(ok); self.assertIn("seven_day", why)

    def test_worker_env_has_no_credentials(self):
        os.environ["GH_TOKEN"] = "ghp_should_be_stripped"; os.environ["GIT_SSH_COMMAND"] = "ssh -i x"
        try:
            env = runner.worker_env(self.cfg, self.apex / ".hb-heartbeat" / "sandbox" / "X", "X", 60)
        finally:
            os.environ.pop("GH_TOKEN"); os.environ.pop("GIT_SSH_COMMAND")
        self.assertNotIn("GH_TOKEN", env); self.assertNotIn("GIT_SSH_COMMAND", env)
        self.assertEqual(env["GIT_CONFIG_COUNT"], "4")
        self.assertEqual((env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]), ("credential.helper", ""))
        self.assertEqual((env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_VALUE_1"]), ("core.askPass", "/bin/false"))
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null"); self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertTrue(Path(env["GH_CONFIG_DIR"]).is_dir()); self.assertFalse(list(Path(env["GH_CONFIG_DIR"]).glob("hosts.yml")))
        self.assertTrue(env["XDG_CONFIG_HOME"].startswith(env["GH_CONFIG_DIR"]))
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["HB_SANDBOX"], str(self.apex / ".hb-heartbeat" / "sandbox" / "X"))
        self.assertIn("HB_APEX_ALIASES", env)
        # behavioural: git under this env resolves NO credential helper for github.com
        r = subprocess.run(["git", "config", "--get-all", "credential.helper"], env=env, capture_output=True, text=True, cwd=str(self.apex))
        self.assertEqual(r.stdout.strip(), "")
        r = subprocess.run(["gh", "auth", "status"], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_pid_start_identity(self):
        me = os.getpid()
        self.assertTrue(hb.pid_alive(me, hb.proc_start(me)))
        self.assertFalse(hb.pid_alive(me, "1"))                                # live pid, wrong start → not ours
        self.assertTrue(hb.pid_alive(me, None))

    def test_cap_reaches_worker_env(self):
        os.environ["HB_FAKE_MODE"] = "envdump"
        p = self.s.approve()
        fm, body, _ = hb.parse_item(p); fm["time_cap_min"] = 500; p.write_text(hb.render_item(fm, body))
        c = self._claim(); e = runner.run(c, self.cfg)
        dumped = json.loads((hb.inbox(self.apex) / "BL-07" / "context.md").read_text())
        self.assertEqual(int(dumped["CBOOT_EXEC_TIMEOUT"]), self.cfg["item_cap_min"] * 60)  # ceiling, not 500
        self.assertEqual(dumped["GIT_CONFIG_VALUE_0"], ""); self.assertNotIn("GH_TOKEN", dumped)

    def test_publish_scrubs_pr_text_and_titles(self):
        self.assertEqual(runner._clean_title("--evil title\nsecond"), "evil title")
        self.assertEqual(runner._clean_title("   \n  "), "")
        self.assertEqual(runner._clean_title(None), "")
        f = hb.STATE / "prtest.md"; hb.STATE.mkdir(exist_ok=True)
        f.write_text("hello world\n")
        ok, why = runner.scrub_text_file(f)
        self.assertTrue(ok, why)
        f.write_text("token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd\n")   # scrub:allow — synthetic token fixture
        ok, why = runner.scrub_text_file(f)
        self.assertFalse(ok)

    def test_scope_breach_reported(self):
        self.assertEqual(runner.scope_breach(["a/b.md", "c.md"], ["a"]), ["c.md"])
        self.assertEqual(runner.scope_breach(["a/b.md"], []), [])
        os.environ["HB_FAKE_MODE"] = "converged"
        p = self.s.approve()
        fm, body, _ = hb.parse_item(p); fm["scope"] = [".codex"]; p.write_text(hb.render_item(fm, body))
        c = self._claim(); e = runner.run(c, self.cfg)
        self.assertIn("scope_breach:\n- HB_FAKE_WORK.md", (hb.inbox(self.apex) / "BL-07" / "outcome.md").read_text())

    def test_read_result_hostile_shapes(self):
        c = hb.list_candidates
        sb = self.apex / ".hb-heartbeat" / "sandbox" / "Y"; rd = sb / runner.RESULT_REL; rd.mkdir(parents=True)
        (rd / "outcome.md").mkdir()                                            # a directory named outcome.md
        fm, body, extra = runner.read_result(sb); self.assertEqual(fm, {})
        shutil.rmtree(rd / "outcome.md")
        (rd / "outcome.md").write_bytes(b"---\nterminus: converged\n---\n\xff\xfe bad utf8")
        fm, body, extra = runner.read_result(sb); self.assertEqual(fm.get("terminus"), "converged")
        (rd / "outcome.md").write_bytes(b"x" * (runner.MAX_RESULT_BYTES + 100))
        fm, body, extra = runner.read_result(sb); self.assertIn("truncated by runner", body)

    def test_project_not_a_repo_root_is_invalid(self):
        sub = self.apex / "grp"; sub.mkdir(); (sub / "CLAUDE.md").write_text("---\nroot: true\n---\n")
        p = self.s.approve()
        fm, body, _ = hb.parse_item(p); fm["project"] = "grp"; p.write_text(hb.render_item(fm, body))
        valid, invalid = hb.list_candidates()
        self.assertEqual(valid, []); self.assertTrue(any("not the top level" in e for e in invalid[0]["errors"]))
        fm["project"] = "/tmp"; p.write_text(hb.render_item(fm, body))
        valid, invalid = hb.list_candidates()
        self.assertTrue(any("outside the apex" in e for e in invalid[0]["errors"]))

    def test_late_close_leaves_fresh_flag(self):
        cfg = dict(self.cfg); cfg["window"] = {"open": "00:00", "close": "23:59"}     # we are inside this window
        hb.issue_flag(hb.now_utc() + timedelta(hours=3))
        hb.write_night({"night": hb.night_key(), "runs": []})
        hb.window_close(cfg)
        self.assertEqual(self.flag()["status"], "go")                            # not revoked by a late close

    def test_approve_validates(self):
        bf = hb.STATE / "body.md"; hb.STATE.mkdir(exist_ok=True); bf.write_text("# body\n")
        with self.assertRaises(SystemExit) as cm:
            hb.approve("bad id", None, None, None, str(bf), self.cfg)
        self.assertIn("invalid id", str(cm.exception))
        with self.assertRaises(SystemExit):
            hb.approve("BL-07", None, "12", None, None, self.cfg)

    def test_publish_skipped_when_no_commits(self):
        os.environ["HB_FAKE_MODE"] = "nocommit"
        self.s.approve(); c = self._claim(); e = runner.run(c, self.cfg)
        self.assertEqual(e["terminus"], "converged"); self.assertFalse(e["pushed"])
        self.assertIn("no commits", (hb.inbox(self.apex) / "BL-07" / "outcome.md").read_text())

    def test_publish_withholds_push_on_flagged_commit_message(self):
        os.environ["HB_FAKE_MODE"] = "secretmsg"
        self.s.approve(); c = self._claim(); e = runner.run(c, self.cfg)
        self.assertEqual(e["terminus"], "converged"); self.assertFalse(e["pushed"])
        self.assertIn("push withheld", (hb.inbox(self.apex) / "BL-07" / "outcome.md").read_text())
        self.assertNotEqual(sh("git", "rev-parse", "--verify", "hb/BL-07", cwd=self.s.origin, check=False).returncode, 0)

    def test_publish_scrub_gate_helpers(self):
        f = hb.STATE / "x.md"; hb.STATE.mkdir(exist_ok=True)
        f.write_text("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd scrub:allow\n")
        self.assertFalse(runner.scrub_text_file(f)[0])                          # pragma is not honoured for worker text
        f.write_text("x" * 2500 + " ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd\n")   # scrub:allow — synthetic token fixture
        self.assertFalse(runner.scrub_text_file(f)[0])                          # long lines are folded before scanning

    def test_scope_breach_withholds_publish(self):
        os.environ["HB_FAKE_MODE"] = "converged"
        p = self.s.approve()
        fm, body, _ = hb.parse_item(p); fm["scope"] = [".codex"]; p.write_text(hb.render_item(fm, body))
        c = self._claim(); e = runner.run(c, self.cfg)
        self.assertFalse(e["pushed"])
        oc = (hb.inbox(self.apex) / "BL-07" / "outcome.md").read_text()
        self.assertIn("publish withheld", oc); self.assertIn("scope_breach:\n- HB_FAKE_WORK.md", oc)

    def test_classify_runner_evidence_outranks_worker(self):
        self.assertEqual(runner.classify({"timed_out": True}, {"terminus": "converged", "qa_result": "converged"}), ("cap", "converged"))
        self.assertEqual(runner.classify({"is_error": True, "result": "usage limit reached"}, {"terminus": "converged"}), ("quota", "n/a"))
        self.assertEqual(runner.classify({}, {"terminus": "converged", "qa_result": "held"}), ("converged", "held"))

    def test_requeue_or_fail_threshold_on_runner_paths(self):
        p = self.s.approve()
        fm, body, _ = hb.parse_item(p); fm["attempts"] = 2; p.write_text(hb.render_item(fm, body))     # one strike left
        real = runner.provision
        runner.provision = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            c = self._claim(); e = runner.run(c, self.cfg)
        finally:
            runner.provision = real
        self.assertEqual(e["terminus"], "unexpected")
        self.assertFalse((hb.outbox(self.apex) / "BL-07.md").exists())                       # not requeued forever
        self.assertIn("failed-repeatedly", (hb.inbox(self.apex) / "BL-07" / "outcome.md").read_text())

    def test_worker_env_has_identity(self):
        env = runner.worker_env(self.cfg, self.apex / ".hb-heartbeat" / "sandbox" / "X", "X", 60)
        keys = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}
        self.assertIn("user.name", keys); self.assertIn("user.email", keys); self.assertTrue(keys["user.name"])
        r = subprocess.run(["git", "config", "--get", "user.email"], env=env, capture_output=True, text=True, cwd=str(self.apex))
        self.assertTrue(r.stdout.strip())

    def test_child_sandbox_control_dir_ignored(self):
        # a scratch "child" repo that does not track .hb-heartbeat: control files must be invisible to git add -A
        child = self.apex / "child"; child.mkdir()
        (child / "CLAUDE.md").write_text("---\nroot: true\n---\n"); (child / "README.md").write_text("c\n")
        (child / ".state" / "work").mkdir(parents=True); (child / ".state" / "work" / "backlog.md").write_text("### BL-01 x\nbody\n")
        sh("git", "init", "-q", "-b", "main", cwd=child)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=child)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=child)
        prov = runner.provision(self.cfg, child, "BL-01", {"id": "BL-01", "attempts": 0})
        st = sh("git", "status", "--porcelain", "--untracked-files=all", cwd=str(prov["sandbox"])).stdout
        self.assertNotIn(".hb-heartbeat", st, st)
        self.assertNotIn(".state/work", st, st)                                              # tracked -> not overwritten
        runner.cleanup(child, prov["sandbox"])

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
        main_sha = sh("git", "rev-parse", "main", cwd=self.apex).stdout.strip()
        self.assertEqual(e["base_commit"], main_sha)                            # fork point via merge-base
        self.assertEqual(hb.read_night().get("runs", []) or [{}], hb.read_night().get("runs", []) or [{}])

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
    SB = "/mnt/claudette/.hb-heartbeat/sandbox/BL-07"

    def guard(self, cmd, cwd=None):
        env = dict(os.environ); env["CLAUDE_PROJECT_DIR"] = self.SB; env.pop("HB_SANDBOX", None); env["HB_APEX_ALIASES"] = "/mnt/d/claudette"
        r = subprocess.run(["bash", str(SRC / "hb-guard.sh")], input=json.dumps({"cwd": cwd or self.SB, "tool_input": {"command": cmd}}),
                           capture_output=True, text=True, env=env)
        return r.returncode

    def test_blocks(self):
        for c in ["gh pr merge 12", "gh pr close 12 --delete-branch", "gh pr ready 12", "gh pr review 12 --approve",
                  "gh pr create --title x", "gh repo delete x", "gh api repos/x", "gh auth token", "gh alias set m 'pr merge'",
                  "gh -R KMc-Arch/claudette pr merge 3", "env gh pr merge 12", "command gh pr merge 12", "bash -c 'gh pr merge 12'",
                  "sh -c \"gh pr merge 12\"", "eval 'gh pr merge 12'", "exec gh pr merge 12", "echo 12 | xargs gh pr merge",
                  "timeout 5 gh pr merge 1", "nohup gh pr merge 1 &", "$(gh pr merge 1)", "echo `gh pr merge 1`",
                  "python3 -c 'import subprocess;subprocess.run([\"gh\",\"pr\",\"merge\",\"1\"])'",
                  "git push origin hb/BL-07", "git push -u origin hb/BL-07", "git push origin HEAD:refs/heads/main",
                  "git push origin +hb/x:refs/heads/main", "git push --force origin hb/x", "git push origin --delete hb/x",
                  "git --no-pager push origin x", "git -c alias.x=push x origin main", "git -c 'alias.z=!gh pr merge 12' z",
                  "git -C /mnt/claudette merge hb/BL-07", "git --git-dir=/mnt/claudette/.git commit -m x", "git --exec-path=/x status",
                  "git config alias.p push", "git config core.hooksPath /x", "git update-ref refs/heads/main abc",
                  "git worktree add ../x", "git branch -D main", "git branch -M hb/x main", "git checkout main", "git switch master",
                  "git switch -c x origin/main", "git checkout -B main", "git remote set-url origin x", "git tag -f v1", "git clone x",
                  "python3 /mnt/claudette/.hb-heartbeat/hb.py window open", "python3 ../../hb.py approve X",
                  "printf 'status: go' > /mnt/claudette/.hb-heartbeat/state/GO", "echo x >/mnt/claudette/x", "cp x ../../../.codex/foo.sh",
                  "ln -s /mnt/claudette/.codex live", "ls /mnt/claudette/~outbox/hb", "cat ~/.config/gh/hosts.yml", "GH_TOKEN=abc gh pr view 1",
                  "HB_HOME=/x python3 hb.py tick", "CLAUDE_PROJECT_DIR=/mnt/claudette ls", "GIT_CONFIG_COUNT=1 git status",
                  "cd .. && ls",
                  "echo x > /mnt/claud*/.hb-heartbeat/state/GO", "cat /mnt/claudette/.hb-heartbeat/state/G?", "cat /home/KMc/.co*/gh/ho*.yml",
                  "git rebase -x 'git status' HEAD~1", "git bisect run sh -c 'x'", "git difftool HEAD~1", "env -u GH_CONFIG_DIR git status",
                  "unset GH_CONFIG_DIR GIT_CONFIG_COUNT", "export HOME=/tmp", "sh -c 'unset GH_CONFIG_DIR; gh pr list'", "git -c core.pager='cp x /tmp' log",
                  "git -c diff.external=x diff", "dd if=/dev/zero of=/mnt/claudette/.hb-heartbeat/state/GO", "cp x --target-directory=/mnt/claudette/.codex",
                  "wget -O/mnt/claudette/x http://e", "if true; then git push origin main; fi", "{ git update-ref refs/heads/main HEAD; }", "! git push origin main",
                  "for i in 1; do gh pr merge 1; done", "cat <(git push origin main)", "tee >(git push origin main)", "cmd.exe /c dir", "cat D:/claudette/x",
                  "ls /mnt/d/claudette/.hb-heartbeat", "python3 -c 'import subprocess'", "env -i git status", "git add -p", "git commit -e -m x",
                  "cat ~/.claude/.credentials.json", "cat /home/KMc/.git-credentials", "cat ~/.ssh/id_rsa", "cat ~/.ssh/id_ed25519", "cat ~/.netrc",
                  "declare -x GH_TOKEN=x", "ls ../*", "GITHUB_TOKEN=x gh pr view 1", "XDG_CONFIG_HOME=/tmp gh pr view 1", "PATH=/x:$PATH ls",
                  "git --config-env=user.name=X commit -m x", "python3 -c \"__import__('os').system('gh pr merge 1')\"",
                  "git grep -O'sh -c x' foo", "X=/mnt/claudette; cat $X/CLAUDE.md", "cat $HOME/../../mnt/claudette/x", "cat ${X}/x",
                  "builtin typeset -x GIT_CONFIG_GLOBAL=/x", "env -uGIT_CONFIG_GLOBAL git status", "GIT_EDITOR='cp x /tmp' git commit",
                  "xargs -0 sh -c 'cp x /mnt/claudette/.codex/e'", "ls /mnt/d/CLAUDETTE/.hb-heartbeat", "ls /MNT/CLAUDETTE/.HB-HEARTBEAT",
                  "git help --web commit", "git cherry-pick -e abc", "echo 'see /mnt/claudette/.codex' > x"]:
            self.assertEqual(self.guard(c), 2, f"should block: {c}")

    def test_allows(self):
        for c in ["git status", "git add -A && git commit -m 'x'", "git log --oneline main..HEAD", "git diff --name-only ea8a227..HEAD",
                  "git branch --show-current", "git branch -a", "git checkout -- README.md", "git checkout -b hb/x2", "git merge main",
                  "git rebase main", "git stash", "git stash pop", "git config --get user.name", "git config --list",
                  "git -c user.name=hb commit -m x", "git --no-pager log -1", "git rev-parse HEAD", "git show HEAD --stat", "git reset --hard HEAD~1",
                  "gh pr view 39", "gh pr list", "gh pr diff 39", "gh --version",
                  "python3 .codex/explicit/scrub/scrub.py range a..b", "ls -la /mnt/claudette/.hb-heartbeat/sandbox/BL-07/.codex",
                  "cat .codex/start.md", "python3 -m pytest tests/", "grep -rn foo .", "echo main", "echo 'git push origin main'",
                  "git commit -m 'fix; gh pr merge 1'", "git log --grep='push'", "cd /mnt/claudette/.hb-heartbeat/sandbox/BL-07 && ls",
                  "ls /tmp", "cat ~/.claude/settings.json", "git status; ls", "git add -A && git commit -m 'msg with | pipe'",
                  "cat <<EOF > notes.md\ngit push origin main\nEOF", "python3 - <<'EOF'\nprint(1)\nEOF",
                  "git log -p -1", "ls *.log", "for f in *.md; do echo $f; done", "cat <(echo hi)", "export FOO=bar", "unset FOO",
                  "if true; then echo hi; fi", "curl http://example.com/x", "echo a:b", "python3 -c 'print(1)'", "git checkout -b hb/x2",
                  "cat > notes.md <<EOF\nSee /mnt/claudette/CLAUDE.md for details\nEOF", "echo $PATH", "git log --format=%h", "grep -e pattern file",
                  "find . -name '*.md'", "sed -i 's/a/b/' x", "ls foo=bar.md", "echo D:", "git grep foo", "echo 10:30"]:
            self.assertEqual(self.guard(c), 0, f"should allow: {c}")


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1, argv=[a for a in sys.argv if a != "-v"])
