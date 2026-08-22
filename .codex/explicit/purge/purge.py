#!/usr/bin/env python3
"""purge.py — Clean transient state from a Claudette2 project.

Purge operates on an explicit ALLOWLIST of categories. Scope levels differ only
in (a) which allowlisted categories are in play and (b) whether recency-sparing
applies. Nothing outside the allowlist is ever eligible, in any scope — so the
hard floor (.codex, audits, start.md, _-prefixed) is never touched because it is
never on the list, not because of a carve-out.

  bare `purge`   Quotidian tidy. Deletes only regenerable SAFE state and prunes
                 keep-recent dirs (traces, boot reports) to the newest N.
                 KEEPS everything precious: transcripts, pauses, project brains
                 (memory/work/plans/bundles), and loose .tmp/ buffers. Sandbox
                 rigs + root stragglers are REPORTED, never deleted.

  `purge all`    Nuclear reset (CONFIRMED HOLD). Every allowlisted category, no
                 recency sparing: SAFE + keep-recent (fully) + precious
                 (transcripts, pauses) + high-value + the ENTIRE .tmp/ (loose
                 buffers, sandbox rigs, every subdir). Only the hard floor
                 survives. Sandbox is DELETED here, not reported.

  `purge <proj>` Bare rules aimed at a child project.

The `_`-prefixed (invisible) floor and `start.md` manifests are protected at
EVERY depth: they are never listed, never counted toward a keep-recent window,
and never recursed into — a dir that holds one is emptied of deletables but
survives.

Usage:
    python purge.py                     # bare
    python purge.py all                 # nuclear (prompts unless --confirm)
    python purge.py <project>           # child project scope
    python purge.py --dry-run           # preview without deleting
    python purge.py all --confirm       # skip confirmation prompt
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import re
import shutil
import sys
from pathlib import Path

# Ownership of files in .claude/agents/ is NOT decided here. purge and cboot
# share one implementation — two divergent copies of that test is exactly how
# purge came to delete files cboot would have preserved.
_AO_PATH = (Path(__file__).resolve().parents[3]
            / ".codex" / "reactive" / "agent-ownership" / "agent_ownership.py")


def _agent_ownership():
    """Load the shared ownership module, or None if it is unavailable.

    None means 'ownership cannot be established', which for a deleter is the
    same as 'owns nothing' — preserve everything.
    """
    try:
        spec = importlib.util.spec_from_file_location("agent_ownership", _AO_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except (OSError, ImportError, AttributeError):
        return None

# Hard floor — never on any allowlist. Also enforced by separate boundaries
# (framework immutability, audit-immutability-guard); listed here so purge is
# self-evidently incapable of reaching them.
# `.state/roots.db` is on the floor because it is no longer a rebuildable cache:
# its agent_optin and agent_registry tables hold decisions a human made once and
# the claims every file in .claude/agents/ depends on. Deleting it would orphan
# them all — and, since ownership is a registry lookup, would leave purge itself
# unable to tell its own files from hand-authored ones ever again.
NEVER_PURGE = {".codex", ".state/tests/audits", ".state/roots.db"}

# Keep-recent dirs retain their newest N files under bare purge; `purge all`
# passes keep=0 to wipe them. One constant, one rule ("keep the N newest files
# in each keep-recent dir"). Cadence differs — boot reports are per-boot, traces
# per-active-day — so N buys a different real window in each, which is fine: it
# gives the forensic trace trail a little more runway than boot-report noise,
# and the recent tail is all a green-switchboard purge needs.
KEEP_RECENT = 5

# (subdir under .state/, filename glob) for each keep-recent target. Lexical name
# order must equal chronological order (ISO-style names), since pruning sorts by
# filename. tests/boot holds two report kinds cboot writes — full-boot
# `*-bootstrap.md` and per-child `*-refresh-*.md` — pruned independently so each
# kind keeps its own newest N (mixing the two formats in one sort would break the
# chronological assumption).
KEEP_RECENT_TARGETS = (
    ("traces", "*.trace"),
    ("tests/boot", "*-bootstrap.md"),
    ("tests/boot", "*-refresh-*.md"),
)

# Filenames that look like throwaway scratch when found OUTSIDE .tmp/. Reported,
# never deleted — surfaces transient-gravity violations without acting on them.
TMP_STRAGGLER_PATTERNS = ("*msg.txt", "*-prbody.md", "*.bak", "*.orig", "*.rej")


def _is_protected(path: Path, root: Path) -> bool:
    """Return True if path is on the hard floor: a start.md manifest, an
    `_`-prefixed (invisible) item, a symlink, or inside a NEVER_PURGE zone.

    Centralizing the `_`-prefix check here (not only in each caller) closes the
    deletion paths that bypassed it — prune_dir_keep_recent's glob matches and
    the recursive dir walk both consult this.
    """
    if path.name == "start.md":
        return True
    if path.name.startswith("_"):
        return True
    if path.is_symlink():
        return True
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True  # outside root = protected, never delete
    rel_posix = rel.as_posix()
    for zone in NEVER_PURGE:
        if rel_posix == zone or rel_posix.startswith(zone + "/"):
            return True
    return False


def _is_underscore_prefixed(path: Path) -> bool:
    return path.name.startswith("_")


def _is_settings_json(path: Path) -> bool:
    # Defensive pre-filter documenting the "preserve settings*.json" intent. Currently
    # redundant with the `.jsonl`/`.md`-only removal sweep in _purge_claude_dir (a
    # `.json` file is never in that set), but kept deliberately: it makes the intent
    # explicit and keeps settings safe should the removal set ever widen. Not a bug.
    return path.name.startswith("settings") and path.suffix == ".json"


def _project_slug(project_root: Path) -> str:
    """Claude Code's transcript-store slug for a project: the resolved absolute
    path with every non-alphanumeric character replaced by '-'.

    This matches how Claude Code itself names ~/.claude/projects/<slug>/ (verified
    against the real store: `/mnt/claudette/~majel` → `-mnt-claudette--majel`,
    `.steward` → `--steward`). The earlier `\\ / :`-only replacement left `~`, `.`
    and other characters intact, so `~`/`.`-rooted projects never matched their
    real store and their transcripts were silently skipped under `purge all`.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(project_root.resolve()))


def _find_project_footprint(project_root: Path) -> Path | None:
    """Locate ~/.claude/projects/<slug>/ for this project — the transcript store."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return None

    candidate = projects_dir / _project_slug(project_root)
    if candidate.is_dir():
        return candidate

    # No loose leaf-name fallback. A fuzzy `endswith("-"+leaf)` match could select
    # a DIFFERENT project's transcript store (any project sharing the same leaf
    # dir name) and rmtree it. If the exact slug isn't present, refuse to guess —
    # return None and delete no footprint. Fail-safe: better to under-delete
    # transcripts than to delete the wrong project's.
    return None


class Purger:
    """Accumulates removal actions and optionally executes them."""

    def __init__(self, root: Path, dry_run: bool = False):
        self.root = root.resolve()
        self.dry_run = dry_run
        self.removed: list[str] = []
        self.skipped: list[str] = []
        self.warnings: list[str] = []  # fail-loud signals (e.g. expected-but-absent footprint)

    def _label(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def _remove_one_file(self, path: Path) -> None:
        if self.dry_run:
            self.removed.append(f"  would remove file: {self._label(path)}")
        else:
            path.unlink()
            self.removed.append(f"  removed file: {self._label(path)}")

    def _remove_whole_dir(self, path: Path) -> None:
        if self.dry_run:
            self.removed.append(f"  would remove dir:  {self._label(path)}")
        else:
            shutil.rmtree(path)
            self.removed.append(f"  removed dir:  {self._label(path)}")

    def remove_file(self, path: Path) -> None:
        if not path.exists():
            return
        if _is_protected(path, self.root):
            self.skipped.append(f"  PROTECTED: {self._label(path)}")
            return
        self._remove_one_file(path)

    def _prune_tree(self, path: Path) -> bool:
        """Recursively remove everything under `path` that is NOT protected, keeping
        protected items (`_`-prefixed, start.md, symlinks, NEVER_PURGE) and any
        directory that transitively holds one. Returns True if `path` survives.

        Assumes `path` itself is already known non-protected. A subtree with no
        protected descendant is removed wholesale (one report line); only subtrees
        that actually contain something protected are itemized.
        """
        if not any(_is_protected(c, self.root) for c in path.rglob("*")):
            self._remove_whole_dir(path)
            return False

        survived = False
        for child in sorted(path.iterdir()):
            if _is_protected(child, self.root):
                self.skipped.append(f"  PROTECTED (kept): {self._label(child)}")
                survived = True
            elif child.is_dir():
                if self._prune_tree(child):
                    survived = True
            else:
                self._remove_one_file(child)

        if survived:
            return True
        # No protected item survived under here after all → remove the empty dir.
        self._remove_whole_dir(path)
        return False

    def remove_dir(self, path: Path) -> None:
        """Remove a directory, honoring the protected floor at every depth.

        A clean dir is removed wholesale. A dir that (at any depth) holds a
        protected item is emptied of its deletable contents but SURVIVES, still
        holding the protected item — so `purge all` can never destroy a nested
        `_secret.md` or a buried `start.md` by blind rmtree.
        """
        if not path.exists():
            return
        if _is_protected(path, self.root):
            self.skipped.append(f"  PROTECTED: {self._label(path)}")
            return
        self._prune_tree(path)

    def remove_dir_external(self, path: Path) -> None:
        """Remove a dir OUTSIDE the project root — only under ~/.claude/projects/."""
        if not path.exists():
            return
        if path.is_symlink():
            self.skipped.append(f"  PROTECTED (symlink): {path}")
            return
        projects_dir = Path.home() / ".claude" / "projects"
        if not path.resolve().is_relative_to(projects_dir.resolve()):
            self.skipped.append(f"  PROTECTED (outside ~/.claude/projects/): {path}")
            return
        label = str(path)
        if self.dry_run:
            self.removed.append(f"  would remove dir:  {label}")
        else:
            shutil.rmtree(path)
            self.removed.append(f"  removed dir:  {label}")

    def prune_dir_keep_recent(self, path: Path, pattern: str, keep: int) -> None:
        """Remove files matching pattern in path, retaining the newest `keep`.

        `_`-prefixed matches are excluded from the candidate list BEFORE the
        keep-N window is computed — an invisible item must never occupy a keep
        slot (a `_pinned.trace` would otherwise displace a real trace, keeping
        only keep-1 real files). Sorting is by filename — callers rely on
        ISO-timestamped names so lexical order equals chronological order. The
        directory itself is left in place. `keep <= 0` removes everything matched.
        """
        if not path.is_dir():
            return
        files = sorted(
            p for p in path.glob(pattern)
            if p.is_file() and not _is_underscore_prefixed(p)
        )
        to_remove = files[:-keep] if keep > 0 else files
        for f in to_remove:
            self.remove_file(f)

    def report(self) -> None:
        if self.warnings:
            for line in self.warnings:
                print(line)
            print()
        if self.removed:
            for line in self.removed:
                print(line)
        else:
            print("  (nothing to remove)")
        if self.skipped:
            print()
            for line in self.skipped:
                print(line)


# ── SAFE tier (deleted in every scope) ─────────────────────────────────────

def _purge_agents_dir(purger: Purger, agents_dir: Path, project_root: Path) -> None:
    """Remove only the files cboot currently CLAIMS in .claude/agents/.

    Ownership is a lookup of each file's path against the current rows of
    agent_registry in .state/roots.db — never a guess from the file's contents.
    Nothing here opens or decodes a candidate file, so a hand-authored file
    cannot be deleted for looking generated, and a non-UTF-8 one cannot crash
    the purge mid-run.

    Fail-safe: if the registry is missing, locked, or unreadable, cboot owns
    NOTHING and every file is preserved. Guessing the other way deletes a live
    project's agent.
    """
    if not agents_dir.exists():
        return
    # A symlinked agents/ is never followed and never deleted through — the same
    # protection remove_dir() gives skills/. Iterating it would delete the
    # link target's contents.
    if _is_protected(agents_dir, purger.root):
        purger.skipped.append(f"  PROTECTED: {purger._label(agents_dir)}")
        return
    if not agents_dir.is_dir():
        return

    ao = _agent_ownership()
    if ao is None:
        purger.skipped.append(
            f"  PRESERVED (ownership module unavailable): {purger._label(agents_dir)}")
        return

    db_path = project_root / ".state" / "roots.db"
    try:
        claims = ao.claims_for(db_path, agents_dir)
    except ao.RegistryUnavailable as e:
        purger.skipped.append(
            f"  PRESERVED (registry unreadable — cboot owns nothing): "
            f"{purger._label(agents_dir)} [{e}]")
        return

    for item in sorted(agents_dir.iterdir()):
        if _is_underscore_prefixed(item) or item.is_dir():
            continue
        # cboot's own interrupted-write staging file. Never hand-authored, so it
        # is removable without consulting the registry.
        if ao.is_tmp_artifact(item):
            purger.remove_file(item)
            continue
        if ao.owns(item, claims):
            purger.remove_file(item)
        else:
            purger.skipped.append(f"  PRESERVED (hand-authored): {purger._label(item)}")


def _purge_claude_dir(purger: Purger, claude_dir: Path,
                      project_root: Path | None = None) -> None:
    """Clean .claude/ — remove .jsonl, .md; skills/; claimed agents/ files.
    Preserve settings*.json, hand-authored agents, and _-prefixed."""
    if not claude_dir.is_dir():
        return

    skills = claude_dir / "skills"
    if skills.is_dir() and not _is_underscore_prefixed(skills):
        purger.remove_dir(skills)

    # agents/ is NOT wholesale-removable: it mixes cboot's generated files with
    # hand-authored ones the user owns.
    _purge_agents_dir(purger, claude_dir / "agents",
                      project_root if project_root is not None else claude_dir.parent)

    for item in claude_dir.iterdir():
        if _is_underscore_prefixed(item):
            continue
        if item.is_dir():
            continue
        if _is_settings_json(item):
            continue
        if item.suffix in (".jsonl", ".md"):
            purger.remove_file(item)


def _purge_safe_state(purger: Purger, state_dir: Path) -> None:
    """SAFE state under .state/: prefs-resolved + transient tests output.

    Skips audits (floor), boot (keep-recent, handled separately), and start.md.
    """
    if not state_dir.is_dir():
        return

    purger.remove_file(state_dir / "prefs-resolved.json")

    tests_dir = state_dir / "tests"
    if tests_dir.is_dir():
        for item in tests_dir.iterdir():
            if item.name in ("audits", "boot", "start.md"):
                continue
            if _is_underscore_prefixed(item):
                continue
            if item.is_dir():
                purger.remove_dir(item)
            else:
                purger.remove_file(item)


def _purge_keep_recent(purger: Purger, state_dir: Path, keep: int) -> None:
    """Prune keep-recent dirs (traces, boot reports) to the newest `keep`.

    Bare purge passes keep=KEEP_RECENT; `purge all` passes keep=0 to wipe them.
    """
    if not state_dir.is_dir():
        return
    for subdir, pattern in KEEP_RECENT_TARGETS:
        purger.prune_dir_keep_recent(state_dir / subdir, pattern, keep)


# ── PRECIOUS + HIGH-VALUE (deleted only by `purge all`) ────────────────────

def _purge_precious(purger: Purger, project_root: Path) -> None:
    """Session-continuity artifacts: pauses/ contents + the external transcript store.

    Precious because either bar qualifies: a mineable record of what was asked,
    and the ability to /resume. Removed only under the nuclear scope.
    """
    pauses = project_root / ".state" / "pauses"
    if pauses.is_dir():
        for item in pauses.iterdir():
            if item.name == "start.md" or _is_underscore_prefixed(item):
                continue
            if item.is_dir():
                purger.remove_dir(item)
            else:
                purger.remove_file(item)

    footprint = _find_project_footprint(project_root)
    if footprint:
        purger.remove_dir_external(footprint)
    else:
        # Fail loud: `purge all` reaches here expecting a transcript store. If none
        # resolves, say so — a silent skip once hid the slug bug that never matched
        # `~`/`.`-rooted projects at all.
        purger.warnings.append(
            f"  WARNING: no transcript store found at "
            f"~/.claude/projects/{_project_slug(project_root)}/ — none removed "
            f"(purge all expected one; it may already be clear)")


def _purge_high_value(purger: Purger, state_dir: Path) -> None:
    """Project brains: memory/, work/, plans/, bundles/. Removed only under `all`."""
    if not state_dir.is_dir():
        return

    for subdir_name in ("memory", "work", "plans", "bundles"):
        subdir = state_dir / subdir_name
        if subdir.is_dir():
            for item in subdir.iterdir():
                if item.name == "start.md":
                    continue
                if _is_underscore_prefixed(item):
                    continue
                if item.is_dir():
                    purger.remove_dir(item)
                else:
                    purger.remove_file(item)


def _purge_tmp_all(purger: Purger, tmp_dir: Path) -> None:
    """`all` scope: clear the ENTIRE .tmp/ — loose buffers, .tmp/sandbox/ rigs, and
    every other subdir — except the protected floor (.tmp/start.md and any
    `_`-prefixed item, at any depth; remove_dir preserves those recursively).

    No recency sparing — `purge all` is a deliberate, confirmed, quiet-moment
    operation, so a freshness guard would only add a rule for no real protection.
    Sandbox is DELETED here (not reported); detection surfaces it only under the
    bare/child scopes, where nothing in .tmp/ is otherwise removed.
    """
    if not tmp_dir.is_dir():
        return
    for item in sorted(tmp_dir.iterdir()):
        if item.name == "start.md" or _is_underscore_prefixed(item):
            continue
        if item.is_dir():
            purger.remove_dir(item)
        else:
            purger.remove_file(item)


# ── DETECT (report-only) ───────────────────────────────────────────────────

def _detect_sandbox(purger: Purger, tmp_dir: Path) -> None:
    """Report .tmp/sandbox/ rigs — never delete. Sandbox can hold live work, so
    bare/child purge surfaces each rig and the user decides what to clear. (Under
    `purge all` sandbox is cleared outright, so this detector is not run there.)"""
    sandbox = tmp_dir / "sandbox"
    if not sandbox.is_dir():
        return
    for item in sandbox.iterdir():
        if item.name == "start.md" or _is_underscore_prefixed(item):
            continue
        purger.skipped.append(
            f"  SANDBOX RIG (not removed): {purger._label(item)}")


def _detect_tmp_stragglers(purger: Purger, project_root: Path, tmp_dir: Path) -> None:
    """Report transient-looking files at the project root found OUTSIDE .tmp/.

    Report-only in EVERY scope: never deletes. Surfaces violations of
    transient-gravity so scratch that landed outside .tmp/ is visible rather than
    silently missed.
    """
    for item in project_root.iterdir():
        if item == tmp_dir or item.is_dir() or _is_underscore_prefixed(item):
            continue
        if any(fnmatch.fnmatch(item.name, pat) for pat in TMP_STRAGGLER_PATTERNS):
            purger.skipped.append(
                f"  STRAGGLER (outside .tmp/, not removed): {purger._label(item)}")


# ── Scope orchestration ────────────────────────────────────────────────────

def _purge_common_safe(purger: Purger, project_root: Path, keep: int) -> None:
    """The floor of every scope: SAFE tier + keep-recent (pruned to `keep`)."""
    _purge_claude_dir(purger, project_root / ".claude", project_root)
    _purge_safe_state(purger, project_root / ".state")
    _purge_keep_recent(purger, project_root / ".state", keep)


def _detect(purger: Purger, project_root: Path, *, include_sandbox: bool = True) -> None:
    tmp_dir = project_root / ".tmp"
    if include_sandbox:
        _detect_sandbox(purger, tmp_dir)
    _detect_tmp_stragglers(purger, project_root, tmp_dir)


def purge_bare(purger: Purger, project_root: Path) -> None:
    _purge_common_safe(purger, project_root, KEEP_RECENT)
    _detect(purger, project_root)


def purge_all(purger: Purger, project_root: Path) -> None:
    _purge_common_safe(purger, project_root, 0)  # wipe keep-recent, no sparing
    _purge_high_value(purger, project_root / ".state")
    _purge_precious(purger, project_root)
    _purge_tmp_all(purger, project_root / ".tmp")  # clears sandbox too
    _detect(purger, project_root, include_sandbox=False)  # sandbox already cleared


def purge_child(purger: Purger, project_root: Path, child_name: str) -> None:
    child_root = project_root / child_name
    if not child_root.resolve().is_relative_to(project_root.resolve()):
        print(f"error: child path escapes project root: {child_name}", file=sys.stderr)
        sys.exit(1)
    if not child_root.is_dir():
        print(f"error: child project not found: {child_root}", file=sys.stderr)
        sys.exit(1)
    # Scope to child root so floor paths resolve correctly, then apply bare rules.
    child_purger = Purger(child_root, dry_run=purger.dry_run)
    purge_bare(child_purger, child_root)
    purger.removed.extend(child_purger.removed)
    purger.skipped.extend(child_purger.skipped)
    purger.warnings.extend(child_purger.warnings)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="purge",
                                     description="Clean transient state from a Claudette2 project.")
    parser.add_argument("scope", nargs="?", default="default",
                        help='"default" (or omit), "all", or a child project name.')
    parser.add_argument("--project-root", type=Path, default=Path.cwd(),
                        help="Project root directory (default: cwd).")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would be deleted without deleting.")
    parser.add_argument("--confirm", action="store_true",
                        help='Skip confirmation prompt for "all" scope.')
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        print(f"error: project root not found: {project_root}", file=sys.stderr)
        sys.exit(1)

    scope = args.scope
    is_all = scope == "all"
    is_default = scope == "default"

    if is_all and not args.dry_run and not args.confirm:
        print("WARNING: 'purge all' is a NUCLEAR reset. With no recency sparing it removes:")
        print("  - transcripts (~/.claude/projects/<slug>/) and pauses   [session history]")
        print("  - memory, work, plans, bundles                          [project brains]")
        print("  - all traces and boot reports")
        print("  - the ENTIRE .tmp/ — loose buffers, sandbox rigs, every subdir")
        print("Only the hard floor survives (.codex, audits, start.md, _-prefixed).")
        print("This is destructive and cannot be undone.")
        try:
            answer = input("Type 'yes' to confirm: ")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "purge"
    if not is_all and not is_default:
        print(f"[{mode}] scope: child project '{scope}' in {project_root}")
    else:
        print(f"[{mode}] scope: {scope} in {project_root}")

    purger = Purger(project_root, dry_run=args.dry_run)

    if is_all:
        purge_all(purger, project_root)
    elif is_default:
        purge_bare(purger, project_root)
    else:
        purge_child(purger, project_root, scope)

    purger.report()
    sys.exit(0)


if __name__ == "__main__":
    main()
