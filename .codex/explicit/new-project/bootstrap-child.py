#!/usr/bin/env python3
"""Bootstrap a new Claudette2 child project.

The user-supplied name is authoritative — it goes into CLAUDE.md's `name:`
frontmatter verbatim. The folder name is derived from it per the Naming
Convention in .codex/specs/child-project.md.

Copies the child template from .templates/child/ (CLAUDE.md + full .state/
scaffolding), then fills `name:` and flags any parent-group-promotion opportunity.

Usage:
    python bootstrap-child.py "<name>" [--project-root <path>]
"""

import argparse
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path


def derive_folder_name(name: str) -> str:
    """Apply the Naming Convention folder-derivation rules.

    Returns the derived folder basename. Raises ValueError on empty result.
    """
    # 1. Transliterate non-ASCII to ASCII (NFKD fold)
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    # 2. Trim and lowercase
    s = s.strip().lower()
    # 3. Strip trailing " group"
    if s.endswith(" group"):
        s = s[: -len(" group")].rstrip()
    # 4. Replace spaces with hyphens
    s = s.replace(" ", "-")
    # 5. Strip characters outside [a-z0-9-]
    s = re.sub(r"[^a-z0-9-]", "", s)
    # 6. Collapse hyphens, strip edges
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        raise ValueError(f"Name derives to empty folder: {name!r}")
    return s


def resolve_folder_path(parent: Path, folder_base: str) -> tuple[Path, int | None]:
    """Resolve a non-conflicting folder path.

    Returns (final_path, suffix_applied). suffix is None if folder_base was free;
    otherwise an integer (2 or max(N)+1 over existing <base><N> siblings).
    Case-insensitive collision check — safe on NTFS and other case-insensitive
    filesystems.
    """
    existing_lower = {p.name.lower() for p in parent.iterdir() if p.is_dir()}
    base_lower = folder_base.lower()

    # Find versioned siblings: <base><digits>
    version_pattern = re.compile(rf"^{re.escape(base_lower)}(\d+)$")
    versions = [int(m.group(1)) for s in existing_lower if (m := version_pattern.match(s))]
    bare_exists = base_lower in existing_lower

    if not bare_exists and not versions:
        return (parent / folder_base, None)

    next_v = max(versions) + 1 if versions else 2
    return (parent / f"{folder_base}{next_v}", next_v)


def read_frontmatter(claude_md: Path) -> tuple[str, dict[str, str], str]:
    """Return (prefix_including_opening_delim, parsed_kv, body_with_closing_delim).

    Minimal YAML-frontmatter reader — only handles simple `key: value` lines.
    Returns empty dict if no frontmatter.
    """
    text = claude_md.read_text(encoding="utf-8-sig")
    if not text.startswith("---"):
        return ("", {}, text)
    end = text.find("\n---", 3)
    if end == -1:
        return ("", {}, text)
    fm_lines = text[3 : end + 1].strip("\n").splitlines()
    kv: dict[str, str] = {}
    for line in fm_lines:
        stripped = line.strip()
        if ":" in stripped and not stripped.startswith("#"):
            key, _, val = stripped.partition(":")
            kv[key.strip()] = val.strip()
    return (text[: end + 4], kv, text[end + 4 :])


def fill_name_in_claude_md(target: Path, name: str) -> None:
    """Replace the empty `name:` line in the copied CLAUDE.md with `name: <name>`."""
    claude_md = target / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    # Match a `name:` line that is empty or has only whitespace after the colon.
    # Preserve indentation and the newline.
    new_text, n = re.subn(
        r"^(\s*name:)\s*$",
        lambda m: f"{m.group(1)} {name}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n == 0:
        # Fall back: insert after `root: true` line if no empty name: exists
        new_text, n = re.subn(
            r"^(\s*root:\s*true\s*)$",
            lambda m: f"{m.group(1)}\nname: {name}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    if n == 0:
        raise RuntimeError(f"Could not insert name: into {claude_md}")
    claude_md.write_text(new_text, encoding="utf-8")


def find_apex(start: Path) -> Path | None:
    """Walk up from `start` looking for a CLAUDE.md with `apex-root: true`.

    Returns the directory containing the apex CLAUDE.md, or None if not found.
    """
    for candidate in [start, *start.parents]:
        claude_md = candidate / "CLAUDE.md"
        if not claude_md.exists():
            continue
        _, kv, _ = read_frontmatter(claude_md)
        if kv.get("apex-root", "").lower() == "true":
            return candidate
    return None


def parent_is_root_without_group(parent: Path) -> tuple[bool, str | None]:
    """Return (should_flag, current_parent_name).

    should_flag is True if the parent has a CLAUDE.md declaring `root: true`
    (or `apex-root: true`) whose `name:` value does NOT end with ' Group'.
    """
    claude_md = parent / "CLAUDE.md"
    if not claude_md.exists():
        return (False, None)
    _, kv, _ = read_frontmatter(claude_md)
    is_root = (
        kv.get("root", "").lower() == "true"
        or kv.get("apex-root", "").lower() == "true"
    )
    if not is_root:
        return (False, None)
    parent_name = kv.get("name", "") or None
    already_group = bool(parent_name and parent_name.endswith(" Group"))
    return (not already_group, parent_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a new Claudette2 child project")
    parser.add_argument("name", help="Canonical project name (goes into CLAUDE.md name: frontmatter verbatim)")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Parent project root (default: cwd)",
    )
    args = parser.parse_args()

    parent = args.project_root.resolve()
    name = args.name.strip()

    if not name:
        print("  Error: name is empty.")
        return 1

    try:
        folder_base = derive_folder_name(name)
    except ValueError as e:
        print(f"  Error: {e}")
        return 1

    apex = find_apex(parent)
    if apex is None:
        print(f"  Error: Could not find apex-root ancestor of {parent}")
        return 1
    template_dir = apex / ".templates" / "child"
    if not template_dir.exists():
        print(f"  Error: Child template not found at {template_dir}")
        return 1

    target, suffix = resolve_folder_path(parent, folder_base)

    # Copy template tree. Use copy_function=shutil.copy (not copy2) to skip
    # metadata preservation — copystat fails on v9fs (WSL mounts) with EPERM,
    # which aborts copytree even though file contents copy fine.
    shutil.copytree(template_dir, target, copy_function=shutil.copy)

    # Fill name: in CLAUDE.md
    fill_name_in_claude_md(target, name)

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
    rel_target = target.relative_to(parent)

    print(f"\n  Created child project '{name}' at: {rel_target}/")
    if suffix is not None:
        print(f"  (Folder suffix {suffix} applied — collision with existing sibling.)")
    print(f"  {len(dirs)} directories, {len(files)} files")
    for f in sorted(files):
        print(f"    {f.relative_to(target)}")

    # Flag parent-group-promotion if applicable
    should_flag, parent_name = parent_is_root_without_group(parent)
    if should_flag:
        print()
        print(f"  [FLAG] Parent '{parent_name or parent.name}' is now a group "
              f"(contains this new root). Consider renaming its name: to "
              f"'{parent_name or parent.name} Group'. Non-blocking.")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
