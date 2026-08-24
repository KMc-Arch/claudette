#!/usr/bin/env python3
"""Heartbeat (HB) — nightly unattended backlog execution for claudette.

    KILL SWITCH:  rm .hb-heartbeat/state/GO      (all backlog runs stop at the next tick)
                  NOTE: the DB keep-alive ping (keepalive()) is GO-independent by design and keeps
                  firing after `rm GO`; disable it separately via cfg keepalive.enabled=false or
                  `touch .hb-heartbeat/state/NO-KEEPALIVE`.

Deterministic control plane. No model call happens in this file. The only process
that ever talks to a model is the *worker* spawned by runner.py — inside a sandbox
worktree, hard-rooted there, and it never touches the GO flag or the queues.

CLI:
    hb.py tick                      # Task Scheduler, every N min: keep-alive; read GO; maybe claim + run one item
    hb.py run                       # SESSION-DRIVEN (apex-only): arm + process ONE item now + release; no scheduler
    hb.py loop start|stop|status    # SESSION-DRIVEN (apex-only): detached `tick` every N s (default 3600); non-persistent
    hb.py window open|close         # Task Scheduler, twice nightly: issue / revoke GO, sweeps, nightly summary
    hb.py install [--dry-run]       # materialize ~outbox/~inbox (+ start.md) at every root in roots.db
    hb.py approve <ID> [--project P] [--priority N] [--model M]   # backlog section -> ~outbox/hb/<ID>.md
    hb.py status                    # flag, tonight, queues, inflight
    hb.py kill                      # rm GO (same as the kill switch, with a log line)
    hb.py summary                   # (re)write tonight's ~inbox/hb/night-<date>.md

Layout (all under the apex):
    .hb-heartbeat/state/GO          permission token   (absent | go | inflight)
    .hb-heartbeat/state/night.json  tonight's ledger   (opened_at, closes_at, runs[])
    .hb-heartbeat/state/quota.json  statusLine telemetry sink (rate_limits + ts)
    .hb-heartbeat/state/diag/       unexpected-failure records (dumb writes)
    .hb-heartbeat/state/log/hb.log  control-plane log (quiet ticks write nothing)
    <root>/~outbox/hb/<ID>.md       approved items;  inflight/ = claimed
    <root>/~inbox/hb/<ID>/          outcomes;        night-<date>.md = nightly summary (apex only)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# HB_HOME lets the test harness point the whole control plane at a scratch apex.
HB = Path(os.environ.get("HB_HOME") or Path(__file__).resolve().parent).resolve()
APEX = HB.parent
STATE = HB / "state"
GO = STATE / "GO"
NIGHT = STATE / "night.json"
QUOTA = STATE / "quota.json"
DIAG = STATE / "diag"
LOG_DIR = STATE / "log"
LOG = LOG_DIR / "hb.log"
KEEPALIVE_STAMP = STATE / "last-keepalive"   # night_key of the last keep-alive attempt (once/night guard)
NO_KEEPALIVE = STATE / "NO-KEEPALIVE"        # sentinel: `touch` it to disable the keep-alive without editing config
LOOP_STATE = STATE / "loop.json"             # session-driven background ticker: pid + interval (see loop_*)
LOOP_LOG = LOG_DIR / "loop.log"
TEMPLATES = HB / "templates"
ROOTS_DB = APEX / ".state" / "roots.db"

RECIPIENT = "hb"
REQUIRED_ITEM_FIELDS = ("id", "recipient", "sender", "project", "priority", "status",
                        "approved_by", "approved_at", "attempts")
TERMINI_EXPECTED = ("converged", "exhausted", "cap")


# ── time ─────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s) -> datetime | None:
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    s = str(s).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def local_today_at(hhmm: str, day_offset: int = 0) -> datetime:
    """Local wall-clock HH:MM (today + offset) as an aware datetime."""
    h, m = (int(x) for x in hhmm.split(":"))
    local = datetime.now().astimezone()
    d = (local + timedelta(days=day_offset)).replace(hour=h, minute=m, second=0, microsecond=0)
    return d


def night_key(dt: datetime | None = None) -> str:
    """Date label for tonight: the *morning* the window closes on (local)."""
    dt = dt or datetime.now().astimezone()
    return dt.strftime("%Y-%m-%d")


# ── config ───────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = json.loads((HB / "config.json").read_text(encoding="utf-8"))
    override = STATE / "config.json"
    if override.exists():
        try:
            o = json.loads(override.read_text(encoding="utf-8"))
            for k, v in o.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except (OSError, json.JSONDecodeError) as e:
            log(f"WARN config override unreadable: {e}")
    return cfg


# ── logging ──────────────────────────────────────────────────────────

def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{iso(now_utc())} [{os.getpid()}] {msg}\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    if os.environ.get("HB_VERBOSE"):
        sys.stderr.write(line)


# ── atomic file helpers ──────────────────────────────────────────────

def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def dump_yaml(d: dict) -> str:
    return yaml.safe_dump(d, sort_keys=False, default_flow_style=False, allow_unicode=True)


def proc_start(pid) -> str | None:
    """Process start time (jiffies since boot, /proc/<pid>/stat field 22) — identity beyond a reusable pid."""
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as f:
            stat = f.read().decode("ascii", "replace")
        return stat.rsplit(")", 1)[1].split()[19]
    except (OSError, ValueError, IndexError, TypeError):
        return None


def pid_alive(pid, start=None) -> bool:
    """kill -0 plus, when a start time was recorded, a /proc start-time match (pid reuse after a WSL VM
    restart would otherwise make a corpse look alive)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    if start:
        now_start = proc_start(pid)
        if now_start is not None and str(now_start) != str(start):
            return False
    return True


def flag_alive(d: dict | None) -> bool:
    return bool(d) and pid_alive(d.get("pid"), d.get("pid_start"))


# ── GO flag ──────────────────────────────────────────────────────────
# States: absent | go | inflight.  Transitions (who):
#   absent   -> go        window open (detector)
#   go       -> inflight  tick (claim; atomic rename, PRE-spawn)
#   inflight -> inflight  runner annotates (transcript_path, item_id) — pid must match
#   inflight -> go        runner, expected terminus — pid must match
#   inflight -> absent    runner, quota exhausted / queue empty — pid must match
#   go|inflight -> absent window close, tick-on-expiry, human (rm)
# Nothing here ever creates GO from absent except window open.

def read_flag() -> dict | None:
    try:
        text = GO.read_text(encoding="utf-8", errors="replace")   # a corrupt (non-UTF-8) GO must not crash the tick
    except FileNotFoundError:
        return None
    except OSError as e:
        # every sibling reader (read_night/read_quota/read_loop/keepalive/status) catches OSError;
        # read_flag was the odd one out, so a GO that was a directory or unreadable wedged EVERY
        # command — including `hb kill`, the kill switch itself.
        log(f"ERROR GO unreadable ({e!r}); treating as corrupt")
        return {"status": "corrupt", "_error": repr(e)}
    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        log("ERROR GO flag unparseable; treating as absent for spawn purposes")
        return {"status": "corrupt", "_raw": text}
    return d if isinstance(d, dict) else {"status": "corrupt", "_raw": text}


def issue_flag(closes_at: datetime) -> dict:
    """window open: absent -> go (overwrites a stale flag, loudly)."""
    prev = read_flag()
    if prev is not None:
        log(f"ERROR GO present at window open (previous close failed): {json.dumps(prev, default=str)} — overwriting")
    d = {"status": "go", "issued_at": iso(now_utc()), "window_closes_at": iso(closes_at)}
    STATE.mkdir(parents=True, exist_ok=True)
    write_atomic(GO, dump_yaml(d))
    log(f"GO issued; closes {d['window_closes_at']}")
    return d


def claim_flag(pid: int | None = None) -> dict | None:
    """go -> inflight, atomically. The rename IS the claim: exactly one caller wins.
    Returns the inflight flag dict, or None if the claim was lost / flag not `go`."""
    pid = pid or os.getpid()
    tmp = GO.with_name(f"GO.claim.{pid}")
    try:
        os.rename(GO, tmp)
    except FileNotFoundError:
        return None
    try:
        try:
            d = yaml.safe_load(tmp.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            d = {}
        if not isinstance(d, dict) or d.get("status") != "go":
            # not ours to claim — put it back untouched
            os.rename(tmp, GO)
            return None
        d.update({"status": "inflight", "claimed_at": iso(now_utc()), "pid": pid, "pid_start": proc_start(pid),
                  "transcript_path": None, "item_id": None})
        write_atomic(tmp, dump_yaml(d))       # separate temp + replace: a failed write never truncates the token
        os.rename(tmp, GO)
    except Exception as e:
        # never leave the token renamed away: best-effort restore, then report
        log(f"ERROR claim_flag failed mid-claim: {e!r}; restoring GO")
        try:
            if tmp.exists() and not GO.exists():
                os.rename(tmp, GO)
        except OSError as e2:
            log(f"ERROR restore failed: {e2!r} — GO may be missing; window open will re-issue")
        return None
    log(f"claimed GO (inflight, pid {pid})")
    return d


def _owned_inflight(pid: int) -> dict | None:
    d = read_flag()
    if not d or d.get("status") != "inflight":
        return None
    try:
        if int(d.get("pid")) != int(pid):
            return None
    except (TypeError, ValueError):
        return None
    return d


def annotate_flag(pid: int, **fields) -> bool:
    """inflight -> inflight (+fields). Only the owning pid. Never creates."""
    d = _owned_inflight(pid)
    if d is None:
        log(f"WARN annotate refused (flag not our inflight): {fields}")
        return False
    d.update(fields)
    write_atomic(GO, dump_yaml(d))
    return True


def release_flag(pid: int, to: str = "go") -> bool:
    """inflight -> go | absent. Only the owning pid. Never creates from absent
    (so a human `rm GO` mid-run stays absent)."""
    d = _owned_inflight(pid)
    if d is None:
        log(f"WARN release->{to} refused (flag not our inflight; kill switch or sweep won)")
        return False
    if to == "absent":
        try:
            GO.unlink()
        except FileNotFoundError:
            pass
        log("GO released -> absent")
        return True
    keep = {"status": "go", "issued_at": d.get("issued_at"), "window_closes_at": d.get("window_closes_at")}
    write_atomic(GO, dump_yaml(keep))
    log("GO released -> go")
    return True


def remove_flag(reason: str) -> None:
    try:
        GO.unlink()
        log(f"GO removed ({reason})")
    except FileNotFoundError:
        pass
    except OSError as e:
        # without this, window_close's corrupt-flag branch crashes here instead of recovering,
        # and the kill switch itself dies on a GO that is not a regular file
        log(f"ERROR could not remove GO ({reason}): {e!r}")


# ── night ledger ─────────────────────────────────────────────────────

def read_night() -> dict:
    try:
        return json.loads(NIGHT.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_night(d: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    write_atomic(NIGHT, json.dumps(d, indent=2, default=str))


def night_add_run(entry: dict) -> None:
    n = read_night()
    n.setdefault("runs", []).append(entry)
    write_night(n)


def night_note(msg: str) -> None:
    n = read_night()
    n.setdefault("notes", []).append(f"{iso(now_utc())} {msg}")
    write_night(n)


# ── roots / mailboxes ────────────────────────────────────────────────

def roots() -> list[dict]:
    """All root: true contexts (apex first) from roots.db; falls back to apex only."""
    out = [{"name": "Claudette", "abs_path": str(APEX), "rel_path": "."}]
    if not ROOTS_DB.exists():
        return out
    try:
        conn = sqlite3.connect(f"file:{ROOTS_DB.as_posix()}?immutable=1&mode=ro", uri=True)
        rows = conn.execute("SELECT name, abs_path, rel_path FROM roots ORDER BY id").fetchall()
        conn.close()
    except sqlite3.Error as e:
        log(f"WARN roots.db unreadable ({e}); apex only")
        return out
    seen = {str(APEX)}
    for name, abs_path, rel in rows:
        if abs_path in seen or not Path(abs_path).is_dir():
            continue
        seen.add(abs_path)
        out.append({"name": name, "abs_path": abs_path, "rel_path": rel})
    return out


def outbox(root: Path) -> Path:
    return root / "~outbox" / RECIPIENT


def inbox(root: Path) -> Path:
    return root / "~inbox" / RECIPIENT


def caller_root() -> Path | None:
    """The nearest context root at/above the CWD, found by walking the CLAUDE.md chain — NOT roots.db, which
    is a rebuildable cache that is absent on a fresh checkout / after `purge all` / before cboot (relying on
    it made this guard fail OPEN: roots() fell back to apex-only, so any child subtree matched the apex).
    A directory bearing a CLAUDE.md is a root boundary; the nearest one wins. Fails CLOSED — a stray
    intermediate CLAUDE.md aborts a driver rather than waving a child through. None if the CWD is outside
    the apex tree entirely."""
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return None
    apex = APEX.resolve()
    if cwd != apex and apex not in cwd.parents:
        return None                          # outside the apex tree
    p = cwd
    while True:
        if (p / "CLAUDE.md").is_file():
            return p                         # nearest CLAUDE.md-bearing dir = nearest root
        if p == apex:
            return apex                      # apex always terminates the walk
        p = p.parent


def require_apex(cmd: str) -> None:
    """Session-facing driver commands (`run`, `loop`) mutate the single apex-global control plane
    (one GO / queue / quota / night ledger). Refuse to run them from a child project's context so the
    apex-global effect is never mistaken for a per-project one. `tick`/`window` are exempt — the
    scheduler invokes them from an arbitrary CWD."""
    cr = caller_root()
    if cr is None or cr != APEX.resolve():
        sys.stderr.write(
            f"hb: `{cmd}` must be run from the apex ({APEX.name}) context — HB is a single apex-global "
            f"control plane (one GO / queue / quota). Current context: {cr or Path.cwd()}.\n"
            f"    cd {APEX} and retry.\n")
        raise SystemExit(3)


def install(dry_run: bool = False) -> list[str]:
    """Materialize mailboxes at every root. Idempotent; never overwrites a start.md."""
    done = []
    for r in roots():
        root = Path(r["abs_path"])
        for box in ("~outbox", "~inbox"):
            tpl = TEMPLATES / box / "start.md"
            for d in ((root / box), (root / box / RECIPIENT)) + (((root / box / RECIPIENT / "inflight"),) if box == "~outbox" else ()):
                if not d.exists():
                    done.append(f"mkdir {d}")
                    if not dry_run:
                        d.mkdir(parents=True, exist_ok=True)
            dst = root / box / "start.md"
            if not dst.exists():
                done.append(f"write {dst}")
                if not dry_run:
                    shutil.copyfile(tpl, dst)
    return done


# ── items ────────────────────────────────────────────────────────────

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def parse_item(path: Path) -> tuple[dict, str, list[str]]:
    """Return (frontmatter, body, errors). Never guesses: errors are fatal for pop."""
    errs = []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        # UnicodeDecodeError is a ValueError, not an OSError. One latin-1 byte in any queued
        # item used to crash list_candidates/status outright, and — with a window armed —
        # crash the tick, which records a `crash` run that CONSUMES count_cap and leaves GO
        # inflight. The bad file is never removed, so every subsequent night repeated it:
        # a permanent silent wedge from one pasted curly quote.
        return {}, "", [f"unreadable: {e}"]
    m = FM_RE.match(text)
    if not m:
        return {}, text, ["no frontmatter"]
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        return {}, m.group(2), [f"frontmatter yaml: {e}"]
    if not isinstance(fm, dict):
        return {}, m.group(2), ["frontmatter not a mapping"]
    for k in REQUIRED_ITEM_FIELDS:
        if k not in fm or fm[k] is None or fm[k] == "":
            errs.append(f"missing {k}")
    if fm.get("recipient") != RECIPIENT:
        errs.append(f"recipient != {RECIPIENT}")
    if fm.get("id") is not None:
        fm["id"] = str(fm["id"])
        if not ID_RE.match(fm["id"]):
            errs.append(f"id {fm['id']!r} not matching {ID_RE.pattern}")
        if path.stem != fm["id"]:
            errs.append(f"filename {path.name} != id {fm['id']}.md")
    proj = str(fm.get("project", ".") or ".")
    if ".." in Path(proj).parts or proj.startswith("^/^/.."):
        errs.append("project must not contain '..'")
    try:
        p = int(fm.get("priority"))
        if not 0 <= p <= 9:
            errs.append("priority out of 0..9")
    except (TypeError, ValueError):
        errs.append("priority not int")
    if fm.get("status") not in ("approved",):
        errs.append(f"status {fm.get('status')!r} not approved")
    if parse_iso(fm.get("approved_at")) is None:
        errs.append("approved_at not ISO 8601")
    try:
        int(fm.get("attempts", 0))
    except (TypeError, ValueError):
        errs.append("attempts not int")
    return fm, m.group(2), errs


def render_item(fm: dict, body: str) -> str:
    return "---\n" + dump_yaml(fm) + "---\n" + body.lstrip("\n")


def project_root_for(item_root: Path, fm: dict) -> Path:
    """Resolve an item's `project` to an absolute path INSIDE the apex.

    Every branch funnels through the one containment check — a `^/`-prefixed form is not
    a trusted shortcut. Two ways the old shape leaked, both now closed:
      - `^/^//abs/path`: joining an absolute path onto a base DISCARDS the base, so the
        prefix branches returned a path outside the apex. `.lstrip("/")` makes the
        embedded absolute a no-op instead.
      - a bare absolute path was compared to APEX *unresolved*, so a symlink inside the
        apex pointing out defeated `relative_to`. Resolve first, then compare.
    """
    p = str(fm.get("project", ".")).strip()
    if p in (".", ""):
        return item_root
    if p.startswith("^/^/"):
        root = (APEX / p[4:].lstrip("/")).resolve()
    elif p.startswith("^/"):
        root = (item_root / p[2:].lstrip("/")).resolve()
    else:
        q = Path(p)
        root = q.resolve() if q.is_absolute() else (item_root / q).resolve()
    try:
        root.relative_to(APEX.resolve())
    except ValueError:
        raise ValueError(f"project {p!r} resolves outside the apex: {root}")
    return root


def project_errors(item_root: Path, fm: dict) -> list[str]:
    """The item's project must resolve inside the apex AND be the top level of its own git repo (or the apex).
    Roots that are merely folders inside the apex repo (gitignored groups) cannot be worked: a worktree of the
    apex would not even contain their files."""
    try:
        proj = project_root_for(item_root, fm)
    except ValueError as e:
        return [str(e)]
    if not proj.is_dir():
        return [f"project dir missing: {proj}"]
    try:
        top = subprocess.run(["git", "-C", str(proj), "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return [f"project {proj}: git unavailable"]
    if not top or Path(top).resolve() != proj.resolve():
        return [f"project {proj} is not the top level of its own git repo (toplevel={top or 'none'}) — not workable"]
    return []


def pop_order(candidate: dict) -> tuple:
    fm = candidate["fm"]
    return (-int(fm["priority"]), parse_iso(fm["approved_at"]) or now_utc(), candidate["path"].name)


def list_candidates() -> tuple[list[dict], list[dict]]:
    """Scan every root's ~outbox/hb/*.md. Returns (valid, invalid)."""
    valid, invalid = [], []
    for r in roots():
        root = Path(r["abs_path"])
        box = outbox(root)
        if not box.is_dir():
            continue
        for p in sorted(box.glob("*.md")):
            if p.name.lower() == "start.md" or not p.is_file():
                continue          # a DIRECTORY named <ID>.md crashed the sweep's write_atomic
            fm, body, errs = parse_item(p)
            if not errs:
                errs += project_errors(root, fm)
            c = {"path": p, "root": root, "root_name": r["name"], "fm": fm, "body": body, "errors": errs}
            (invalid if errs else valid).append(c)
    valid.sort(key=pop_order)
    return valid, invalid


def _pidfile(inflight_path: Path) -> Path:
    return inflight_path.with_suffix(".pid")


def claim_item(c: dict, pid: int | None = None) -> Path | None:
    """Atomic move outbox -> inflight. The move IS the claim. A sidecar <ITEM>.pid (pid + start time)
    lets the sweeps recognise a live runner even after the kill switch removed GO."""
    dst = c["path"].parent / "inflight" / c["path"].name
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(c["path"], dst)
    except FileNotFoundError:
        return None
    pid = pid or os.getpid()
    write_atomic(_pidfile(dst), json.dumps({"pid": pid, "pid_start": proc_start(pid), "claimed_at": iso(now_utc())}))
    log(f"claimed item {c['fm']['id']} from {c['root_name']}")
    return dst


def item_live(inflight_path: Path) -> bool:
    try:
        d = json.loads(_pidfile(inflight_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return pid_alive(d.get("pid"), d.get("pid_start"))


def unclaim_item(inflight_path: Path, outbox_path: Path) -> None:
    """inflight -> outbox (content already rewritten by the caller if attempts changed)."""
    try:
        _pidfile(inflight_path).unlink()
    except FileNotFoundError:
        pass
    os.rename(inflight_path, outbox_path)


def requeue_or_fail(inflight_path: Path, outbox_path: Path, fm: dict, body: str, cfg: dict, item_root: Path, reason: str) -> str:
    """attempts += 1, then either back to ~outbox (retry another night) or - at attempts_max - to ~inbox as
    failed-repeatedly. The single place the threshold is applied on the runner's own return paths."""
    attempts = int(fm.get("attempts") or 0) + 1
    fm["attempts"] = attempts
    amax = int(fm.get("attempts_max") or cfg.get("attempts_max", 3))
    item_id = str(fm.get("id") or inflight_path.stem)
    if attempts >= amax:
        dst_dir = inbox(item_root) / item_id
        dst_dir.mkdir(parents=True, exist_ok=True)
        write_atomic(inflight_path, render_item(fm, body))
        shutil.move(str(inflight_path), str(dst_dir / "item.md"))
        try:
            _pidfile(inflight_path).unlink()
        except FileNotFoundError:
            pass
        write_outcome(dst_dir, {"item_id": item_id, "terminus": "failed-repeatedly", "attempts": attempts,
                                "branch": None, "pr": None, "qa_result": "n/a"},
                      f"{reason}. Attempt {attempts} of {amax}: giving up - this is a bug report, not a backlog item.")
        log(f"item {item_id}: {reason}; attempts={attempts} >= {amax} -> inbox failed-repeatedly")
        return "failed"
    write_atomic(inflight_path, render_item(fm, body))
    unclaim_item(inflight_path, outbox_path)
    log(f"item {item_id}: {reason}; attempts={attempts} -> outbox")
    return "requeued"


def finish_item(inflight_path: Path) -> None:
    for p in (_pidfile(inflight_path), inflight_path):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def orphan_sweep(cfg: dict, live_item_id: str | None = None) -> list[str]:
    """inflight/ items with no live runner: attempts+1 -> outbox, or -> inbox failed-repeatedly."""
    events = []
    for r in roots():
        root = Path(r["abs_path"])
        infl = outbox(root) / "inflight"
        if not infl.is_dir():
            continue
        for p in sorted(infl.glob("*.md")):
            if not p.is_file():
                events.append(f"orphan {p.name} @{r['name']}: not a regular file; skipped")
                continue
            fm, body, errs = parse_item(p)
            if not fm:
                # Do NOT re-render what we could not parse: render_item({}, body) replaced a full
                # frontmatter with a bare `attempts: 1`, destroying unrecoverable (gitignored)
                # metadata. Unclaim it byte-for-byte and let the runner's reject path report it.
                dst = p.parent.parent / p.name
                os.rename(p, dst)
                _pidfile(p).unlink(missing_ok=True)
                events.append(f"orphan {p.stem} @{r['name']}: unparseable, returned untouched ({'; '.join(errs)})")
                continue
            item_id = str(fm.get("id") or p.stem)
            if (live_item_id and item_id == str(live_item_id)) or item_live(p):
                continue
            attempts = int(fm.get("attempts") or 0) + 1
            fm["attempts"] = attempts
            amax = int(fm.get("attempts_max") or cfg.get("attempts_max", 3))
            if attempts >= amax:
                dst_dir = inbox(root) / item_id
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dst_dir / "item.md"))
                try:
                    _pidfile(p).unlink()
                except FileNotFoundError:
                    pass
                write_outcome(dst_dir, {"item_id": item_id, "terminus": "failed-repeatedly", "attempts": attempts,
                                        "branch": None, "pr": None, "qa_result": "n/a"},
                              f"Orphaned {attempts} times (attempts_max {amax}). This is a bug report, not a backlog item.")
                events.append(f"orphan {item_id} @{r['name']}: attempts={attempts} >= {amax} -> inbox failed-repeatedly")
            else:
                back = p.parent.parent / p.name
                write_atomic(p, render_item(fm, body))
                unclaim_item(p, back)
                events.append(f"orphan {item_id} @{r['name']}: attempts={attempts} -> outbox")
    for e in events:
        log(e)
    return events


def write_outcome(dst_dir: Path, fields: dict, summary: str) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    fields = {"written_at": iso(now_utc()), **fields}
    out = dst_dir / "outcome.md"
    write_atomic(out, "---\n" + dump_yaml(fields) + "---\n\n" + summary.rstrip() + "\n")
    return out


# ── approve ──────────────────────────────────────────────────────────

def backlog_section(root: Path, item_id: str) -> str | None:
    bl = root / ".state" / "work" / "backlog.md"
    try:
        text = bl.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(rf"^###\s+{re.escape(item_id)}\b.*?(?=^###\s|\Z)", text, re.S | re.M)
    return m.group(0).rstrip() + "\n" if m else None


def approve(item_id: str, project: str | None, priority: int | None, model: str | None,
            body_file: str | None, cfg: dict) -> Path:
    root = Path(project).resolve() if project else APEX
    if not (root / "CLAUDE.md").exists():
        raise SystemExit(f"not a project root: {root}")
    dst = outbox(root) / f"{item_id}.md"
    if dst.exists() or (outbox(root) / "inflight" / f"{item_id}.md").exists():
        raise SystemExit(f"already queued: {dst}")
    if not ID_RE.match(item_id):
        raise SystemExit(f"invalid id {item_id!r}: must match {ID_RE.pattern}")
    if priority is not None:
        try:
            if not 0 <= int(priority) <= 9:
                raise ValueError
        except ValueError:
            raise SystemExit("--priority must be an integer 0..9")
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8")
    else:
        body = backlog_section(root, item_id)
        if body is None:
            raise SystemExit(f"{item_id} not found in {root}/.state/work/backlog.md — pass --body FILE")
    who = os.environ.get("HB_APPROVED_BY")
    if not who:
        try:
            who = subprocess.run(["git", "-C", str(root), "config", "user.name"], capture_output=True,
                                 text=True, check=False).stdout.strip()
        except OSError:
            who = ""
    who = who or os.environ.get("USER", "unknown")
    fm = {"id": item_id, "recipient": RECIPIENT, "sender": root.name if root != APEX else "claudette",
          "project": ".", "priority": 5 if priority is None else int(priority), "status": "approved",
          "approved_by": who, "approved_at": iso(now_utc()),
          "source": f".state/work/backlog.md#{item_id}", "attempts": 0,
          "attempts_max": cfg.get("attempts_max", 3), "model": model or cfg.get("model", "sonnet"),
          "time_cap_min": cfg.get("item_cap_min", 90), "qa": cfg.get("qa", "mileqa"), "pr": cfg.get("pr", True),
          "base": None, "scope": [], "depends_on": [], "tags": []}
    dst.parent.mkdir(parents=True, exist_ok=True)
    (dst.parent / "inflight").mkdir(exist_ok=True)
    write_atomic(dst, render_item(fm, body))
    log(f"approved {item_id} -> {dst}")
    return dst


# ── window detector ──────────────────────────────────────────────────

def compute_close(cfg: dict) -> datetime:
    """Next occurrence of window.close after now (local wall clock)."""
    close = local_today_at(cfg["window"]["close"])
    if close <= datetime.now().astimezone():
        close = local_today_at(cfg["window"]["close"], 1)
    return close


def in_window(cfg: dict, now: datetime | None = None) -> bool:
    """True iff local wall-clock is inside [open, close) — handles overnight windows (open > close)."""
    now = (now or datetime.now().astimezone()).astimezone()
    o = local_today_at(cfg["window"]["open"]).timetz().replace(tzinfo=None)
    c = local_today_at(cfg["window"]["close"]).timetz().replace(tzinfo=None)
    tnow = now.timetz().replace(tzinfo=None)
    if o <= c:
        return o <= tnow < c
    return tnow >= o or tnow < c


def window_open(cfg: dict, force: bool = False) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    d = read_flag()
    if d and d.get("status") == "inflight":
        if flag_alive(d):
            log(f"ERROR open: runner pid {d.get('pid')} still alive on {d.get('item_id')} — refusing to re-arm over a live run")
            return
        corpse(d, cfg)
    if not force and not in_window(cfg):
        msg = f"open: {datetime.now().astimezone():%H:%M} is outside the window {cfg['window']['open']}–{cfg['window']['close']}; not issuing GO (late/replayed trigger). Use `hb.py window open --force` to arm by hand."
        log("WARN " + msg)
        print(msg, file=sys.stderr)
        return
    events = orphan_sweep(cfg)
    prune_worktrees()
    closes = compute_close(cfg)
    issue_flag(closes)
    # A replayed/duplicate open inside an already-open night must NOT reset the ledger: doing
    # so wiped runs[] (losing every terminus and PR link from the morning summary) and reset
    # the count_cap gate, licensing another cap's worth of unattended runs. `window_close` and
    # `run_once` both already carry the equivalent guard; this one was the asymmetry.
    n = read_night()
    if n.get("night") == night_key(closes) and not n.get("closed"):
        n["closes_at"] = iso(closes)
        n.setdefault("notes", []).extend(
            ["re-open of an already-open night (replayed trigger); ledger preserved"] + events)
        write_night(n)
    else:
        write_night({"night": night_key(closes), "opened_at": iso(now_utc()), "closes_at": iso(closes),
                     "count_cap": cfg.get("count_cap"), "runs": [],
                     "notes": [f"open: {len(events)} orphan events"] + events})


def window_close(cfg: dict) -> None:
    n = read_night()
    if n.get("night") != night_key():
        # no open recorded for tonight (machine off / trigger missed): still produce tonight's file
        write_night({"night": night_key(), "opened_at": None, "closes_at": None, "count_cap": cfg.get("count_cap"),
                     "runs": [], "notes": [f"close without a recorded open (previous night.json: {n.get('night')})"]})
    d = read_flag()
    live_id = None
    if d is None:
        log("close: GO absent (normal)")
    elif d.get("status") == "go":
        closes = parse_iso(d.get("window_closes_at"))
        if closes and now_utc() < closes - timedelta(minutes=10) and in_window(cfg):
            # a late/replayed close must not revoke a fresh window's token
            log(f"WARN close: flag belongs to a window closing at {d.get('window_closes_at')} (still open) — leaving it")
            return
        remove_flag("window close, quiet night end")
    elif d.get("status") == "inflight":
        if flag_alive(d):
            # D7: never kill mid-item. Log loudly, leave the flag; the runner releases it and the
            # next tick removes an expired `go`.
            live_id = d.get("item_id")
            log(f"WARN close: runner pid {d.get('pid')} still alive on {live_id} — letting it finish (overrun)")
            night_note(f"OVERRUN: pid {d.get('pid')} item {live_id} alive at close")
        else:
            corpse(d, cfg)
            remove_flag("window close after corpse sweep")
    else:
        log(f"ERROR close: GO in unknown state {d!r}; removing")
        remove_flag("window close, corrupt flag")
    events = orphan_sweep(cfg, live_item_id=live_id)
    n = read_night()
    if events:
        n.setdefault("notes", []).extend(events)
    n["closed"] = True
    write_night(n)
    write_summary(cfg)


def corpse(d: dict, cfg: dict) -> None:
    """Dead PID on an inflight flag: LOUD. Distinct message type in the morning inbox."""
    rec = {"kind": "corpse", "at": iso(now_utc()), "pid": d.get("pid"), "claimed_at": d.get("claimed_at"),
           "transcript_path": d.get("transcript_path"),
           "died_before_session_boot": d.get("transcript_path") is None,
           "item_id": d.get("item_id")}
    DIAG.mkdir(parents=True, exist_ok=True)
    write_atomic(DIAG / f"{now_utc().strftime('%Y%m%dT%H%M%SZ')}-corpse-{d.get('item_id') or 'noitem'}.json",
                 json.dumps(rec, indent=2))
    log(f"CORPSE: {json.dumps(rec)}")
    n = read_night(); n.setdefault("corpses", []).append(rec); write_night(n)


def prune_worktrees() -> None:
    try:
        subprocess.run(["git", "-C", str(APEX), "worktree", "prune"], capture_output=True, check=False)
    except OSError:
        pass


def stale_branches(cfg: dict) -> list[str]:
    days = int(cfg.get("stale_branch_days", 5))
    try:
        out = subprocess.run(["git", "-C", str(APEX), "for-each-ref", "--format=%(refname:short) %(committerdate:unix)",
                              f"refs/heads/{cfg.get('branch_prefix', 'hb/')}"],
                             capture_output=True, text=True, check=False).stdout
    except OSError:
        return []
    cutoff = time.time() - days * 86400
    res = []
    for line in out.splitlines():
        try:
            name, ts = line.rsplit(" ", 1)
            if float(ts) < cutoff:
                res.append(name)
        except ValueError:
            continue
    return res


def read_quota() -> dict:
    try:
        return json.loads(QUOTA.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_summary(cfg: dict) -> Path:
    """Always written at close: the positive 'ran and did nothing' signal (spec O5)."""
    n = read_night()
    key = n.get("night") or night_key()
    dst_dir = inbox(APEX)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"night-{key}.md"
    runs = n.get("runs", [])
    q = read_quota()
    lt = (STATE / "last-tick").read_text().strip() if (STATE / "last-tick").exists() else "never"
    lines = [f"# Heartbeat night {key}", "",
             f"- opened: {n.get('opened_at', '—')}  closes: {n.get('closes_at', '—')}  count_cap: {n.get('count_cap', cfg.get('count_cap'))}  last tick: {lt}",
             f"- runs: {len(runs)}   corpses: {len(n.get('corpses', []))}",
             f"- quota reading (last statusLine write): {json.dumps(q.get('rate_limits')) if q else 'none'} @ {q.get('written_at', '—') if q else '—'}",
             ""]
    if runs:
        lines += ["| item | root | terminus | qa | branch | pushed | pr | min | cost |", "|---|---|---|---|---|---|---|---|---|"]
        for r in runs:
            lines.append(f"| {r.get('item_id')} | {r.get('root_name')} | {r.get('terminus')} | {r.get('qa_result')} | "
                         f"{r.get('branch')} | {r.get('pushed')} | {r.get('pr') or '—'} | {r.get('duration_min')} | {r.get('cost_usd')} |")
        lines.append("")
    else:
        lines += ["No items ran tonight.", ""]
    for c in n.get("corpses", []):
        lines.append(f"- **CORPSE** pid {c.get('pid')} item {c.get('item_id')} claimed {c.get('claimed_at')} "
                     f"{'(died before session boot)' if c.get('died_before_session_boot') else ''}")
    sb = stale_branches(cfg)
    if sb:
        lines += ["", f"Stale `{cfg.get('branch_prefix','hb/')}*` branches (> {cfg.get('stale_branch_days',5)}d, unmerged/unreviewed?):"] + [f"- {b}" for b in sb]
    notes = n.get("notes", [])
    if notes:
        lines += ["", "Notes:"] + [f"- {x}" for x in notes]
    write_atomic(dst, "\n".join(lines) + "\n")
    log(f"summary written {dst}")
    return dst


# ── tick ─────────────────────────────────────────────────────────────

def touch_last_tick() -> None:
    """Proof the schedule runs (spec O5): a timestamp, not a log line, so quiet ticks stay quiet."""
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        write_atomic(STATE / "last-tick", iso(now_utc()) + "\n")
    except OSError:
        pass


def keepalive(cfg: dict) -> None:
    """GO-independent DB keep-awake ping. Majel's live Supabase project (A/Archivist) is free-tier and
    pauses after ~7 days idle; a nightly read-only `SELECT 1` (via the configured command) keeps it awake.

    Runs at the TOP of every tick, BEFORE the GO/window/quota gates, so `rm GO` does NOT stop it (that is
    the point — the DB must stay awake even when backlog automation is disarmed). At most one attempt per
    night (guarded by KEEPALIVE_STAMP); the attempt is stamped up front so an unreachable/paused A does not
    re-hammer every 5-minute tick. The stamp records the OUTCOME (`<night> ok|FAILED`) so `hb status` surfaces
    a misconfigured or failing ping instead of it failing silently until A pauses. Off switch:
    cfg["keepalive"].enabled=false, or `touch state/NO-KEEPALIVE`. Never raises — a keep-alive problem must
    never disturb the tick. NOTE: a data ping keeps A from pausing; it cannot un-pause an already-paused
    project (that is a manual dashboard/management-API restore)."""
    ka = cfg.get("keepalive") or {}
    cmd = ka.get("command")
    if not ka.get("enabled") or not cmd or NO_KEEPALIVE.exists():
        return
    tonight = night_key()
    try:
        # errors="replace": a corrupt (non-UTF-8) stamp must never raise here — keepalive() must NOT crash the
        # tick (it is called before every gate). Garbage won't equal tonight, so the next line re-stamps clean.
        prev = KEEPALIVE_STAMP.read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        prev = []
    if prev[:1] == [tonight]:
        return                              # already attempted this night (any outcome) — bounded 1/night

    def _stamp(outcome: str) -> None:
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            write_atomic(KEEPALIVE_STAMP, f"{tonight} {outcome}\n")
        except OSError:
            pass

    _stamp("attempt")                       # stamp before running so a hard kill can't re-hammer; outcome overwrites it
    try:
        timeout_s = int(ka.get("timeout_s") or 20)     # tolerate null / bad config without a TypeError
        if timeout_s <= 0:
            timeout_s = 20
    except (TypeError, ValueError):
        timeout_s = 20
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        if r.returncode == 0:
            _stamp("ok"); log(f"keepalive: ok — {(r.stdout or '').strip()[:160]}")
        else:
            _stamp("FAILED"); log(f"keepalive: FAILED rc={r.returncode} — {(r.stderr or r.stdout or '').strip()[:200]}")
    except subprocess.TimeoutExpired:
        _stamp("FAILED"); log(f"keepalive: timed out after {timeout_s}s")
    except Exception as e:
        _stamp("FAILED"); log(f"keepalive: error {e!r}")


def tick(cfg: dict, reap: bool = False, ignore_count_cap: bool = False) -> int:
    """Reads the flag and nothing else. Quiet when absent.

    `reap` (session/loop mode): first reap a DEAD inflight corpse. The scheduler defers reaping to
    window_close, but no-scheduler run/loop have no window_close, so they must self-heal or one crash wedges
    HB. `ignore_count_cap` lets a deliberate `hb run` process one item past the scheduler's per-night cap.
    Both default off so the scheduler's `tick` behavior is byte-for-byte unchanged."""
    touch_last_tick()
    keepalive(cfg)          # GO-independent DB keep-awake — before every gate; `rm GO` does not stop it
    if reap:
        reap_dead_inflight(cfg)
    d = read_flag()
    if d is None:
        return 0
    status = d.get("status")
    if status == "inflight":
        if flag_alive(d):
            return 0
        log(f"WARN tick: dead pid {d.get('pid')} on inflight flag (item {d.get('item_id')}); leaving for close sweep")
        return 0
    if status != "go":
        log(f"WARN tick: GO in unexpected state {status!r}; ignoring")
        return 0
    closes = parse_iso(d.get("window_closes_at"))
    now = now_utc()
    if closes and now >= closes:
        remove_flag("expired past window_closes_at")
        return 0
    n = read_night()
    cap = int(cfg.get("count_cap", 1))
    if not ignore_count_cap and len(n.get("runs", [])) >= cap:
        if not n.get("cap_logged"):
            log(f"count cap {cap} reached; not spawning again tonight")
            n["cap_logged"] = True; write_night(n)
        return 0
    item_cap = int(cfg.get("item_cap_min", 90))
    if closes and now + timedelta(minutes=item_cap) > closes:
        if not n.get("near_close_logged"):
            log(f"within {item_cap}m of close; not spawning")
            n["near_close_logged"] = True; write_night(n)
        return 0
    claim = claim_flag()
    if claim is None:
        return 0
    # In-process: the tick IS the runner for the duration of one item (D6).
    import runner  # noqa: WPS433 (sibling module)
    try:
        entry = runner.run(claim, cfg)
    except Exception as e:
        # Our own crash is an UNEXPECTED terminus (spec §10.2 "anything else → leave corpse"): record it as a
        # run (so count_cap holds), write the diag, and leave GO inflight — the close sweep logs the corpse and
        # the orphan sweep returns the item. Do NOT release: relaunching into an unknown failure all night is
        # exactly what §7.2 forbids.
        log(f"ERROR runner crashed: {e!r}; leaving GO inflight for the sweep")
        DIAG.mkdir(parents=True, exist_ok=True)
        write_atomic(DIAG / f"{now_utc().strftime('%Y%m%dT%H%M%SZ')}-runner-crash.json",
                     json.dumps({"kind": "runner-crash", "error": repr(e), "claim": claim}, indent=2, default=str))
        night_add_run({"item_id": (read_flag() or {}).get("item_id"), "terminus": "crash", "qa_result": "n/a",
                       "error": repr(e), "finished_at": iso(now_utc())})
        raise
    if entry:
        night_add_run(entry)
        if read_night().get("closed"):
            write_summary(cfg)          # the overrun finished after close: refresh the morning file
    return 0


# ── session-driven drivers (no scheduler): run / loop ────────────────
#   Apex-only (require_apex). These let you drive HB from a session without native Task Scheduler.
#   `run`  = one deliberate item now.  `loop` = a detached background ticker (keep-alive + run-if-armed).
#   NON-PERSISTENT: a loop survives the terminal closing but dies on reboot/shutdown/WSL-down and never
#   self-restarts — it is a while-you-work driver, not the unattended nightly scheduler.

def reap_dead_inflight(cfg: dict) -> bool:
    """If GO is inflight with a DEAD pid, reap it in-band: record the corpse, return the item to the queue
    (orphan_sweep, honoring attempts_max), and clear GO. The scheduler defers this to window_close; the
    session drivers (run/loop) have no window_close, so without this one worker crash wedges HB — `hb run`
    would refuse forever on the stale inflight and the loop would idle. Returns True iff it reaped."""
    d = read_flag()
    if not d or d.get("status") != "inflight" or flag_alive(d):
        return False
    log(f"reap: dead pid {d.get('pid')} on inflight flag (item {d.get('item_id')}); sweeping (session-driven)")
    corpse(d, cfg)
    orphan_sweep(cfg)
    remove_flag("reaped dead inflight corpse (session-driven)")
    return True


def run_once(cfg: dict) -> int:
    """Manual one-shot. Self-heals first (reap a dead inflight corpse), then: if GO is absent, arm a
    windowless one-item budget and process exactly ONE item — past the scheduler's per-night count_cap, since
    this is a deliberate user action — then release. If a REAL window is already armed, advance its queue by
    one item under its own cap (no ledger reset, no override). Refuses only over a LIVE inflight run. Prints
    what it did so a no-op is never silent."""
    reap_dead_inflight(cfg)
    d = read_flag()
    if d is not None and d.get("status") == "inflight":        # survived the reap ⇒ a LIVE run
        print(f"hb run: a run is already in flight (item {d.get('item_id')}); refusing to double-arm", file=sys.stderr)
        return 1
    armed_here = d is None
    if armed_here:
        item_cap = int(cfg.get("item_cap_min", 90))
        issue_flag(now_utc() + timedelta(minutes=item_cap + 5))   # one item + margin, so tick's near-close passes
        if read_night().get("night") != night_key():
            # only start a fresh ledger when none exists for tonight; never clobber a scheduled window's
            # record (its runs/corpses feed the morning summary)
            write_night({"night": night_key(), "opened_at": iso(now_utc()), "closes_at": None,
                         "count_cap": cfg.get("count_cap"), "runs": [], "notes": ["manual `hb run` one-shot"]})
        log("hb run: armed a windowless one-shot")
    before = len(read_night().get("runs", []))
    crashed = False
    try:
        tick(cfg, ignore_count_cap=armed_here)     # a deliberate manual run bypasses the scheduler's night cap
    except Exception as e:
        crashed = True
        print(f"hb run: the item crashed ({e!r}); left as a corpse — re-run `hb run` to reap and retry", file=sys.stderr)
    finally:
        if armed_here and (read_flag() or {}).get("status") != "inflight":
            remove_flag("hb run one-shot complete")     # leave an inflight corpse for the next reap, else clear
    if crashed:
        return 1
    if (read_flag() or {}).get("status") == "inflight":
        # the runner returned an UNEXPECTED terminus and left GO inflight (a corpse) — armed or real-window,
        # report it honestly with a non-zero exit, mirroring the crash path, so a `$?`-checking caller is
        # never told it succeeded
        print("hb run: the item ended abnormally and was left as a corpse — re-run `hb run` to reap and retry",
              file=sys.stderr)
        return 1
    if len(read_night().get("runs", [])) > before:
        print("hb run: ran 1 item — see its terminus in ~inbox/hb/<ID>/outcome.md")
    else:
        print("hb run: no item processed (queue empty, quota exhausted, or — with a window already armed — count cap reached)")
    return 0


def read_loop() -> dict:
    try:
        return json.loads(LOOP_STATE.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def loop_alive(d: dict | None) -> bool:
    return bool(d) and pid_alive(d.get("pid"), d.get("pid_start"))


def loop_start(cfg: dict, interval_s: int) -> int:
    """Spawn a detached background ticker: `hb.py tick` every interval_s, in its own session (survives the
    terminal closing). Records pid/interval in LOOP_STATE. Refuses if one is already live."""
    d = read_loop()
    if loop_alive(d):
        print(f"hb loop: already running (pid {d.get('pid')}, every {d.get('interval_s')}s since {d.get('started_at')})",
              file=sys.stderr)
        return 1
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # $1=python $2=hb.py $3=logfile $4=interval — passed as argv to avoid quoting the paths into the script.
    # `tick --reap` (not bare tick): with no window_close in this mode, the loop must self-heal a dead
    # inflight corpse each tick, else one crash idles it permanently.
    script = 'while true; do "$1" "$2" tick --reap >> "$3" 2>&1; sleep "$4"; done'
    proc = subprocess.Popen(
        ["bash", "-c", script, "hb-loop", sys.executable, str(HB / "hb.py"), str(LOOP_LOG), str(interval_s)],
        cwd=str(APEX), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, env=dict(os.environ),
    )
    if hasattr(proc, "_child_created"):
        proc._child_created = False   # fire-and-forget daemon: tracked by pid, not this Popen — silence the finalizer warning (best-effort across CPython versions)
    write_atomic(LOOP_STATE, json.dumps(
        {"pid": proc.pid, "pid_start": proc_start(proc.pid), "interval_s": interval_s,
         "started_at": iso(now_utc())}, indent=2))
    log(f"hb loop: started pid {proc.pid}, every {interval_s}s")
    print(f"hb loop: started (pid {proc.pid}) — `hb.py tick` every {interval_s}s. Stop: `hb.py loop stop`.\n"
          f"  NON-PERSISTENT: survives the terminal closing, but dies on reboot/shutdown and never self-restarts.")
    return 0


def loop_stop() -> int:
    d = read_loop()
    if not loop_alive(d):
        LOOP_STATE.unlink(missing_ok=True)
        print("hb loop: not running")
        return 0
    pid = int(d["pid"])
    f = read_flag()
    if f and f.get("status") == "inflight" and flag_alive(f):
        # loop_stop is a hard stop (unlike `rm GO`, which lets a worker finish): warn that an in-flight item
        # will be interrupted and left as a reapable corpse (the next `hb run`/loop tick --reap reclaims it).
        print(f"hb loop: WARNING an item is in flight (item {f.get('item_id')}, pid {f.get('pid')}); stopping the "
              f"loop now interrupts it and leaves a reapable corpse (the next `hb run` reclaims it). To let an "
              f"in-flight item finish, prefer `rm GO` over `loop stop`.", file=sys.stderr)
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)   # the whole session group (bash loop + any child tick)
    except (ProcessLookupError, PermissionError) as e:
        log(f"hb loop: stop signal failed for pid {pid}: {e!r}")
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    LOOP_STATE.unlink(missing_ok=True)
    log(f"hb loop: stopped pid {pid}")
    print(f"hb loop: stopped (pid {pid})")
    return 0


def loop_status() -> str:
    d = read_loop()
    if loop_alive(d):
        return (f"loop: running (pid {d.get('pid')}) — `tick` every {d.get('interval_s')}s "
                f"since {d.get('started_at')}")
    if d:
        return f"loop: not running (stale record pid {d.get('pid')}); `loop stop` clears it"
    return "loop: not running"


# ── status / kill ────────────────────────────────────────────────────

def status(cfg: dict) -> str:
    d = read_flag()
    lines = [f"GO: {json.dumps(d, default=str) if d else 'absent'}"]
    n = read_night()
    if n:
        lines.append(f"night {n.get('night')}: runs={len(n.get('runs', []))} cap={n.get('count_cap')} closes={n.get('closes_at')}")
    valid, invalid = list_candidates()
    lines.append(f"queue: {len(valid)} valid, {len(invalid)} invalid")
    for c in valid:
        lines.append(f"  [{c['fm']['priority']}] {c['fm']['id']} @{c['root_name']} attempts={c['fm'].get('attempts')}")
    for c in invalid:
        lines.append(f"  INVALID {c['path']}: {'; '.join(c['errors'])}")
    for r in roots():
        infl = outbox(Path(r["abs_path"])) / "inflight"
        if infl.is_dir():
            for p in infl.glob("*.md"):
                lines.append(f"  inflight {p.stem} @{r['name']}")
    q = read_quota()
    lines.append(f"quota: {json.dumps(q.get('rate_limits')) if q else 'none'} @ {q.get('written_at') if q else '—'}")
    try:
        ks = KEEPALIVE_STAMP.read_text(encoding="utf-8", errors="replace").split()   # never crash status on a corrupt stamp
        if ks:
            lines.append(f"keepalive: last {ks[0]} {ks[1] if len(ks) > 1 else '?'}")
    except OSError:
        pass
    lines.append(loop_status())
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cfg = load_config()
    cmd, rest = argv[0], argv[1:]
    if cmd == "tick":
        return tick(cfg, reap="--reap" in rest)
    if cmd == "run":
        require_apex("run")
        return run_once(cfg)
    if cmd == "loop":
        require_apex("loop")
        sub = rest[0] if rest else "status"
        if sub == "start":
            interval = cfg.get("loop_interval_s", 3600)     # config default OR --interval — both floored below
            if "--interval" in rest:
                j = rest.index("--interval")
                interval = rest[j + 1] if j + 1 < len(rest) else None
            try:
                interval = max(60, int(interval))            # floor 60s on BOTH paths: guard a runaway tight loop
            except (TypeError, ValueError):
                print("usage: hb.py loop start [--interval SECONDS]  (needs a positive integer; "
                      "check config loop_interval_s)", file=sys.stderr); return 2
            return loop_start(cfg, interval)
        if sub == "stop":
            return loop_stop()
        if sub == "status":
            print(loop_status()); return 0
        print("usage: hb.py loop start [--interval SECONDS] | stop | status", file=sys.stderr); return 2
    if cmd == "window":
        if rest[:1] == ["open"]:
            window_open(cfg, force="--force" in rest); return 0
        if rest[:1] == ["close"]:
            window_close(cfg); return 0
        print("usage: hb.py window open|close", file=sys.stderr); return 2
    if cmd == "install":
        for line in install(dry_run="--dry-run" in rest):
            print(line)
        return 0
    if cmd == "approve":
        if not rest:
            print("usage: hb.py approve <ID> [--project P] [--priority N] [--model M] [--body FILE]", file=sys.stderr); return 2
        opts = {}
        i = 1
        while i < len(rest):
            if rest[i] in ("--project", "--priority", "--model", "--body") and i + 1 < len(rest):
                opts[rest[i][2:]] = rest[i + 1]; i += 2
            else:
                i += 1
        p = approve(rest[0], opts.get("project"), opts.get("priority"), opts.get("model"), opts.get("body"), cfg)
        print(p)
        return 0
    if cmd == "status":
        print(status(cfg)); return 0
    if cmd == "kill":
        remove_flag("kill switch via hb.py kill"); print("GO removed" if not GO.exists() else "GO still present?!"); return 0
    if cmd == "summary":
        print(write_summary(cfg)); return 0
    print(f"unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
