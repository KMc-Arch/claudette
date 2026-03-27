#!/usr/bin/env python3
"""Bootstrap a new Claudette2 child project.

Copies the child template from .templates/child/ which includes CLAUDE.md
and the full .state/ scaffolding. All content comes from template files —
this script is the orchestrator, not the source of truth.

Usage:
    python bootstrap-child.py <name> [--project-root <path>]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Bootstrap a new Claudette2 child project")
    parser.add_argument("name", help="Name of the child project")
    parser.add_argument("--project-root", type=Path, default=Path.cwd(),
                        help="Claudette2 project root (default: cwd)")
    args = parser.parse_args()

    root = args.project_root.resolve()
    name = args.name

    # Sanitize name
    if "/" in name or "\\" in name or name.startswith("..") or name.startswith(".codex") or name.startswith(".state") or name.startswith(".claude"):
        print(f"  Error: invalid project name: {name}")
        sys.exit(1)

    target = root / name

    # Validate
    if target.exists():
        print(f"  Error: {target} already exists.")
        sys.exit(1)

    template_dir = root / ".templates" / "child"
    if not template_dir.exists():
        print(f"  Error: Child template not found at {template_dir}")
        sys.exit(1)

    # Copy template tree (includes CLAUDE.md, .gitignore, and full .state/ scaffolding)
    shutil.copytree(template_dir, target)

    # Generate .claude/settings.local.json with correct absolute memory path
    claude_dir = target / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    memory_path = str(target / ".state" / "memory").replace("\\", "/")
    (claude_dir / "settings.local.json").write_text(
        json.dumps({"autoMemoryDirectory": memory_path}, indent=4) + "\n"
    )

    # Report
    created = list(target.rglob("*"))
    dirs = [p for p in created if p.is_dir()]
    files = [p for p in created if p.is_file()]

    print(f"\n  Created child project: {args.name}/")
    print(f"  {len(dirs)} directories, {len(files)} files\n")
    for f in sorted(files):
        print(f"    {f.relative_to(target)}")
    print()


if __name__ == "__main__":
    main()
