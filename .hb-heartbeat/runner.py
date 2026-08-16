#!/usr/bin/env python3
"""Heartbeat runner — the deterministic half of one nightly item.

Called in-process by `hb.py tick` after the tick has atomically claimed GO.
Sequence (spec §10.1, split per plan D1):

    quota gate -> pop one approved item (atomic move to inflight/) -> annotate GO
    -> provision sandbox worktree -> spawn WORKER (headless claude, hard-rooted in the sandbox,
       via cboot.py --project SANDBOX --exec-file PROMPT) -> harvest RESULT -> write ~inbox outcome
    -> remove worktree (branch stays) -> release GO (inflight -> go | absent)

The worker never touches GO, the queues, or the live ~inbox. Its only outputs are its
branch (+ optional PR) and RESULT/ inside its own sandbox, which this file harvests.

Standalone dry use (no flag, no spawn):  python3 runner.py --dry-run
Fake worker for tests:                    HB_WORKER_CMD="python3 tests/fake_worker.py" (receives SANDBOX PROMPT_FILE argv)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import hb  # sibling

RESULT_REL = Path(".hb-heartbeat") / "state" / "RESULT"
QUOTA_HINT = re.compile(r"rate.?limit|usage.?limit|quota|out of (extra )?usage|429|overloaded", re.I)

SANDBOX_DENY = [
    "Bash(gh pr merge:*)", "Bash(gh pr close:*)", "Bash(gh pr ready:*)", "Bash(gh repo:*)",
    "Bash(git update-ref:*)", "Bash(git worktree:*)", "Bash(git branch -D:*)", "Bash(git branch -f:*)",
    "Bash(git branch --force:*)", "Bash(git checkout main:*)", "Bash(git switch main:*)",
]


# ── helpers ──────────────────────────────────────────────────────────

def _git(root: Path, *args, check=False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def _env() -> dict:
    env = dict(os.environ)
    cfg = hb.load_config()
    extra = [p for p in cfg.get("extra_path", []) if p]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def branch_name(cfg: dict, root: Path, item_id: str) -> str:
    prefix = cfg.get("branch_prefix", "hb/")
    if root.resolve() == hb.APEX.resolve():
        return f"{prefix}{item_id}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-").lower()
    return f"{prefix}{slug}/{item_id}"


def transcript_path_for(sandbox: Path, session_id: str | None) -> str | None:
    if not session_id:
        return None
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(sandbox))
    p = Path.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl"
    return str(p)


def diag(kind: str, payload: dict) -> Path:
    """Dumb file write, no model call (spec §11.3)."""
    hb.DIAG.mkdir(parents=True, exist_ok=True)
    p = hb.DIAG / f"{hb.now_utc().strftime('%Y%m%dT%H%M%SZ')}-{kind}-{payload.get('item_id') or 'noitem'}.json"
    hb.write_atomic(p, json.dumps({"kind": kind, "at": hb.iso(hb.now_utc()), **payload}, indent=2, default=str))
    hb.log(f"DIAG {kind}: {p.name}")
    return p


# ── quota gate ───────────────────────────────────────────────────────

def quota_gate(cfg: dict) -> tuple[bool, str, dict]:
    """Returns (ok, reason, reading). Stale-by-nature in v1 (statusLine sink; see plan D5)."""
    q = cfg.get("quota", {})
    reading = hb.read_quota()
    if not reading:
        ok = q.get("missing_policy", "allow") == "allow"
        return ok, "quota.json missing" + (" (allowed by policy)" if ok else " (blocked by policy)"), {}
    written = hb.parse_iso(reading.get("written_at"))
    age_h = (hb.now_utc() - written).total_seconds() / 3600 if written else None
    rl = reading.get("rate_limits") or {}
    now_ts = time.time()
    notes = []
    for win, key in (("five_hour", "five_hour_max_pct"), ("seven_day", "seven_day_max_pct")):
        w = rl.get(win) or {}
        pct, resets = w.get("used_percentage"), w.get("resets_at")
        if pct is None:
            continue
        if resets and float(resets) < now_ts:
            notes.append(f"{win} reading void (reset passed)")
            continue
        if float(pct) > float(q.get(key, 100)):
            return False, f"{win} at {pct}% > {q.get(key)}% (resets_at {resets})", reading
        notes.append(f"{win} {pct}%")
    if age_h is not None and age_h > float(q.get("max_age_hours", 12)):
        notes.append(f"stale {age_h:.1f}h")
    return True, "; ".join(notes) or "no windows in reading", reading


# ── provisioning ─────────────────────────────────────────────────────

def provision(cfg: dict, project: Path, item_id: str, fm: dict) -> dict:
    """Fresh worktree on branch hb/<id> from a pinned base; copy read-only state in."""
    branch = branch_name(cfg, project, item_id)
    base_ref = fm.get("base") or cfg.get("base_branch", "main")
    base = _git(project, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    if base.returncode != 0:
        raise RuntimeError(f"base {base_ref!r} not resolvable in {project}: {base.stderr.strip()}")
    base_sha = base.stdout.strip()
    sandbox = project / cfg.get("sandbox_rel", ".hb-heartbeat/sandbox") / item_id
    if sandbox.exists():
        _git(project, "worktree", "remove", "--force", str(sandbox))
        shutil.rmtree(sandbox, ignore_errors=True)
    _git(project, "worktree", "prune")
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    exists = _git(project, "rev-parse", "--verify", f"refs/heads/{branch}").returncode == 0
    if exists:
        r = _git(project, "worktree", "add", str(sandbox), branch)          # retry: continue the branch
    else:
        r = _git(project, "worktree", "add", "-b", branch, str(sandbox), base_sha)
    if r.returncode != 0:
        raise RuntimeError(f"worktree add failed: {r.stderr.strip()}")
    # read-only copies (copy IS the isolation; the sandbox's .state is discarded)
    for rel in ("memory", "work"):
        src, dst = project / ".state" / rel, sandbox / ".state" / rel
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
    for f in ("prefs.json",):
        src = project / ".state" / f
        if src.exists():
            (sandbox / ".state").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, sandbox / ".state" / f)
    (sandbox / RESULT_REL).mkdir(parents=True, exist_ok=True)
    # core.fileMode=false on drvfs: tracked scripts are 100644, so a fresh checkout loses the exec bit
    # and git silently ignores the scrub pre-push hook ("ignored hook" advisory). The push gate must fire.
    hooks_path = _git(project, "config", "core.hooksPath").stdout.strip()
    if hooks_path and not Path(hooks_path).is_absolute():
        for h in (sandbox / hooks_path).glob("*"):
            if h.is_file():
                try:
                    h.chmod(h.stat().st_mode | 0o111)
                except OSError as e:
                    hb.log(f"WARN chmod +x {h}: {e}")
    # sandbox-only controls: deny overlay + hb-guard hook (settings.local.json is merged, not replaced,
    # by child propagation — existing keys survive)
    claude_dir = sandbox / ".claude"
    claude_dir.mkdir(exist_ok=True)
    overlay = {
        "permissions": {"deny": SANDBOX_DENY},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": f"bash \"{(hb.HB / 'hb-guard.sh').as_posix()}\""}]}]},
    }
    (claude_dir / "settings.local.json").write_text(json.dumps(overlay, indent=2) + "\n", encoding="utf-8")
    return {"sandbox": sandbox, "branch": branch, "base_sha": base_sha, "resumed": exists}


def render_prompt(cfg: dict, prov: dict, item_root: Path, project: Path, fm: dict, body: str) -> str:
    tpl = (hb.HB / "prompt-worker.md").read_text(encoding="utf-8")
    scope = fm.get("scope") or []
    fields = {
        "ITEM_ID": str(fm["id"]),
        "BRANCH": prov["branch"],
        "BASE_SHA": prov["base_sha"],
        "PROJECT_NAME": project.name if project != hb.APEX else "claudette",
        "PROJECT_PATH": str(project),
        "SANDBOX": str(prov["sandbox"]),
        "RESULT_DIR": str(prov["sandbox"] / RESULT_REL),
        "QA": str(fm.get("qa") or cfg.get("qa", "mileqa")),
        "PR": "yes" if (fm.get("pr", cfg.get("pr", True)) not in (False, "false", "no")) else "no",
        "SCOPE": ("\n".join(f"- `{s}`" for s in scope) if scope else "- (whole repo)"),
        "ATTEMPT": str(int(fm.get("attempts", 0)) + 1),
        "RESUMED": "yes — the branch already has commits from a previous attempt; continue, do not restart" if prov["resumed"] else "no",
        "TIME_CAP_MIN": str(fm.get("time_cap_min") or cfg.get("item_cap_min", 90)),
        "ITEM_FRONTMATTER": hb.dump_yaml(fm).rstrip(),
        "ITEM_BODY": body.strip(),
    }
    for k, v in fields.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    return tpl


# ── spawn ────────────────────────────────────────────────────────────

def spawn_worker(cfg: dict, prov: dict, prompt: str, fm: dict) -> dict:
    """Run the worker to completion. Returns an envelope-like dict:
    {ok, timed_out, session_id, is_error, result, cost_usd, duration_ms, raw, stderr}."""
    sandbox: Path = prov["sandbox"]
    prompt_file = sandbox / RESULT_REL.parent / "PROMPT.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    cap_s = int(float(fm.get("time_cap_min") or cfg.get("item_cap_min", 90)) * 60)
    env = _env()
    env["CBOOT_EXEC_TIMEOUT"] = str(cap_s)
    env["HB_ITEM_ID"] = str(fm["id"])
    fake = os.environ.get("HB_WORKER_CMD")
    if fake:
        cmd = fake.split() + [str(sandbox), str(prompt_file)]
    else:
        cmd = [cfg.get("python", "python3"), str(hb.APEX / "cboot.py"), "--project", str(sandbox),
               "--exec-file", str(prompt_file), "--model", str(fm.get("model") or cfg.get("model", "sonnet"))]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=cap_s + 120, env=env, cwd=str(hb.APEX))
    except subprocess.TimeoutExpired:
        return {"ok": False, "timed_out": True, "session_id": None, "is_error": True, "result": None,
                "cost_usd": None, "duration_ms": int((time.time() - t0) * 1000), "raw": "", "stderr": "outer timeout"}
    raw = (proc.stdout or "").strip()
    try:
        env_json = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        env_json = {}
    timed_out = "timed out" in str(env_json.get("error", "")).lower()
    return {"ok": proc.returncode == 0 and not env_json.get("is_error"), "timed_out": timed_out,
            "session_id": env_json.get("session_id"), "is_error": bool(env_json.get("is_error")),
            "result": env_json.get("result") if env_json.get("result") is not None else env_json.get("error"),
            "cost_usd": env_json.get("cost_usd"), "duration_ms": env_json.get("duration_ms") or int((time.time() - t0) * 1000),
            "raw": raw[:4000], "stderr": (proc.stderr or "")[-4000:]}


# ── harvest ──────────────────────────────────────────────────────────

def read_result(sandbox: Path) -> tuple[dict, str, dict]:
    """Returns (outcome_frontmatter, outcome_body, extra_files{name:text})."""
    rd = sandbox / RESULT_REL
    fm, body = {}, ""
    out = rd / "outcome.md"
    if out.exists():
        m = hb.FM_RE.match(out.read_text(encoding="utf-8-sig"))
        if m:
            try:
                fm = yaml_load(m.group(1)) or {}
            except Exception:
                fm = {}
            body = m.group(2)
        else:
            body = out.read_text(encoding="utf-8-sig")
    extra = {}
    for name in ("context.md", "state.md"):
        p = rd / name
        if p.exists():
            extra[name] = p.read_text(encoding="utf-8-sig")
    return fm, body, extra


def yaml_load(text):
    import yaml
    return yaml.safe_load(text)


def pr_url(project: Path, branch: str) -> str | None:
    try:
        r = subprocess.run(["gh", "pr", "view", branch, "--json", "url", "-q", ".url"], cwd=str(project),
                           capture_output=True, text=True, timeout=60, env=_env())
        u = r.stdout.strip()
        return u if r.returncode == 0 and u.startswith("http") else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def classify(env: dict, res_fm: dict) -> tuple[str, str]:
    """(terminus, qa_result). Only the terminus table from spec §10.2 lives here."""
    t = str(res_fm.get("terminus") or "").strip().lower()
    qa = str(res_fm.get("qa_result") or "n/a").strip().lower()
    if t in hb.TERMINI_EXPECTED:
        return t, qa
    if env.get("timed_out"):
        return "cap", qa if qa != "n/a" else "n/a"
    blob = f"{env.get('result') or ''}\n{env.get('stderr') or ''}"
    if env.get("is_error") and QUOTA_HINT.search(blob):
        return "quota", "n/a"
    return "unexpected", qa


def state_delta(project: Path, sandbox: Path, dst: Path) -> None:
    """The sandbox's .state is discarded by design (amnesiac nights) — but a worker that files a backlog
    item or resolves one did real work. Preserve it as a reviewable diff, never apply it: state-delta.diff."""
    src_dir, box_dir = project / ".state" / "work", sandbox / ".state" / "work"
    if not box_dir.is_dir():
        return
    try:
        r = subprocess.run(["git", "diff", "--no-index", "--", str(src_dir), str(box_dir)],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return
    if r.stdout.strip():
        (dst / "state-delta.diff").write_text(r.stdout, encoding="utf-8")


def cleanup(project: Path, sandbox: Path) -> None:
    _git(project, "worktree", "remove", "--force", str(sandbox))
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
    _git(project, "worktree", "prune")


# ── main entry ───────────────────────────────────────────────────────

def run(claim: dict, cfg: dict) -> dict | None:
    pid = os.getpid()
    t_start = time.time()

    ok, why, reading = quota_gate(cfg)
    if not ok:
        n = hb.read_night()
        if not n.get("quota_logged"):
            hb.log(f"quota gate closed: {why}")
            hb.night_note(f"quota gate closed: {why}")
            n = hb.read_night(); n["quota_logged"] = True; hb.write_night(n)
        hb.release_flag(pid, "go")   # retry on later ticks: the reading may reset (void) before close
        return None
    hb.log(f"quota gate open: {why}")

    valid, invalid = hb.list_candidates()
    for c in invalid:  # never guess: reject loudly, keep going
        dst = hb.inbox(c["root"]) / c["path"].stem
        dst.mkdir(parents=True, exist_ok=True)
        shutil.move(str(c["path"]), str(dst / "item.md"))
        hb.write_outcome(dst, {"item_id": c["path"].stem, "terminus": "rejected", "qa_result": "n/a",
                               "branch": None, "pr": None, "attempts": c["fm"].get("attempts")},
                         "Rejected by the runner (invalid item frontmatter):\n" + "\n".join(f"- {e}" for e in c["errors"]))
        hb.log(f"rejected {c['path']}: {'; '.join(c['errors'])}")
    if not valid:
        hb.log("queue empty; releasing GO -> absent for tonight")
        hb.night_note("queue empty at pop; nothing to do")
        hb.release_flag(pid, "absent")
        return None

    c = valid[0]
    inflight_path = hb.claim_item(c)
    if inflight_path is None:
        hb.release_flag(pid, "go")
        return None
    fm, body, item_root = c["fm"], c["body"], c["root"]
    item_id = str(fm["id"])
    project = hb.project_root_for(item_root, fm)
    hb.annotate_flag(pid, item_id=item_id)

    entry = {"item_id": item_id, "root_name": c["root_name"], "project": str(project), "started_at": hb.iso(hb.now_utc()),
             "attempts": int(fm.get("attempts", 0)) + 1, "quota_at_gate": reading.get("rate_limits") if reading else None}

    try:
        prov = provision(cfg, project, item_id, fm)
    except Exception as e:
        # provisioning failure is ours, not the worker's: unexpected -> diag, item back to outbox with attempts+1
        diag("provision-failed", {"item_id": item_id, "error": repr(e)})
        fm["attempts"] = int(fm.get("attempts", 0)) + 1
        hb.write_atomic(inflight_path, hb.render_item(fm, body))
        os.rename(inflight_path, c["path"])
        hb.release_flag(pid, "go")
        entry.update({"terminus": "unexpected", "qa_result": "n/a", "error": repr(e)})
        return entry
    entry.update({"branch": prov["branch"], "base_commit": prov["base_sha"], "sandbox": str(prov["sandbox"])})

    prompt = render_prompt(cfg, prov, item_root, project, fm, body)
    env = spawn_worker(cfg, prov, prompt, fm)
    hb.annotate_flag(pid, transcript_path=transcript_path_for(prov["sandbox"], env.get("session_id")))

    res_fm, res_body, extra = read_result(prov["sandbox"])
    terminus, qa_result = classify(env, res_fm)
    head = _git(project, "rev-parse", prov["branch"]).stdout.strip() or None
    files = _git(project, "diff", "--name-only", f"{prov['base_sha']}..{prov['branch']}").stdout.split() if head else []
    pr = res_fm.get("pr") or (pr_url(project, prov["branch"]) if head else None)
    duration_min = round((time.time() - t_start) / 60, 1)

    outcome_fields = {
        "item_id": item_id, "branch": prov["branch"], "pr": pr, "terminus": terminus, "qa_result": qa_result,
        "base_commit": prov["base_sha"], "head_commit": head, "files_touched": files, "attempts": entry["attempts"],
        "session_id": env.get("session_id"), "transcript_path": transcript_path_for(prov["sandbox"], env.get("session_id")),
        "cost_usd": env.get("cost_usd"), "duration_min": duration_min, "worker_is_error": env.get("is_error"),
    }
    summary = res_body.strip() or (f"Worker left no RESULT/outcome.md.\n\nWorker result text:\n\n{(env.get('result') or '')[:3000]}\n\n"
                                   f"stderr tail:\n\n```\n{(env.get('stderr') or '')[-1500:]}\n```")
    dst = hb.inbox(item_root) / item_id
    hb.write_outcome(dst, outcome_fields, summary)
    for name, text in extra.items():
        (dst / name).write_text(text, encoding="utf-8")
    state_delta(project, prov["sandbox"], dst)
    entry.update({"terminus": terminus, "qa_result": qa_result, "pr": pr, "head_commit": head,
                  "files_touched": len(files), "cost_usd": env.get("cost_usd"), "duration_min": duration_min,
                  "session_id": env.get("session_id"), "finished_at": hb.iso(hb.now_utc())})

    if terminus in hb.TERMINI_EXPECTED:
        shutil.copyfile(inflight_path, dst / "item.md")
        inflight_path.unlink()
        cleanup(project, prov["sandbox"])
        hb.release_flag(pid, "go")
        hb.log(f"item {item_id} done: {terminus}/{qa_result} branch {prov['branch']} pr {pr}")
        return entry

    if terminus == "quota":
        # §11.3: the gate cleared and we hit the wall anyway — measurement failure. Loud, dumb, stop the night.
        diag("quota-exhausted", {"item_id": item_id, "reading_at_gate": reading, "reading_now": hb.read_quota(),
                                 "worker_result": (env.get("result") or "")[:2000]})
        shutil.copyfile(inflight_path, dst / "item.md")
        fm["attempts"] = entry["attempts"]
        hb.write_atomic(inflight_path, hb.render_item(fm, body))
        os.rename(inflight_path, c["path"])           # back to outbox for another night
        cleanup(project, prov["sandbox"])
        hb.release_flag(pid, "absent")
        return entry

    # unexpected: leave the corpse for the sweep (spec §10.2 "anything else"). Item stays inflight
    # (orphan sweep bumps attempts), GO stays inflight (close sweep logs the corpse). Sandbox kept for forensics.
    diag("unexpected-terminus", {"item_id": item_id, "envelope": {k: env.get(k) for k in ("is_error", "timed_out", "session_id", "result", "stderr")},
                                 "sandbox": str(prov["sandbox"]), "branch": prov["branch"]})
    hb.log(f"item {item_id} UNEXPECTED terminus; leaving GO inflight + item inflight for the sweep")
    return entry


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        cfg = hb.load_config()
        ok, why, _ = quota_gate(cfg)
        print(f"quota gate: {'open' if ok else 'CLOSED'} — {why}")
        valid, invalid = hb.list_candidates()
        print(f"would pop: {valid[0]['fm']['id'] + ' @' + valid[0]['root_name'] if valid else 'nothing'}")
        for c in invalid:
            print(f"would reject: {c['path']} — {'; '.join(c['errors'])}")
        sys.exit(0)
    print(__doc__)
