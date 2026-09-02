#!/usr/bin/env python3
"""move_project.py — the /move-project command.

Relocate a child project (and every root project nested inside it) to a new
location WITHIN the apex, carrying all of its Claude-side state: the root_id
identity spine (preserved), its transcript history, and the working directory of
any paused session that lived inside it. The intentional-move complement of
`/roots` relink (which recovers from a move already done out of band).

THIN wrapper over the single writer. It carries NO identity/claim write SQL of
its own: every spine mutation dispatches to `roots_register.relink()` — the SOLE
writer of the identity tables. Boot and `/roots` call the same module; three
copies of claim-mutation is exactly the divergence bug that module exists to
prevent. This command ORCHESTRATES built primitives; it adds the tree move, the
session rewrite, the reconcile, and the report around them.

CONFIRMED HOLD on EXECUTION. Dry-run (a plan) is the DEFAULT. A real move requires
--execute AND (an interactive confirmation at a real terminal OR --yes). Building
the command is not held; running a real move is.

WAL discipline (BL-46 round-4). This command does EVERY db read and write on ONE
house write connection and NEVER opens an `immutable=1&mode=ro` reader. Those RO
readers go blind to a write-connection's un-checkpointed WAL commits; by never
opening one here, a stale-ownership read is impossible BY CONSTRUCTION.

Non-goal — cross-platform migration (RUL-028). The re-slug operates in one path
system; a WSL `/mnt/...` <-> Windows `D:\\...` move is out of scope and fails safe.

    python .codex/explicit/move-project/move_project.py <source> <dest> \
           --project-root ^ [--execute] [--yes]
"""

from __future__ import annotations

import argparse
import errno
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Framework MODULES live under the apex; move_project.py sits at
# ^/.codex/explicit/move-project/move_project.py, so parents[3] is the apex — the
# same derivation roots.py/purge.py use. The apex the command OPERATES on comes
# from --project-root (they coincide for the only supported, apex, invocation).
_HERE = Path(__file__).resolve()
_APEX = _HERE.parents[3]
_RR_PATH = _APEX / ".codex" / "reactive" / "roots-register" / "roots_register.py"
_TS_PATH = _APEX / ".codex" / "reactive" / "transcript-slug" / "transcript_slug.py"
_SQLITE_PATH = _APEX / ".codex" / "reactive" / "sqlite" / "sqlite.py"


def _load(path):
    """Load a house meta-script from a filesystem path (mirrors cboot/roots)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RR = _TS = _SQLITE = None


def _rr():
    global _RR
    if _RR is None:
        _RR = _load(_RR_PATH)
    return _RR


def _ts():
    global _TS
    if _TS is None:
        _TS = _load(_TS_PATH)
    return _TS


def _sqlite():
    global _SQLITE
    if _SQLITE is None:
        _SQLITE = _load(_SQLITE_PATH)
    return _SQLITE


def _slug(abs_path):
    """The transcript-store slug for an absolute path (shared derivation)."""
    return _ts().project_slug(abs_path)


# ── Root discovery (FS walk — catches UNregistered nested roots) ──────

def _has_root_true(claude_md):
    """True if a CLAUDE.md frontmatter declares root: true / apex-root: true."""
    try:
        text = claude_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if not text.startswith("---"):
        return False
    end = text.find("---", 3)
    if end == -1:
        return False
    for line in text[3:end].splitlines():
        if line.strip() in ("root: true", "root:true",
                            "apex-root: true", "apex-root:true"):
            return True
    return False


def _discover_child_roots(root):
    """root: true descendants of `root`, recursing through nested roots.

    Skips dot- and underscore-prefixed dirs (invisible / Claude-internal). Does
    NOT include `root` itself. Mirrors the cosette-era prior art.
    """
    found = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    for d in entries:
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        cmd = d / "CLAUDE.md"
        if cmd.exists() and _has_root_true(cmd):
            found.append(d)
            found.extend(_discover_child_roots(d))
    return found


# ── Sessions (~/.claude/sessions/*.json) ─────────────────────────────

def _iter_sessions(home):
    """Yield (file, data) for each parseable ~/.claude/sessions/*.json."""
    sdir = home / ".claude" / "sessions"
    if not sdir.is_dir():
        return
    for f in sorted(sdir.iterdir()):
        if not f.is_file() or f.suffix != ".json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):   # a valid-JSON non-object ([]/42/null) is skipped,
            yield f, data            # not crashed on — every caller does data.get(...)


def _fold(s):
    """ASCII-only lowercase — the case-fold this drvfs mount actually applies
    (matches the DB's COLLATE NOCASE and cboot's _nocase_key). Non-ASCII is left
    untouched and length is preserved, unlike str.casefold (which expands e.g.
    'ß'->'ss' and would shift a prefix-slice boundary)."""
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in str(s))


def _is_within(child, parent):
    """True if `child` is `parent` or nested under it, case-insensitively (this
    mount folds case), on the resolved absolute paths."""
    c, p = _fold(str(child)), _fold(str(parent))
    return c == p or c.startswith(p + "/")


def _under(cwd, base_str):
    """True if `cwd` is `base_str` or a path beneath it (case-insensitive mount).

    Uses the SINGLE ASCII `_fold` — the same fold everywhere (DB `COLLATE NOCASE`
    and the mount's confirmed ASCII case-insensitivity). It is length-preserving, so
    the `cwd[len(base):]` slice a caller does after this match is always aligned;
    `casefold` (full-Unicode) is deliberately NOT used — it expands ß->ss, which
    would over-match an unrelated `SS` path and mis-cut that slice. On this mount
    args are canonicalised to on-disk casing up front (`_true_case`), so a genuine
    case-variant source already reads as its real name here — the fold only mops up
    residual ASCII drift. (Non-ASCII case-folding is a documented latent limitation.)"""
    c, b = _fold(cwd), _fold(base_str)
    return c == b or c.startswith(b + "/")


def _live_sessions_under(home, source_abs):
    """(pid, cwd) for sessions under source with a still-running PID (/proc)."""
    src = str(source_abs)
    live = []
    for _f, data in _iter_sessions(home):
        cwd = data.get("cwd", "") or ""
        pid = data.get("pid")
        if pid and _under(cwd, src) and (Path("/proc") / str(pid)).exists():
            live.append((pid, cwd))
    return live


def _sessions_to_rewrite(home, source_abs, dest_abs):
    """(file, cwd, new_cwd) for every session whose cwd is under source."""
    src, dst = str(source_abs), str(dest_abs)
    out = []
    for f, data in _iter_sessions(home):
        cwd = data.get("cwd", "") or ""
        if _under(cwd, src):
            out.append((f, cwd, dst + cwd[len(src):]))
    return out


# ── Preflight ────────────────────────────────────────────────────────

class Blocked(Exception):
    """A preflight guard that refuses the move (message is user-facing)."""


def _rel(apex, abs_path):
    """Apex-relative POSIX rel_path (real casing), matching how boot stores it.

    Fold-robust: reuses `_apex_rel_parts` rather than a raw `relative_to`. A raw
    `Path.relative_to` is case-SENSITIVE and would raise `ValueError` on a
    case-variant absolute arg that the folded containment guards already accepted —
    an uncaught crash. `_apex_rel_parts` slices off a case-folded prefix, so the two
    apex-relative derivations agree."""
    return "/".join(_apex_rel_parts(apex, abs_path))


def _apex_rel_parts(apex, abs_path):
    """Apex-relative path components of `abs_path` (real casing), or () for the apex
    itself. Sliced off a case-FOLDED prefix match so a case-variant absolute arg
    still yields the true components (case never changes a path's length)."""
    a, p = _fold(str(apex)), _fold(str(abs_path))
    if p == a:
        return ()
    if p.startswith(a + "/"):
        return tuple(str(abs_path)[len(str(apex)) + 1:].split("/"))
    return (abs_path.name,)


def _true_case(apex, abs_path):
    """`abs_path` with its apex-relative components rebuilt to their TRUE on-disk
    casing. `.resolve()` does NOT case-normalise on this drvfs mount, so a mis-cased
    CLI arg keeps its typed case and would mis-slug the transcript store of an
    unregistered root (the registered path is safe — it slugs the DB-authoritative
    rel_path). Each component is matched against its parent's real dirents: an exact
    hit wins; else an ASCII-fold hit (the mount's confirmed case-insensitivity)
    recovers the real name; else the typed name is kept — a non-ASCII variant or a
    not-yet-existing dest leaf — so this is never worse than the raw arg. Caller
    guards that `abs_path` is within `apex` before calling."""
    cur = apex
    for name in _apex_rel_parts(apex, abs_path):
        try:
            names = [e.name for e in cur.iterdir()]
        except OSError:
            names = []
        if name in names:
            real = name
        else:
            real = next((n for n in names if _fold(n) == _fold(name)), name)
        cur = cur / real
    return cur


def _preflight(conn, apex, source_abs, dest_abs, home):
    """Validate + assemble the move plan. Raises Blocked on a hard refusal.

    Returns a dict describing everything that will happen — printed verbatim in a
    dry run and consumed by _execute.
    """
    # ── Containment + shape guards ───────────────────────────────────
    # All path comparisons fold case — this drvfs mount is case-insensitive, so a
    # case-variant of a path is the SAME directory (a raw == / is_relative_to would
    # miss it and, e.g., yank a live session out from under a case-variant source).
    if not source_abs.is_dir():
        raise Blocked("source does not exist or is not a directory: %s" % source_abs)
    if _fold(str(source_abs)) == _fold(str(apex)):
        raise Blocked("refusing to move the apex itself")
    if not _is_within(source_abs, apex):
        raise Blocked("source is outside the apex (%s)" % apex)
    if not _is_within(dest_abs, apex):
        raise Blocked("destination is outside the apex — that is an egress move, refused")
    if dest_abs.exists():
        raise Blocked("destination already exists: %s" % dest_abs)
    if not dest_abs.parent.is_dir():
        raise Blocked("destination parent does not exist: %s" % dest_abs.parent)
    if _is_within(dest_abs, source_abs):
        raise Blocked("destination is inside the source — cannot move a tree into itself")
    for comp in (_apex_rel_parts(apex, source_abs) + _apex_rel_parts(apex, dest_abs)):
        if comp.startswith(("_", ".")):
            raise Blocked("a path component is Claude-internal (%r, dot/underscore-"
                          "prefixed) — refusing to move framework/invisible internals"
                          % comp)

    source_rel = _rel(apex, source_abs)
    dest_rel = _rel(apex, dest_abs)
    projects = home / ".claude" / "projects"

    # ── Spine identities under the moved tree → relink each ───────────
    src_l = _fold(source_rel)
    identities = []          # (root_id, old_rel, new_rel, old_store, new_store, will_move)
    covered_rel = set()      # folded rels that a spine identity already owns
    for row in conn.execute(
            "SELECT root_id, rel_path FROM roots_register WHERE valid_to IS NULL"):
        rp = row["rel_path"]
        rp_l = _fold(rp)
        if rp_l == src_l or rp_l.startswith(src_l + "/"):
            new_rel = dest_rel + rp[len(source_rel):]
            old_store = projects / _slug(apex / rp)
            new_store = projects / _slug(apex / new_rel)
            will_move = old_store != new_store and old_store.exists()
            identities.append((row["root_id"], rp, new_rel,
                               old_store, new_store, will_move))
            covered_rel.add(rp_l)

    # ── UNregistered nested roots (FS walk) → best-effort store follow ─
    unregistered = []        # (old_abs, new_abs, old_store, new_store, will_move)
    walked = [source_abs] + _discover_child_roots(source_abs)
    for d in walked:
        rel = _rel(apex, d)
        if _fold(rel) in covered_rel:
            continue
        new_abs = dest_abs / d.relative_to(source_abs)
        old_store = projects / _slug(d)
        new_store = projects / _slug(new_abs)
        will_move = old_store != new_store and old_store.exists()
        unregistered.append((d, new_abs, old_store, new_store, will_move))

    # ── Store collisions ─────────────────────────────────────────────
    # A REGISTERED identity's store collision is a hard blocker (relink refuses it
    # anyway — a merge would destroy real history). An UNregistered one is
    # best-effort, NOT blocking (start.md): the store just stays put and the dir
    # re-canonicalizes at the new path on next boot — reported (per-item, inline in
    # the plan and at execute), never fatal.
    collisions = [ns for (_r, _o, _n, _os, ns, wm) in identities if wm and ns.exists()]

    # ── Session guard + rewrites ─────────────────────────────────────
    live = _live_sessions_under(home, source_abs)
    sessions = _sessions_to_rewrite(home, source_abs, dest_abs)

    # ── Report-only surfaces (never rewritten) ───────────────────────
    child_repos = [d for d in walked if (d / ".git").exists()]

    return {
        "apex": apex, "source_abs": source_abs, "dest_abs": dest_abs,
        "source_rel": source_rel, "dest_rel": dest_rel,
        "identities": identities, "unregistered": unregistered,
        "collisions": collisions, "live": live, "sessions": sessions,
        "child_repos": child_repos,
    }


# ── Plan printout ────────────────────────────────────────────────────

def _print_plan(plan, execute):
    p = plan
    print()
    print("  move-project — %s" % ("EXECUTE" if execute else "DRY RUN (plan only)"))
    print("    from: %s" % p["source_abs"])
    print("      to: %s" % p["dest_abs"])
    print()
    print("  [tree]     os.rename  %s -> %s" % (p["source_rel"], p["dest_rel"]))
    if p["identities"]:
        print("  [identity] relink %d root(s), identity + transcripts preserved:"
              % len(p["identities"]))
        for rid, old_rel, new_rel, _os, _ns, wm in p["identities"]:
            tail = "  (+ transcript store)" if wm else "  (no store to move)"
            print("               root_id=%s  %s -> %s%s" % (rid, old_rel, new_rel, tail))
    else:
        print("  [identity] no registered identity under the source")
    for _o, new_abs, _os, ns, wm in p["unregistered"]:
        if wm and ns.exists():
            note = ("store CANNOT follow — a store already occupies the dest slug; "
                    "left in place, re-canonicalizes on next boot")
        elif wm:
            note = "transcript store follows (best-effort), re-canonicalizes on next boot"
        else:
            note = "no store, re-canonicalizes on next boot"
        print("  [unreg]    %s — not a registered identity; %s"
              % (_rel(p["apex"], new_abs), note))
    if p["sessions"]:
        print("  [sessions] rewrite cwd in %d paused session file(s)" % len(p["sessions"]))
    print("  [reconcile] cboot --materialize-only (agent files + inventory)")
    if p["child_repos"]:
        print("  [report]   %d nested git repo(s) — .git internals NOT rewritten:"
              % len(p["child_repos"]))
        for d in p["child_repos"]:
            print("               %s" % _rel(p["apex"], d))
    print("  [report]   Windows Task Scheduler paths + cross-project text refs: "
          "not rewritten — review by hand")
    print()
    if p["live"]:
        print("  BLOCKER: %d live session(s) running inside the source:" % len(p["live"]))
        for pid, cwd in p["live"]:
            print("               pid=%s  cwd=%s" % (pid, cwd))
    if p["collisions"]:
        print("  BLOCKER: a transcript store already exists at the destination slug:")
        for ns in p["collisions"]:
            print("               %s" % ns)
    if p["live"] or p["collisions"]:
        print()


# ── Execute ──────────────────────────────────────────────────────────

def _execute(conn, plan, apex, home):
    """Perform the move with written per-step rollback for the atomic core.

    Atomic core (rolled back on any failure): tree os.rename + every identity
    relink (spine writes in ONE transaction + each relink's transcript store).
    Post-commit reconcile (unregistered stores, session cwd, cboot, report) is
    best-effort — its failures are reported, never rolled back over a good move.
    """
    source_abs, dest_abs = plan["source_abs"], plan["dest_abs"]
    undo = []  # inverse actions for the atomic core, run in reverse on failure
    try:
        # E1 — cold tree move (this mount ghosts hot-tree renames).
        os.rename(source_abs, dest_abs)
        undo.append(lambda: os.rename(dest_abs, source_abs))
        # Post-rename verification: a 9p hot-tree rename can "succeed" (no error)
        # yet leave a ghost dirent — listed but unstattable/untraversable
        # (reference_9p_rename_ghost). Confirm the move really took BEFORE committing
        # durable identity over it; a ghost trips the undo (rename back) + rollback.
        try:
            moved_ok = dest_abs.is_dir() and not source_abs.exists()
        except OSError:
            moved_ok = False   # a ghosted dirent can raise ESTALE rather than
            #                    return a bool — treat that as a failed verification
        if not moved_ok:
            raise OSError(errno.EIO, "post-rename verification failed (possible 9p "
                          "ghost): the destination is not a traversable directory, "
                          "or the source is still present after the rename")
        print("  [ok] moved tree -> %s" % dest_abs)

        # E2 — relink each identity in ONE transaction; commit once.
        for rid, _old_rel, new_rel, old_store, new_store, will_move in plan["identities"]:
            _rr().relink(conn, rid, new_rel, home=home)
            if will_move:
                undo.append(_make_store_undo(new_store, old_store))
            print("  [ok] relinked root_id=%s -> %s%s"
                  % (rid, new_rel, "  (+ store)" if will_move else ""))
        conn.commit()
        undo.clear()  # the move is durable; no core rollback past this point
        print("  [ok] identity spine committed")
    except Exception as e:
        undo_failed = []
        for fn in reversed(undo):
            try:
                fn()
            except Exception as ue:  # best-effort unwind — collect, keep going
                undo_failed.append(str(ue))
        try:
            conn.rollback()
        except Exception:
            pass
        if undo_failed:
            # The rollback itself could not fully undo — do NOT claim a clean revert.
            print("  [FAIL] move failed AND rollback was INCOMPLETE: %s" % e)
            print("  [!!] state may be left partly moved — filesystem and identity "
                  "spine can be out of sync. source=%s dest=%s. Reconcile with "
                  "/roots (relink the orphaned identity, or move the tree back by "
                  "hand), then re-run. rollback errors: %s"
                  % (source_abs, dest_abs, "; ".join(undo_failed)))
        else:
            print("  [FAIL] move aborted and rolled back: %s" % e)
        if isinstance(e, OSError) and e.errno in (errno.EACCES, errno.EPERM):
            _report_lock_diagnostic(source_abs)
        return 1

    # ── Post-commit reconcile (best-effort) ──────────────────────────
    for _old_abs, _new_abs, old_store, new_store, will_move in plan["unregistered"]:
        if not will_move:
            continue
        if new_store.exists():   # dest slug occupied — leave it, report (never fatal)
            print("  [warn] unregistered store %s not moved — a store already "
                  "occupies the dest slug; it re-canonicalizes at the new path on "
                  "next boot" % old_store.name)
            continue
        try:
            os.rename(old_store, new_store)
            print("  [ok] moved unregistered store -> %s" % new_store.name)
        except OSError as ue:
            print("  [warn] could not move unregistered store %s: %s"
                  % (old_store.name, ue))

    rewritten = 0
    for f, _cwd, new_cwd in plan["sessions"]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):   # changed under us since preflight
                continue
            data["cwd"] = new_cwd
            f.write_text(json.dumps(data) + "\n", encoding="utf-8")
            rewritten += 1
        except (OSError, ValueError) as ue:
            print("  [warn] could not rewrite session %s: %s" % (f.name, ue))
    if plan["sessions"]:
        print("  [ok] rewrote cwd in %d/%d session file(s)"
              % (rewritten, len(plan["sessions"])))

    _reconcile(apex)
    _print_report_only(plan)
    print("  Done. `claude` can now be run from %s" % dest_abs)
    return 0


def _make_store_undo(new_store, old_store):
    """A closure that reverses a relink's transcript-store move on rollback."""
    def _undo():
        if new_store.exists() and not old_store.exists():
            os.rename(new_store, old_store)
    return _undo


def _reconcile(apex):
    """Re-materialize agent files + walk inventory (idempotent). Best-effort."""
    cboot = apex / "cboot.py"
    if not cboot.exists():
        print("  [warn] cboot.py not found — run a re-materialize manually")
        return
    try:
        r = subprocess.run(
            [sys.executable, "-B", str(cboot), "--materialize-only"],
            cwd=str(apex), capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            print("  [ok] reconciled agent files + inventory (cboot --materialize-only)")
        else:
            print("  [warn] cboot --materialize-only exited %d — run it by hand:\n%s"
                  % (r.returncode, (r.stderr or r.stdout)[-800:]))
    except (OSError, subprocess.SubprocessError) as e:
        print("  [warn] could not run cboot --materialize-only (%s) — run it by hand" % e)


def _print_report_only(plan):
    if plan["child_repos"]:
        print("  [report] nested git repos moved with intact .git (paths inside are "
              "relative; verify remotes/hooks if any use absolute paths):")
        for d in plan["child_repos"]:
            print("             %s" % _rel(plan["apex"], d))
    print("  [report] NOT rewritten — review by hand: Windows Task Scheduler path "
          "registrations, and cross-project text refs (backlogs/memories/designs) "
          "that mention the old path.")


# ── Lock diagnostics (a rename EACCES → who holds the subtree) ────────
#
# A move's tree rename fails with EACCES when another process holds a file OR a
# DIRECTORY under the source open — and a single locked descendant *directory*
# blocks moving the whole subtree even though the node itself is free and no file
# is locked. Off WSL that stays a bare errno-13; on WSL the holder is almost always
# a Windows app (an Explorer window, an editor/viewer, or Search indexing a file
# here), invisible to Linux /proc. This turns that cryptic failure into a named
# locked path. Best-effort and self-contained: it must never itself raise.

_LOCKED_DIR_SCAN_PS = r'''$src=@"
using System;
using System.Runtime.InteropServices;
public static class MpLock {
  [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)]
  public static extern IntPtr CreateFileW(string p,uint a,uint sh,IntPtr sa,uint d,uint f,IntPtr t);
  [DllImport("kernel32.dll",SetLastError=true)]
  public static extern bool CloseHandle(IntPtr h);
}
"@
Add-Type $src
$root='__ROOT__'
$dirs=@($root)+(Get-ChildItem -Recurse -Directory -Force $root -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
foreach($d in $dirs){
  $h=[MpLock]::CreateFileW($d,0x00010000,0,[IntPtr]::Zero,3,0x02000000,[IntPtr]::Zero)
  if($h -eq [IntPtr](-1)){
    $e=[Runtime.InteropServices.Marshal]::GetLastWin32Error()
    if($e -eq 32){ Write-Output ("LOCKED`t"+$d) }   # 32 = ERROR_SHARING_VIOLATION
  } else { [void][MpLock]::CloseHandle($h) }
}
'''


def _which_powershell():
    """A Windows PowerShell reachable from WSL, or None (feature-detect)."""
    for name in ("powershell.exe", "pwsh.exe"):
        p = shutil.which(name)
        if p:
            return p
    cand = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    return str(cand) if cand.exists() else None


def _win_locked_descendants(source_abs):
    """Descendant dirs of `source_abs` a Windows process holds open (share-violation).

    Returns Linux paths (may include `source_abs` itself). Best-effort: [] off WSL,
    without powershell/wslpath, or on any probe error — a diagnostic never raises.
    """
    pwsh = _which_powershell()
    wslpath = shutil.which("wslpath")
    if not pwsh or not wslpath or not source_abs.exists():
        return []
    try:
        win = subprocess.run([wslpath, "-w", str(source_abs)], capture_output=True,
                             text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return []
    if not win:
        return []
    ps = _LOCKED_DIR_SCAN_PS.replace("__ROOT__", win.replace("'", "''"))
    try:
        out = subprocess.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-Command", ps], capture_output=True, text=True,
                             timeout=90).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    locked = []
    for line in out.splitlines():
        if line.startswith("LOCKED\t"):
            winpath = line[len("LOCKED\t"):].strip()
            try:
                lin = subprocess.run([wslpath, "-u", winpath], capture_output=True,
                                     text=True, timeout=15).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                lin = ""
            locked.append(lin or winpath)
    return locked


def _report_lock_diagnostic(source_abs):
    """Explain a rename EACCES and, on WSL, name the locked descendant(s)."""
    print("  [why] EACCES on the tree move: another process holds a file or a "
          "DIRECTORY under the source open — even one locked descendant directory "
          "blocks moving the whole subtree. On WSL this is usually a Windows app "
          "(an Explorer window, an editor/viewer, or Search indexing a file here), "
          "invisible to Linux /proc.")
    locked = _win_locked_descendants(source_abs)
    if locked:
        print("  [locked] a Windows process holds these open — close it, then retry:")
        for p in locked:
            print("             %s" % p)
        print("  [tip] name the holder with Sysinternals: `handle64.exe \"%s\"`, or "
              "Process Explorer -> Ctrl+F -> the folder name." % source_abs.name)
    else:
        print("  [locked] could not pin the exact descendant (not on WSL, or the "
              "probe was unavailable). Close any Explorer window / editor / viewer "
              "open under the source, then retry.")


# ── CLI ──────────────────────────────────────────────────────────────

def _confirm(dest_abs):
    """Interactive confirmation for a real move. True to proceed."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        ans = input("  Type the destination path to confirm the move: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans == str(dest_abs)


def run(argv=None):
    ap = argparse.ArgumentParser(
        prog="move-project",
        description="Move a child project within the apex, carrying its state.")
    ap.add_argument("source", type=Path, help="project to move (absolute or apex-relative)")
    ap.add_argument("dest", type=Path, help="destination (absolute or apex-relative)")
    ap.add_argument("--project-root", type=Path, default=Path.cwd(),
                    help="the apex (holds .state/roots.db)")
    ap.add_argument("--execute", action="store_true",
                    help="perform the move (default: dry-run plan only)")
    ap.add_argument("--yes", action="store_true",
                    help="skip the interactive confirmation (execution still needs --execute)")
    ap.add_argument("--home", type=Path, default=None,
                    help="override ~ (holds .claude/projects and .claude/sessions); for testing")
    args = ap.parse_args(argv)

    apex = args.project_root.resolve()
    home = args.home.resolve() if args.home else Path.home()
    source_abs = (apex / args.source).resolve() if not args.source.is_absolute() \
        else args.source.resolve()
    dest_abs = (apex / args.dest).resolve() if not args.dest.is_absolute() \
        else args.dest.resolve()
    # Recover true on-disk casing (resolve() does not case-normalise on drvfs, so a
    # mis-cased arg would otherwise mis-slug an unregistered root's store). Only for
    # in-apex paths — an egress path is left for _preflight to refuse.
    if _is_within(source_abs, apex):
        source_abs = _true_case(apex, source_abs)
    if _is_within(dest_abs, apex):
        dest_abs = _true_case(apex, dest_abs)

    db_path = apex / ".state" / "roots.db"
    if not db_path.exists():
        sys.stderr.write("move-project: no identity spine at %s\n" % db_path)
        return 2

    # ONE house write connection for every read and write (WAL discipline —
    # never an immutable=1&mode=ro reader, so no stale-ownership read is possible).
    conn = _sqlite().connect(str(db_path))
    try:
        try:
            plan = _preflight(conn, apex, source_abs, dest_abs, home)
        except Blocked as b:
            sys.stderr.write("move-project: %s\n" % b)
            return 2

        _print_plan(plan, args.execute)

        if not args.execute:
            print("  Dry run only. Re-run with --execute (after confirming) to move.")
            print()
            return 0

        if plan["live"] or plan["collisions"]:
            sys.stderr.write("move-project: refusing to execute — resolve the "
                             "BLOCKER(s) above first.\n")
            return 2

        if not args.yes and not _confirm(dest_abs):
            sys.stderr.write("move-project: not confirmed (need a matching "
                             "confirmation at a terminal, or --yes).\n")
            return 1

        return _execute(conn, plan, apex, home)
    finally:
        conn.close()


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
