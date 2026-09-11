#!/usr/bin/env python3
"""Bootstrap a new Claudette2 child project.

The user-supplied name is authoritative — it goes into CLAUDE.md's `name:`
frontmatter verbatim. The folder name is derived from it per the Naming
Convention in .codex/specs/child-project.md.

Copies the child template from .templates/child/ (CLAUDE.md + full .state/
scaffolding), then fills `name:` (and, with --description, the one-line body
description) and flags any parent-group-promotion opportunity.

Usage:
    python bootstrap-child.py [--name-file <path> | -- '<name>'] [--description-file <path> | --description='<one line>'] [--project-root '<path>']
"""

import argparse
import errno
import importlib.util
import re
import shutil
import sys
import unicodedata
from pathlib import Path


def _load_module(path):
    """Load a Python module from an arbitrary filesystem path."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def copy_tree_tolerant(src: Path, dst: Path) -> None:
    """Recursively copy file *contents* from src to dst, tolerating EPERM on
    metadata ops (chmod/copystat). Required on v9fs mounts (WSL), where stat
    operations raise EPERM even though file contents copy fine. shutil.copytree
    can't be used: it runs copystat on every directory, which aborts the copy.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        d = dst / item.name
        if item.is_dir():
            copy_tree_tolerant(item, d)
        else:
            shutil.copyfile(item, d)  # contents only — no mode/stat copy
    try:
        shutil.copystat(src, dst)  # best-effort metadata
    except OSError as e:
        if e.errno != errno.EPERM:
            raise


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
    if len(s) > FOLDER_MAX:
        raise ValueError(f"Name derives to a folder name longer than {FOLDER_MAX} characters.")
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
    # Bytes, not write_text: on Windows, text mode would turn every LF into CRLF,
    # and the CLAUDE.md guard refuses any CLAUDE.md containing a CR.
    claude_md.write_bytes(new_text.encode("utf-8"))


READ_LINE = re.compile(r"^(Read `\.state/start\.md`\.)[ \t]*$", re.MULTILINE)

# The characters claude-md-immutability-guard.sh refuses anywhere in a CLAUDE.md
# (every str.splitlines() break other than LF, plus the BOM). Keep in step with
# UNVETTABLE there: one of these in the scaffold freezes the file for Claude.
UNVETTABLE = "".join(chr(c) for c in (13, 11, 12, 28, 29, 30, 133, 8232, 8233, 65279))
NAME_FIRST_BANNED = set("[]{}&*!|>%@`")
DESCRIPTION_MAX = 300
FOLDER_MAX = 100


def input_problem(name: str, description: str) -> str | None:
    """Why this name/description would leave a broken or frozen CLAUDE.md, or None."""
    for label, text in (("name", name), ("description", description)):
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as e:
            return f"{label} cannot be encoded as UTF-8 ({e})."
        if any(c in UNVETTABLE for c in text):
            return f"{label} contains a line break or BOM character."
    if any(unicodedata.category(c) == "Cc" for c in name):
        return "name contains a control character."
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in description):
        return "description contains a control or invisible formatting character."
    if len(description) > DESCRIPTION_MAX:
        return f"description is longer than {DESCRIPTION_MAX} characters."
    if "---" in name:
        # Frontmatter readers that stop at the first --- anywhere (Claude Code's
        # own included) would end the block inside the name.
        return "name contains ---."
    return None


def guard_name_problem(name: str) -> str | None:
    """Why the guard's name: grammar would refuse a later Claude rename, or None."""
    if name[:1] in NAME_FIRST_BANNED:
        return f"starts with {name[0]!r}"
    if len(name) > 200:
        return "is longer than 200 characters"
    if any(unicodedata.category(c) in ("Cf", "Cs", "Co", "Cn") for c in name):
        return "contains a format, private-use or unassigned character"
    return None


def fill_description_in_claude_md(target: Path, description: str) -> None:
    """Write the one-line description into the body, above the `Read .state/start.md` line.

    This happens here, at scaffold time, because claude-md-immutability-guard.sh
    makes the body of an existing CLAUDE.md immutable to Claude: the description
    cannot be added with an Edit once the file exists.
    """
    claude_md = target / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    new_text, n = READ_LINE.subn(lambda m: f"{description}\n\n{m.group(1)}", text, count=1)
    if n == 0:
        raise RuntimeError(f"Could not place the description in {claude_md}: "
                           f"no `Read .state/start.md` line")
    claude_md.write_bytes(new_text.encode("utf-8"))   # LF on every platform (see above)


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
    name_group = parser.add_mutually_exclusive_group(required=True)
    name_group.add_argument("name", nargs="?", default=None,
                            help="Canonical project name (goes into CLAUDE.md name: frontmatter verbatim)")
    name_group.add_argument("--name-file", type=Path, default=None,
                            help="Read the name from this UTF-8 file instead (no shell quoting involved)")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Parent project root (default: cwd)",
    )
    desc_group = parser.add_mutually_exclusive_group()
    desc_group.add_argument(
        "--description",
        default=None,
        help="One-line project description, written into the CLAUDE.md body at scaffold time",
    )
    desc_group.add_argument(
        "--description-file",
        type=Path,
        default=None,
        help="Read the one-line description from this UTF-8 file instead (no shell quoting involved)",
    )
    args = parser.parse_args()

    parent = args.project_root.resolve()
    try:
        # utf-8-sig: a file saved by a Windows editor may start with a BOM.
        raw_name = (args.name_file.read_text(encoding="utf-8-sig") if args.name_file is not None
                    else args.name or "")
        raw_description = (args.description_file.read_text(encoding="utf-8-sig")
                           if args.description_file is not None else args.description or "")
    except (OSError, UnicodeDecodeError) as e:
        print(f"  Error: cannot read the name or description file ({e}).")
        return 1
    name = raw_name.strip()
    if args.description_file is not None and not raw_description.strip():
        print("  Error: --description-file is empty.")
        return 1
    if len([ln for ln in raw_description.splitlines() if ln.strip()]) > 1:
        print("  Error: the description must be one line.")
        return 1
    description = " ".join(raw_description.split())

    if not name:
        print("  Error: name is empty.")
        return 1
    # Both land in CLAUDE.md, whose body and structural keys Claude can never
    # repair afterwards (claude-md-immutability-guard.sh) — so refuse input that
    # would leave a broken or permanently frozen file, before anything is copied.
    problem = input_problem(name, description)
    if problem:
        print(f"  Error: {problem}")
        return 1
    later = guard_name_problem(name)
    if later:
        print(f"  [NOTE] The name {later}. Claude cannot write a name like that "
              f"(claude-md-immutability-guard.sh), so any later rename by Claude — adding "
              f"' Group', say — must also drop it. A human can edit it freely.")

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
    # Check the template BEFORE copying anything: a scaffold that comes out wrong
    # cannot be fixed by Claude afterwards.
    template_text = (template_dir / "CLAUDE.md").read_text(encoding="utf-8")
    if any(c in UNVETTABLE for c in template_text):
        print("  Error: template CLAUDE.md contains a CR, BOM or other non-LF line break.")
        return 1
    if re.search(r"^[ \t]*name:[ \t]*\S", template_text, re.MULTILINE):
        print("  Error: template CLAUDE.md already has a name: value (filling it would duplicate it).")
        return 1
    if description and not READ_LINE.search(template_text):
        print(f"  Error: template CLAUDE.md has no `Read .state/start.md` line "
              f"to place --description above.")
        return 1

    target, suffix = resolve_folder_path(parent, folder_base)

    # Copy template tree. copy_tree_tolerant copies contents but swallows EPERM
    # on metadata ops (chmod/copystat), which v9fs (WSL mounts) raise and which
    # would otherwise abort the whole copy.
    copy_tree_tolerant(template_dir, target)

    # Fill name: (frontmatter) and the description (body) in CLAUDE.md
    fill_name_in_claude_md(target, name)
    if description:
        fill_description_in_claude_md(target, description)

    # Note: .claude/settings.local.json (autoMemoryDirectory + perms), settings.json,
    # skill shims, and prefs-resolved.json are all created by the materialization
    # step below — the single shared per-child path — not hand-written here.

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

    # Materialize the child (settings.json, settings.local.json, skill shims,
    # prefs-resolved.json) via the single shared per-child path — the same engine
    # full boot and `cboot --project` use. Reads the apex's already-generated
    # outputs; if they're absent (apex never booted), it warns and the child can
    # be materialized later with `cboot --project <folder>`.
    print("\n  Materializing child (settings, perms, shims, resolved prefs)...")
    child_propagate = _load_module(apex / ".codex" / "implicit" / "00-preboot" / "child_propagate.py")
    mat_report = child_propagate._CliReport()
    # cboot resolves a relative --project against the APEX, not the parent, so the
    # recovery hint must be apex-relative (these differ for nested projects).
    recover_target = target.relative_to(apex)
    try:
        if child_propagate.propagate_one(apex, target, mat_report) is None:
            print(f"  [WARN] Child not materialized (apex not booted yet?). "
                  f"Run: cboot --project {recover_target}")
    except OSError as e:
        # _propagate_one writes with write_text (no EPERM tolerance); on v9fs a
        # metadata-triggered write can fail. Scaffold is already valid — recover
        # by materializing later rather than aborting with a traceback.
        print(f"  [WARN] Materialization failed ({e}). "
              f"Scaffold is intact — run: cboot --project {recover_target}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
