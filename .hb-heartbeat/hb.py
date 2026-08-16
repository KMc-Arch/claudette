#!/usr/bin/env python3
"""Heartbeat (HB) — nightly unattended backlog execution for claudette.

    KILL SWITCH:  rm .hb-heartbeat/state/GO      (everything stops at the next tick)

Deterministic control plane. No model call happens in this file. The only process
that ever talks to a model is the *worker* spawned by runner.py — inside a sandbox
worktree, hard-rooted there, and it never touches the GO flag or the queues.

CLI:
    hb.py tick                      # Task Scheduler, every N min: read GO; maybe claim + run one item (in-process)
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


def pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


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
        text = GO.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
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
        d = yaml.safe_load(tmp.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        d = {}
    if not isinstance(d, dict) or d.get("status") != "go":
        # not ours to claim — put it back untouched
        os.rename(tmp, GO)
        return None
    d.update({"status": "inflight", "claimed_at": iso(now_utc()), "pid": pid,
              "transcript_path": None, "item_id": None})
    tmp.write_text(dump_yaml(d), encoding="utf-8")
    os.rename(tmp, GO)
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


# ── night ledger ─────────────────────────────────────────────────────

def read_night() -> dict:
    try:
        return json.loads(NIGHT.read_text(encoding="utf-8"))
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


def parse_item(path: Path) -> tuple[dict, str, list[str]]:
    """Return (frontmatter, body, errors). Never guesses: errors are fatal for pop."""
    errs = []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as e:
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
    if fm.get("id") and path.stem != str(fm["id"]):
        errs.append(f"filename {path.name} != id {fm['id']}.md")
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
    p = str(fm.get("project", ".")).strip()
    if p in (".", ""):
        return item_root
    if p.startswith("^/^/"):
        return (APEX / p[4:]).resolve()
    if p.startswith("^/"):
        return (item_root / p[2:]).resolve()
    q = Path(p)
    return q if q.is_absolute() else (item_root / q).resolve()


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
            if p.name == "start.md":
                continue
            fm, body, errs = parse_item(p)
            c = {"path": p, "root": root, "root_name": r["name"], "fm": fm, "body": body, "errors": errs}
            (invalid if errs else valid).append(c)
    valid.sort(key=pop_order)
    return valid, invalid


def claim_item(c: dict) -> Path | None:
    """Atomic move outbox -> inflight. The move IS the claim."""
    dst = c["path"].parent / "inflight" / c["path"].name
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(c["path"], dst)
    except FileNotFoundError:
        return None
    log(f"claimed item {c['fm']['id']} from {c['root_name']}")
    return dst


def orphan_sweep(cfg: dict, live_item_id: str | None = None) -> list[str]:
    """inflight/ items with no live runner: attempts+1 -> outbox, or -> inbox failed-repeatedly."""
    events = []
    for r in roots():
        root = Path(r["abs_path"])
        infl = outbox(root) / "inflight"
        if not infl.is_dir():
            continue
        for p in sorted(infl.glob("*.md")):
            fm, body, errs = parse_item(p)
            item_id = fm.get("id") or p.stem
            if live_item_id and item_id == live_item_id:
                continue
            attempts = int(fm.get("attempts") or 0) + 1
            fm["attempts"] = attempts
            amax = int(fm.get("attempts_max") or cfg.get("attempts_max", 3))
            if attempts >= amax:
                dst_dir = inbox(root) / item_id
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dst_dir / "item.md"))
                write_outcome(dst_dir, {"item_id": item_id, "terminus": "failed-repeatedly", "attempts": attempts,
                                        "branch": None, "pr": None, "qa_result": "n/a"},
                              f"Orphaned {attempts} times (attempts_max {amax}). This is a bug report, not a backlog item.")
                events.append(f"orphan {item_id} @{r['name']}: attempts={attempts} >= {amax} -> inbox failed-repeatedly")
            else:
                back = p.parent.parent / p.name
                write_atomic(p, render_item(fm, body))
                os.rename(p, back)
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


def window_open(cfg: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    events = orphan_sweep(cfg)
    prune_worktrees()
    closes = compute_close(cfg)
    issue_flag(closes)
    write_night({"night": night_key(closes), "opened_at": iso(now_utc()), "closes_at": iso(closes),
                 "count_cap": cfg.get("count_cap"), "runs": [], "notes": [f"open: {len(events)} orphan events"] + events})


def window_close(cfg: dict) -> None:
    d = read_flag()
    live_id = None
    if d is None:
        log("close: GO absent (normal)")
    elif d.get("status") == "go":
        remove_flag("window close, quiet night end")
    elif d.get("status") == "inflight":
        if pid_alive(d.get("pid")):
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
    if events:
        n = read_night(); n.setdefault("notes", []).extend(events); write_night(n)
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
        return json.loads(QUOTA.read_text(encoding="utf-8"))
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
    lines = [f"# Heartbeat night {key}", "",
             f"- opened: {n.get('opened_at', '—')}  closes: {n.get('closes_at', '—')}  count_cap: {n.get('count_cap', cfg.get('count_cap'))}",
             f"- runs: {len(runs)}   corpses: {len(n.get('corpses', []))}",
             f"- quota reading (last statusLine write): {json.dumps(q.get('rate_limits')) if q else 'none'} @ {q.get('written_at', '—') if q else '—'}",
             ""]
    if runs:
        lines += ["| item | root | terminus | qa | branch | pr | min | cost |", "|---|---|---|---|---|---|---|---|"]
        for r in runs:
            lines.append(f"| {r.get('item_id')} | {r.get('root_name')} | {r.get('terminus')} | {r.get('qa_result')} | "
                         f"{r.get('branch')} | {r.get('pr') or '—'} | {r.get('duration_min')} | {r.get('cost_usd')} |")
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

def tick(cfg: dict) -> int:
    """Reads the flag and nothing else. Quiet when absent."""
    d = read_flag()
    if d is None:
        return 0
    status = d.get("status")
    if status == "inflight":
        if pid_alive(d.get("pid")):
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
    if len(n.get("runs", [])) >= cap:
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
    except Exception as e:  # last-resort: never leave the flag inflight on our own crash
        log(f"ERROR runner crashed: {e!r}")
        DIAG.mkdir(parents=True, exist_ok=True)
        write_atomic(DIAG / f"{now_utc().strftime('%Y%m%dT%H%M%SZ')}-runner-crash.json",
                     json.dumps({"kind": "runner-crash", "error": repr(e), "claim": claim}, indent=2, default=str))
        release_flag(os.getpid(), "go")
        raise
    if entry:
        night_add_run(entry)
    return 0


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
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cfg = load_config()
    cmd, rest = argv[0], argv[1:]
    if cmd == "tick":
        return tick(cfg)
    if cmd == "window":
        if rest[:1] == ["open"]:
            window_open(cfg); return 0
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
