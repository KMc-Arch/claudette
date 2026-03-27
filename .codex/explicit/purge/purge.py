#!/usr/bin/env python3
"""purge.py — Clean transient state from a Claudette2 project.

Removes session artifacts, generated files, and optionally high-value
state files.

Usage:
    python purge.py                     # default scope
    python purge.py all                 # full reset (memory + work)
    python purge.py <project>           # child project scope
    python purge.py --dry-run           # preview without deleting
    python purge.py all --confirm       # skip confirmation prompt
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

NEVER_PURGE = {".codex", ".state/tests/audits", ".state/pauses", ".state/bundles"}


def _is_protected(path: Path, root: Path) -> bool:
    """Return True if path falls inside a never-purge zone or is a start.md manifest."""
    if path.name == "start.md":
        return True
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    rel_posix = rel.as_posix()
    for zone in NEVER_PURGE:
        if rel_posix == zone or rel_posix.startswith(zone + "/"):
            return True
    return False


def _is_underscore_prefixed(path: Path) -> bool:
    return path.name.startswith("_")


def _is_settings_json(path: Path) -> bool:
    return path.name.startswith("settings") and path.suffix == ".json"


def _find_project_footprint(project_root: Path) -> Path | None:
    """Locate ~/.claude/projects/<slug>/ for this project."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return None

    resolved = str(project_root.resolve())
    slug = resolved.replace("\\", "-").replace("/", "-").replace(":", "-")
    candidate = projects_dir / slug
    if candidate.is_dir():
        return candidate

    leaf = project_root.resolve().name
    for d in projects_dir.iterdir():
        if d.is_dir() and leaf in d.name:
            return d

    return None


class Purger:
    """Accumulates removal actions and optionally executes them."""

    def __init__(self, root: Path, dry_run: bool = False):
        self.root = root.resolve()
        self.dry_run = dry_run
        self.removed: list[str] = []
        self.skipped: list[str] = []

    def _label(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def remove_file(self, path: Path) -> None:
        if not path.exists():
            return
        if _is_protected(path, self.root):
            self.skipped.append(f"  PROTECTED: {self._label(path)}")
            return
        label = self._label(path)
        if self.dry_run:
            self.removed.append(f"  would remove file: {label}")
        else:
            path.unlink()
            self.removed.append(f"  removed file: {label}")

    def remove_dir(self, path: Path) -> None:
        if not path.exists():
            return
        if _is_protected(path, self.root):
            self.skipped.append(f"  PROTECTED: {self._label(path)}")
            return
        label = self._label(path)
        if self.dry_run:
            self.removed.append(f"  would remove dir:  {label}")
        else:
            shutil.rmtree(path)
            self.removed.append(f"  removed dir:  {label}")

    def remove_dir_external(self, path: Path) -> None:
        if not path.exists():
            return
        label = str(path)
        if self.dry_run:
            self.removed.append(f"  would remove dir:  {label}")
        else:
            shutil.rmtree(path)
            self.removed.append(f"  removed dir:  {label}")

    def report(self) -> None:
        if self.removed:
            for line in self.removed:
                print(line)
        else:
            print("  (nothing to remove)")
        if self.skipped:
            print()
            for line in self.skipped:
                print(line)


def _purge_claude_dir(purger: Purger, claude_dir: Path) -> None:
    """Clean .claude/ — remove .jsonl, .md; skills/; agents/. Preserve settings*.json and _-prefixed."""
    if not claude_dir.is_dir():
        return

    for subdir_name in ("skills", "agents"):
        subdir = claude_dir / subdir_name
        if subdir.is_dir() and not _is_underscore_prefixed(subdir):
            purger.remove_dir(subdir)

    for item in claude_dir.iterdir():
        if _is_underscore_prefixed(item):
            continue
        if item.is_dir():
            continue
        if _is_settings_json(item):
            continue
        if item.suffix in (".jsonl", ".md"):
            purger.remove_file(item)


def _purge_state_transient(purger: Purger, state_dir: Path) -> None:
    """Clean transient items from .state/."""
    if not state_dir.is_dir():
        return

    prefs = state_dir / "prefs-resolved.json"
    purger.remove_file(prefs)

    tests_dir = state_dir / "tests"
    if tests_dir.is_dir():
        for item in tests_dir.iterdir():
            if item.name == "audits":
                continue
            if item.name == "start.md":
                continue
            if _is_underscore_prefixed(item):
                continue
            if item.is_dir():
                purger.remove_dir(item)
            else:
                purger.remove_file(item)

    traces_dir = state_dir / "traces"
    if traces_dir.is_dir():
        for item in traces_dir.iterdir():
            if item.name == "start.md":
                continue
            if _is_underscore_prefixed(item):
                continue
            if item.is_dir():
                purger.remove_dir(item)
            else:
                purger.remove_file(item)


def _purge_state_high_value(purger: Purger, state_dir: Path) -> None:
    """Clean memory/ and work/ inside .state/."""
    if not state_dir.is_dir():
        return

    for subdir_name in ("memory", "work"):
        subdir = state_dir / subdir_name
        if subdir.is_dir():
            for item in subdir.iterdir():
                if _is_underscore_prefixed(item):
                    continue
                if item.is_dir():
                    purger.remove_dir(item)
                else:
                    purger.remove_file(item)


def purge_default(purger: Purger, project_root: Path) -> None:
    _purge_claude_dir(purger, project_root / ".claude")
    _purge_state_transient(purger, project_root / ".state")
    footprint = _find_project_footprint(project_root)
    if footprint:
        purger.remove_dir_external(footprint)


def purge_all(purger: Purger, project_root: Path) -> None:
    purge_default(purger, project_root)
    _purge_state_high_value(purger, project_root / ".state")


def purge_child(purger: Purger, project_root: Path, child_name: str) -> None:
    child_root = project_root / child_name
    if not child_root.is_dir():
        print(f"error: child project not found: {child_root}", file=sys.stderr)
        sys.exit(1)
    _purge_claude_dir(purger, child_root / ".claude")
    _purge_state_transient(purger, child_root / ".state")


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
        print("WARNING: 'purge all' will remove .state/memory/ and .state/work/ files.")
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
        purge_default(purger, project_root)
    else:
        purge_child(purger, project_root, scope)

    purger.report()
    sys.exit(0)


if __name__ == "__main__":
    main()
