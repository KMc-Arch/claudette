#!/usr/bin/env python3
"""Heartbeat runner — the deterministic half of one nightly item.

Called in-process by `hb.py tick` after the tick has atomically claimed GO.
Sequence (spec §10.1, split per plan D1):

    quota gate -> pop one approved item (atomic move to inflight/) -> annotate GO
    -> provision sandbox worktree -> spawn WORKER (headless claude, hard-rooted in the sandbox,
       via cboot.py --project SANDBOX --exec-file PROMPT; NO git/gh credentials) -> harvest RESULT
    -> RUNNER pushes the branch (scrub pre-push hook fires in the live repo) + `gh pr create`
    -> write ~inbox outcome -> remove worktree (branch stays) -> release GO (inflight -> go | absent)

The worker never touches GO, the queues, the live ~inbox, or the remote. Its only outputs are commits
on its branch and RESULT/ inside its own sandbox, which this file harvests. Push + PR are runner
actions with the runner's (the user's) credentials; the worker's environment has gh unauthenticated
(empty GH_CONFIG_DIR) and git credential helpers reset, so a push from inside the sandbox fails.

Standalone dry use (no flag, no spawn):  python3 runner.py --dry-run
Fake worker for tests:                    HB_WORKER_CMD="python3 tests/fake_worker.py" (receives SANDBOX PROMPT_FILE argv)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

import hb  # sibling

RESULT_REL = Path(".hb-heartbeat") / "state" / "RESULT"
QUOTA_HINT = re.compile(r"rate.?limit|usage.?limit|quota|out of (extra )?usage|\b429\b|overloaded", re.I)
QA_RESULTS = ("converged", "held", "exhausted", "escalation", "n/a")

# Belt under the hb-guard hook: prefix denies for the obvious forms (the hook is the real check).
SANDBOX_DENY = [
    "Bash(git push:*)", "Bash(git remote:*)", "Bash(git update-ref:*)", "Bash(git worktree:*)",
    "Bash(git tag:*)", "Bash(git branch -D:*)", "Bash(git branch -f:*)", "Bash(git checkout main:*)",
    "Bash(git switch main:*)", "Bash(gh pr merge:*)", "Bash(gh pr close:*)", "Bash(gh pr ready:*)",
    "Bash(gh pr create:*)", "Bash(gh pr edit:*)", "Bash(gh pr review:*)", "Bash(gh repo:*)",
    "Bash(gh auth:*)", "Bash(gh alias:*)", "Bash(gh api:*)",
]


# ── helpers ──────────────────────────────────────────────────────────

def _git(root: Path, *args, check=False, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check, env=env)


def _env(cfg: dict | None = None) -> dict:
    env = dict(os.environ)
    cfg = cfg or hb.load_config()
    extra = [p for p in cfg.get("extra_path", []) if p]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def apex_aliases() -> list[str]:
    r"""Other mount points of the same Windows directory (drvfs mounts D:\ at /mnt/d and D:\claudette at
    /mnt/claudette). hb-guard needs them for path containment. Best effort from /proc/mounts."""
    out = []
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    apex_src = None
    mounts = []
    for ln in lines:
        parts = ln.split()
        if len(parts) < 4:
            continue
        mp, opts = parts[1].replace("\\040", " "), parts[3]
        m = re.search(r"path=([^;,]+)", opts)
        if not m:
            continue
        src = m.group(1).rstrip("\\").lower()
        mounts.append((mp, src))
        if Path(mp) == hb.APEX:
            apex_src = src
    if not apex_src:
        return out
    for mp, src in mounts:
        if Path(mp) == hb.APEX:
            continue
        if src == apex_src:
            out.append(mp)
        elif apex_src.startswith(src + "\\") or (len(src) == 2 and src.endswith(":") and apex_src.startswith(src)):
            rel = apex_src[len(src):].lstrip("\\").replace("\\", "/")
            out.append(str(Path(mp) / rel))
    return out


def worker_env(cfg: dict, sandbox: Path, item_id: str, cap_s: int) -> dict:
    """The worker's environment: PATH fixed, time cap, and NO git/gh credentials.
    Env-only by nature (an adversarial shell child could `unset` these — hb-guard refuses unset/export/env -u
    of protected names; the true fix is a separate OS user, backlog BL-44)."""
    env = _env(cfg)
    env["CBOOT_EXEC_TIMEOUT"] = str(cap_s)
    env["HB_ITEM_ID"] = item_id
    env["HB_SANDBOX"] = str(sandbox)
    env["HB_APEX_ALIASES"] = ":".join(apex_aliases())
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GIT_ASKPASS", "SSH_ASKPASS", "SSH_AUTH_SOCK",
              "GIT_SSH", "GIT_SSH_COMMAND"):
        env.pop(k, None)
    empty_gh = sandbox / RESULT_REL.parent / "gh-empty"
    empty_gh.mkdir(parents=True, exist_ok=True)
    (empty_gh / "xdg").mkdir(exist_ok=True)
    env["GH_CONFIG_DIR"] = str(empty_gh)               # gh: unauthenticated
    env["XDG_CONFIG_HOME"] = str(empty_gh / "xdg")     # gh/git XDG lookups land in the sandbox
    env["GIT_TERMINAL_PROMPT"] = "0"                    # git: never prompt; a push without creds fails fast
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"              # ~/.gitconfig (URL-scoped gh helper) is not consulted
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    # reset inherited credential helpers (an empty value clears the helper list) and disable askpass
    env["GIT_CONFIG_COUNT"] = "4"
    env["GIT_CONFIG_KEY_0"] = "credential.helper"; env["GIT_CONFIG_VALUE_0"] = ""
    env["GIT_CONFIG_KEY_1"] = "core.askPass"; env["GIT_CONFIG_VALUE_1"] = "/bin/false"
    # identity: the global config is off, so set the worker's committer identity explicitly. A distinct NAME
    # flags autopilot commits in git log/blame; the EMAIL inherits the project's so GitHub still attributes
    # them to the account. Both overridable via cfg["worker_identity"] {name, email}; email null = inherit apex.
    ident = cfg.get("worker_identity") or {}
    name = ident.get("name") or "Heartbeat (autopilot)"
    email = ident.get("email") or _git(hb.APEX, "config", "user.email").stdout.strip() or "heartbeat@localhost"
    env["GIT_CONFIG_KEY_2"] = "user.name"; env["GIT_CONFIG_VALUE_2"] = name
    env["GIT_CONFIG_KEY_3"] = "user.email"; env["GIT_CONFIG_VALUE_3"] = email
    return env


def branch_name(cfg: dict, root: Path, item_id: str) -> str:
    prefix = cfg.get("branch_prefix", "hb/")
    if root.resolve() == hb.APEX.resolve():
        return f"{prefix}{item_id}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-").lower()
    return f"{prefix}{slug}/{item_id}"


def transcript_dir_for(sandbox: Path) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(sandbox))
    return Path.home() / ".claude" / "projects" / slug


def transcript_path_for(sandbox: Path, session_id: str | None) -> str | None:
    if not session_id:
        return None
    return str(transcript_dir_for(sandbox) / f"{session_id}.jsonl")


def diag(kind: str, payload: dict) -> Path:
    """Dumb file write, no model call (spec §11.3)."""
    hb.DIAG.mkdir(parents=True, exist_ok=True)
    p = hb.DIAG / f"{hb.now_utc().strftime('%Y%m%dT%H%M%SZ')}-{kind}-{payload.get('item_id') or 'noitem'}.json"
    hb.write_atomic(p, json.dumps({"kind": kind, "at": hb.iso(hb.now_utc()), **payload}, indent=2, default=str))
    hb.log(f"DIAG {kind}: {p.name}")
    return p


def item_cap_min(cfg: dict, fm: dict) -> int:
    """Per-item cap may LOWER the config ceiling, never raise it (keeps the tick's near-close check honest)."""
    ceiling = int(cfg.get("item_cap_min", 90))
    try:
        want = int(float(fm.get("time_cap_min") or ceiling))
    except (TypeError, ValueError):
        want = ceiling
    return max(1, min(want, ceiling))


# ── quota gate ───────────────────────────────────────────────────────

def quota_gate(cfg: dict) -> tuple[bool, str, dict]:
    """Returns (ok, reason, reading). Stale-by-nature in v1 (statusLine sink; plan D5): a reading older
    than quota.max_age_hours is treated like a missing reading (missing_policy decides)."""
    q = cfg.get("quota", {})
    reading = hb.read_quota()
    allow_missing = q.get("missing_policy", "allow") == "allow"
    if not reading:
        return allow_missing, "quota.json missing" + (" (allowed by policy)" if allow_missing else " (blocked by policy)"), {}
    written = hb.parse_iso(reading.get("written_at"))
    age_h = (hb.now_utc() - written).total_seconds() / 3600 if written else None
    if age_h is None or age_h > float(q.get("max_age_hours", 12)):
        why = f"reading stale ({age_h:.1f}h > {q.get('max_age_hours', 12)}h)" if age_h is not None else "reading has no written_at"
        return allow_missing, why + (" (allowed by policy)" if allow_missing else " (blocked by policy)"), reading
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
        mb = _git(project, "merge-base", base_ref, branch).stdout.strip()   # the commit actually branched from
        if mb:
            base_sha = mb
    else:
        r = _git(project, "worktree", "add", "-b", branch, str(sandbox), base_sha)
    if r.returncode != 0:
        raise RuntimeError(f"worktree add failed: {r.stderr.strip()}")
    # read-only copies (copy IS the isolation; the sandbox's .state is discarded). Only .state/work travels —
    # memory (user profile, preferences) is not needed for an item and would only widen what a worker could leak.
    for rel in ("work",):
        src, dst = project / ".state" / rel, sandbox / ".state" / rel
        if not src.is_dir():
            continue
        # per-file: copy what the repo does NOT track (a tracked skeleton like .state/work/start.md is already in
        # the checkout and must not be overwritten — that would show as a modification the worker might commit)
        tracked = set(x for x in _git(sandbox, "ls-files", "-z", "--", f".state/{rel}").stdout.split("\0") if x)
        for f in src.rglob("*"):
            if not f.is_file():
                continue
            relp = f.relative_to(project).as_posix()
            if relp in tracked:
                continue
            target = sandbox / relp
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, target)
    # a project that does not track .hb-heartbeat/ (every child) must never see the sandbox control files as
    # addable: an ignore-all .gitignore makes the whole dir invisible to `git add -A`
    ctl = sandbox / ".hb-heartbeat"
    ctl.mkdir(exist_ok=True)
    if not _git(sandbox, "ls-files", "--", ".hb-heartbeat").stdout.strip():
        (ctl / ".gitignore").write_text("*\n", encoding="utf-8")
    for f in ("prefs.json",):
        src = project / ".state" / f
        if src.exists():
            (sandbox / ".state").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, sandbox / ".state" / f)
    (sandbox / RESULT_REL).mkdir(parents=True, exist_ok=True)
    # core.fileMode=false on drvfs: tracked scripts are 100644, so a fresh checkout loses the exec bit
    # and git silently ignores the scrub pre-push hook ("ignored hook" advisory). Keep the sandbox honest too.
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
    deny = list(SANDBOX_DENY)
    if not cfg.get("worker_web", False):
        deny += ["WebFetch", "WebSearch"]                # exfiltration surface; opt in per instance via config
    overlay = {
        "permissions": {"deny": deny},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": f"bash \"{(hb.HB / 'hb-guard.sh').as_posix()}\""}]}]},
    }
    (claude_dir / "settings.local.json").write_text(json.dumps(overlay, indent=2) + "\n", encoding="utf-8")
    return {"sandbox": sandbox, "branch": branch, "base_sha": base_sha, "resumed": exists}


def render_prompt(cfg: dict, prov: dict, item_root: Path, project: Path, fm: dict, body: str) -> str:
    tpl = (hb.HB / "prompt-worker.md").read_text(encoding="utf-8")
    scope = fm.get("scope") or []
    # the item body is untrusted-ish human text: neutralize template markers and fence it
    safe_body = body.strip().replace("{{", "{ {").replace("}}", "} }")
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
        "TIME_CAP_MIN": str(item_cap_min(cfg, fm)),
        "ITEM_FRONTMATTER": hb.dump_yaml(fm).rstrip().replace("{{", "{ {"),
        "ITEM_BODY": safe_body,
    }
    for k, v in fields.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    return tpl


# ── spawn ────────────────────────────────────────────────────────────

def spawn_worker(cfg: dict, prov: dict, prompt: str, fm: dict, on_session=None) -> dict:
    """Run the worker to completion (own process group; killed as a group on cap). While it runs, poll
    the sandbox's transcript dir so the GO flag's transcript_path blank is filled as soon as the session
    boots (spec §5.5) — `on_session(transcript_path)` is called once when it appears.
    Returns {ok, timed_out, session_id, is_error, result, cost_usd, duration_ms, raw, stderr}."""
    sandbox: Path = prov["sandbox"]
    prompt_file = sandbox / RESULT_REL.parent / "PROMPT.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    cap_s = item_cap_min(cfg, fm) * 60
    env = worker_env(cfg, sandbox, str(fm["id"]), cap_s)
    fake = os.environ.get("HB_WORKER_CMD")
    if fake:
        cmd = fake.split() + [str(sandbox), str(prompt_file)]
    else:
        cmd = [cfg.get("python", "python3"), str(hb.APEX / "cboot.py"), "--project", str(sandbox),
               "--exec-file", str(prompt_file), "--model", str(fm.get("model") or cfg.get("model", "sonnet"))]
    tdir = transcript_dir_for(sandbox)
    before = set(p.name for p in tdir.glob("*.jsonl")) if tdir.is_dir() else set()
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                            cwd=str(hb.APEX), start_new_session=True)
    seen_transcript = None
    timed_out = False
    deadline = t0 + cap_s + 120
    while True:
        try:
            out, err = proc.communicate(timeout=5)
            break
        except subprocess.TimeoutExpired:
            pass
        if seen_transcript is None and tdir.is_dir():
            new = [p for p in tdir.glob("*.jsonl") if p.name not in before]
            if new:
                seen_transcript = str(max(new, key=lambda p: p.stat().st_mtime))
                if on_session:
                    try:
                        on_session(seen_transcript)
                    except Exception as e:  # never let annotation kill the run
                        hb.log(f"WARN on_session: {e!r}")
        if time.time() > deadline:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
            break
    # whatever remains of the worker's process group (detached helpers, tool servers) dies with the worker
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    raw = (out or "").strip()
    try:
        env_json = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        env_json = {}
    timed_out = timed_out or "timed out" in str(env_json.get("error", "")).lower()
    session_id = env_json.get("session_id")
    if not session_id and seen_transcript:
        session_id = Path(seen_transcript).stem
    return {"ok": proc.returncode == 0 and not env_json.get("is_error") and not timed_out, "timed_out": timed_out,
            "session_id": session_id, "is_error": bool(env_json.get("is_error")) or timed_out,
            "result": env_json.get("result") if env_json.get("result") is not None else env_json.get("error"),
            "cost_usd": env_json.get("cost_usd"), "duration_ms": env_json.get("duration_ms") or int((time.time() - t0) * 1000),
            "raw": raw[:4000], "stderr": (err or "")[-4000:]}


# ── harvest ──────────────────────────────────────────────────────────

def read_result(sandbox: Path) -> tuple[dict, str, dict]:
    """Returns (outcome_frontmatter, outcome_body, extra_files{name:text})."""
    rd = sandbox / RESULT_REL
    fm, body = {}, ""
    out = rd / "outcome.md"
    if out.is_file() and not out.is_symlink():
        text = _read_capped(out)
        m = hb.FM_RE.match(text)
        if m:
            try:
                fm = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                fm = {}
            if not isinstance(fm, dict):
                fm = {}
            body = m.group(2)
        else:
            body = text
    extra = {}
    for name in ("context.md", "state.md"):
        p = rd / name
        if p.is_file() and not p.is_symlink():
            extra[name] = _read_capped(p)
    return fm, body, extra


MAX_RESULT_BYTES = 512 * 1024


def _read_capped(p: Path) -> str:
    """Worker-written files: regular files only, bounded size, tolerant decoding (never hang or crash the runner)."""
    try:
        with open(p, "rb") as f:
            data = f.read(MAX_RESULT_BYTES + 1)
    except OSError:
        return ""
    if len(data) > MAX_RESULT_BYTES:
        data = data[:MAX_RESULT_BYTES] + b"\n\n[truncated by runner: RESULT file exceeded 512 KB]\n"
    return data.decode("utf-8-sig", errors="replace")


def pr_url(project: Path, branch: str, cfg: dict | None = None, open_only: bool = True) -> str | None:
    """URL of the branch's PR. By default only an OPEN one counts (a merged/closed PR from an earlier run must not
    suppress creating a new one)."""
    try:
        r = subprocess.run(["gh", "pr", "view", branch, "--json", "url,state"], cwd=str(project),
                           capture_output=True, text=True, timeout=60, env=_env(cfg))
        if r.returncode != 0:
            return None
        d = json.loads(r.stdout or "{}")
        u = str(d.get("url") or "")
        if not u.startswith("http"):
            return None
        if open_only and str(d.get("state", "")).upper() != "OPEN":
            return None
        return u
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return None


def classify(env: dict, res_fm: dict) -> tuple[str, str]:
    """(terminus, qa_result). Only the terminus table from spec §10.2 lives here."""
    t = str(res_fm.get("terminus") or "").strip().lower()
    qa = str(res_fm.get("qa_result") or "n/a").strip().lower()
    qa = {"clean": "converged"}.get(qa, qa)
    if qa not in QA_RESULTS:
        qa = "n/a"
    # the runner's own evidence outranks the worker's self-declaration
    if env.get("timed_out"):
        return "cap", qa
    blob = f"{env.get('result') or ''}\n{env.get('stderr') or ''}\n{env.get('raw') or ''}"
    if env.get("is_error") and QUOTA_HINT.search(blob):
        return "quota", "n/a"
    if t in hb.TERMINI_EXPECTED:
        return t, qa
    return "unexpected", qa


def publish(cfg: dict, project: Path, prov: dict, item_id: str, res_fm: dict, res_body: str) -> dict:
    """RUNNER-side push + PR (the worker has no credentials). The live repo's pre-push hook (scrub) is
    the push gate; a blocked push is reported, never forced. Returns {pushed, pr, note}."""
    branch = prov["branch"]
    out = {"pushed": False, "pr": None, "note": ""}
    if os.environ.get("HB_NO_PUBLISH"):
        out["note"] = "publish skipped (HB_NO_PUBLISH)"
        return out
    env = _env(cfg)
    env["GIT_TERMINAL_PROMPT"] = "0"                    # a credential miss must fail, not hang the tick
    # egress scrub BEFORE the push: commit messages + touched paths + PR title (the pre-push hook only sees diff lines)
    title = _clean_title(res_fm.get("summary")) or f"Heartbeat {item_id}"
    log_txt = _git(project, "log", "--format=%B%n--", f"{prov['base_sha']}..{branch}").stdout
    paths_txt = _git(project, "diff", "--name-only", f"{prov['base_sha']}..{branch}").stdout
    pre_file = hb.STATE / f"pr-pre-{item_id}.md"
    pre_file.write_text(f"TITLE: {title}\n\nCOMMIT MESSAGES:\n{log_txt}\n\nPATHS:\n{paths_txt}\n", encoding="utf-8")
    ok_pre, why_pre = scrub_text_file(pre_file)
    try:
        pre_file.unlink()
    except OSError:
        pass
    if not ok_pre:
        out["note"] = f"push withheld: scrub flagged commit messages/paths/title ({why_pre})"
        hb.log(f"publish {item_id}: {out['note']}")
        return out
    try:
        r = subprocess.run(["git", "-C", str(project), "push", "-u", "origin", f"refs/heads/{branch}:refs/heads/{branch}"],
                           capture_output=True, text=True, env=env, timeout=600, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        out["note"] = "push timed out (600s)"
        hb.log(f"publish {item_id}: push timed out")
        return out
    if r.returncode != 0:
        out["note"] = f"push blocked/failed (pre-push scrub or remote): {(r.stderr or r.stdout).strip()[-800:]}"
        hb.log(f"publish {item_id}: push failed rc={r.returncode}")
        return out
    out["pushed"] = True
    existing = pr_url(project, branch, cfg)
    if existing:
        out["pr"] = existing
        out["note"] = "PR already existed"
        return out
    body_file = hb.STATE / f"pr-body-{item_id}.md"
    body_text = (f"Produced unattended by Heartbeat (item `{item_id}`, branch `{branch}`, base `{prov['base_sha'][:10]}`).\n\n"
                 f"**Review before merging — nothing here has been merged or approved by a human.**\n\n---\n\n"
                 f"{res_body.strip()}\n")
    body_file.write_text(body_text, encoding="utf-8")
    # scrub gate for the PR text (the pre-push hook only sees the commit range, not the title/body)
    ok_scrub, why_scrub = scrub_text_file(body_file)
    if not ok_scrub:
        body_file.write_text(f"Produced unattended by Heartbeat (item `{item_id}`, branch `{branch}`).\n\n"
                             f"**Outcome text withheld: scrub flagged the worker's outcome ({why_scrub}). "
                             f"See the local `~inbox/hb/{item_id}/` for the full text.**\n", encoding="utf-8")
        title = f"Heartbeat {item_id} (outcome text withheld — scrub)"
        out["note"] = f"PR body withheld: scrub flagged ({why_scrub}); "
        hb.log(f"publish {item_id}: scrub flagged PR text — body withheld")
    try:
        r = subprocess.run(["gh", "pr", "create", "--base", cfg.get("base_branch", "main"), "--head", branch,
                            "--title", f"hb/{item_id}: {title}", "--body-file", str(body_file)],
                           cwd=str(project), capture_output=True, text=True, timeout=120, env=env)
        url = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""
        if r.returncode == 0 and url.startswith("http"):
            out["pr"] = url
        else:
            out["pr"] = pr_url(project, branch, cfg)
            out["note"] = f"gh pr create rc={r.returncode}: {(r.stderr or '').strip()[-500:]}"
    except (OSError, subprocess.TimeoutExpired) as e:
        out["note"] = f"gh pr create failed: {e!r}"
    finally:
        try:
            body_file.unlink()
        except OSError:
            pass
    return out


def _clean_title(s) -> str:
    s = str(s or "").strip()
    first = s.splitlines()[0] if s else ""
    first = "".join(ch for ch in first if ch.isprintable()).strip()
    first = first.lstrip("-").strip()                     # never let a title parse as a gh option
    return first[:100]


def scrub_text_file(path: Path) -> tuple[bool, str]:
    """Run the codex scrub over one file. (True, '') when clean or when scrub is unavailable (logged)."""
    real_apex = Path(__file__).resolve().parent.parent
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, "unreadable"
    if "scrub:allow" in text:
        return False, "worker text carries a scrub:allow pragma"
    # scrub skips over-long lines; fold them so nothing hides past the line cap
    folded = "\n".join(ln[i:i + 1000] for ln in text.splitlines() for i in range(0, max(1, len(ln)), 1000))
    if folded != text.rstrip("\n"):
        path.write_text(folded + "\n", encoding="utf-8")
    scrub = next((c for c in (hb.APEX / ".codex" / "explicit" / "scrub" / "scrub.py",
                              real_apex / ".codex" / "explicit" / "scrub" / "scrub.py") if c.exists()), None)
    if scrub is None:
        hb.log("WARN scrub.py not found; PR text withheld (fail closed)")
        return False, "scrub unavailable"
    try:
        r = subprocess.run([sys.executable, str(scrub), str(path), "--project-root", str(scrub.parent.parent.parent.parent)],
                           capture_output=True, text=True, timeout=120, cwd=str(hb.APEX))
    except (OSError, subprocess.TimeoutExpired) as e:
        hb.log(f"WARN scrub failed to run: {e!r}; treating PR text as flagged")
        return False, "scrub did not run"
    if r.returncode == 0:
        return True, ""
    return False, (r.stdout or r.stderr).strip().splitlines()[-1][:200] if (r.stdout or r.stderr).strip() else f"rc={r.returncode}"


def scope_breach(files: list, scope: list) -> list:
    """Files touched outside the item's scope allowlist (prefix match). Reported, not enforced (v1)."""
    if not scope:
        return []
    pats = [str(s).strip().rstrip("/") for s in scope if str(s).strip()]
    out = []
    for f in files:
        if not any(f == p or f.startswith(p + "/") for p in pats):
            out.append(f)
    return out


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
    inflight_path = hb.claim_item(c, pid)
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
        hb.requeue_or_fail(inflight_path, c["path"], fm, body, cfg, item_root, f"provision failed: {e!r}")
        hb.release_flag(pid, "go")
        entry.update({"terminus": "unexpected", "qa_result": "n/a", "error": repr(e)})
        return entry
    entry.update({"branch": prov["branch"], "base_commit": prov["base_sha"], "sandbox": str(prov["sandbox"])})

    prompt = render_prompt(cfg, prov, item_root, project, fm, body)
    env = spawn_worker(cfg, prov, prompt, fm, on_session=lambda tp: hb.annotate_flag(pid, transcript_path=tp))
    tpath = transcript_path_for(prov["sandbox"], env.get("session_id"))
    if tpath:
        hb.annotate_flag(pid, transcript_path=tpath)

    res_fm, res_body, extra = read_result(prov["sandbox"])
    terminus, qa_result = classify(env, res_fm)
    if res_fm.get("item_id") not in (None, "", item_id) and str(res_fm.get("item_id")) != item_id:
        hb.log(f"WARN outcome item_id {res_fm.get('item_id')!r} != {item_id}")
    head = _git(project, "rev-parse", "--verify", f"refs/heads/{prov['branch']}").stdout.strip() or None
    files = _git(project, "diff", "--name-only", f"{prov['base_sha']}..{prov['branch']}").stdout.split() if head else []
    has_commits = bool(head) and head != prov["base_sha"]

    pub = {"pushed": False, "pr": None, "note": "not published"}
    want_pr = fm.get("pr", cfg.get("pr", True)) not in (False, "false", "no")
    breach = scope_breach(files, fm.get("scope") or [])
    if terminus in hb.TERMINI_EXPECTED and want_pr and has_commits and breach:
        pub["note"] = f"publish withheld: {len(breach)} file(s) outside the item's scope: {breach[:8]}"
        hb.log(f"item {item_id}: {pub['note']}")
    elif terminus in hb.TERMINI_EXPECTED and want_pr and has_commits:
        pub = publish(cfg, project, prov, item_id, res_fm, res_body)
    elif terminus in hb.TERMINI_EXPECTED and want_pr and not has_commits:
        pub["note"] = "no commits on the branch — nothing to publish"
    duration_min = round((time.time() - t_start) / 60, 1)

    outcome_fields = {
        "item_id": item_id, "branch": prov["branch"], "pr": pub["pr"], "pushed": pub["pushed"], "publish_note": pub["note"],
        "scope_breach": breach,
        "terminus": terminus, "qa_result": qa_result, "summary": str(res_fm.get("summary") or "").strip()[:300] or None,
        "base_commit": prov["base_sha"], "head_commit": head, "has_commits": has_commits, "files_touched": files,
        "attempts": entry["attempts"], "session_id": env.get("session_id"),
        "transcript_path": transcript_path_for(prov["sandbox"], env.get("session_id")),
        "cost_usd": env.get("cost_usd"), "duration_min": duration_min, "worker_is_error": env.get("is_error"),
    }
    summary = res_body.strip() or (f"Worker left no RESULT/outcome.md.\n\nWorker result text:\n\n{(env.get('result') or '')[:3000]}\n\n"
                                   f"stderr tail:\n\n```\n{(env.get('stderr') or '')[-1500:]}\n```")
    dst = hb.inbox(item_root) / item_id
    hb.write_outcome(dst, outcome_fields, summary)
    for name, text in extra.items():
        (dst / name).write_text(text, encoding="utf-8")
    state_delta(project, prov["sandbox"], dst)
    entry.update({"terminus": terminus, "qa_result": qa_result, "pr": pub["pr"], "pushed": pub["pushed"], "head_commit": head,
                  "files_touched": len(files), "cost_usd": env.get("cost_usd"), "duration_min": duration_min,
                  "session_id": env.get("session_id"), "finished_at": hb.iso(hb.now_utc())})

    if terminus in hb.TERMINI_EXPECTED:
        shutil.copyfile(inflight_path, dst / "item.md")
        hb.finish_item(inflight_path)
        cleanup(project, prov["sandbox"])
        hb.release_flag(pid, "go")
        hb.log(f"item {item_id} done: {terminus}/{qa_result} branch {prov['branch']} pr {pub['pr']} ({pub['note'] or 'published'})")
        return entry

    if terminus == "quota":
        # §11.3: the gate cleared and we hit the wall anyway — measurement failure. Loud, dumb, stop the night.
        diag("quota-exhausted", {"item_id": item_id, "reading_at_gate": reading, "reading_now": hb.read_quota(),
                                 "worker_result": (env.get("result") or "")[:2000]})
        shutil.copyfile(inflight_path, dst / "item.md")
        hb.requeue_or_fail(inflight_path, c["path"], fm, body, cfg, item_root, "quota exhausted mid-run")   # another night, or failed-repeatedly
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
