#!/usr/bin/env python3
"""scrub.py — Pre-push scan for sensitive patterns.

Scans staged changes, tracked files, or specific paths against regex
patterns defined in patterns.txt. Reports matches with file, line number,
and matched pattern.

Usage:
    python scrub.py [diff|full|<path>] [--project-root <dir>]

Modes:
    diff   (default) Scan only added lines from git diff (staged changes).
    full   Scan all tracked files via git ls-files.
    <path> Scan the specified file or directory.

Exit codes:
    0  Clean — no matches found.
    1  Matches found — review required.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SELF_EXCLUSIONS = {
    "patterns.txt",
    ".state/memory/user.md",
}

SCRIPT_DIR = Path(__file__).resolve().parent

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".svg",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pyc", ".pyo", ".whl", ".egg",
    ".db", ".sqlite", ".duckdb",
}


def load_patterns(patterns_file: Path) -> list[re.Pattern]:
    """Load regex patterns from file, skipping comments and blank lines."""
    patterns: list[re.Pattern] = []
    for line in patterns_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(re.compile(stripped))
    return patterns


def is_excluded(file_path: str) -> bool:
    """Return True if file_path should be excluded from scanning."""
    normalized = file_path.replace("\\", "/")
    # Skip binary files
    suffix = Path(normalized).suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return True
    for exclusion in SELF_EXCLUSIONS:
        if normalized.endswith(exclusion):
            return True
    try:
        resolved = Path(file_path).resolve()
        if resolved == (SCRIPT_DIR / "patterns.txt").resolve():
            return True
    except (OSError, ValueError):
        pass
    return False


def is_git_repo(cwd: Path) -> bool:
    """Return True if cwd is inside a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=cwd, capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def git_run(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"git {' '.join(args)} failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return result.stdout


def scan_diff(project_root: Path, patterns: list[re.Pattern]) -> list[dict]:
    """Scan added lines in staged git diff."""
    diff_output = git_run(["diff", "--cached", "-U0", "--diff-filter=ACMR"], project_root)
    matches: list[dict] = []
    current_file: str | None = None
    line_number = 0

    for line in diff_output.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("@@ "):
            hunk_match = re.search(r"\+(\d+)", line)
            if hunk_match:
                line_number = int(hunk_match.group(1)) - 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            line_number += 1
            if current_file and not is_excluded(current_file):
                content = line[1:]
                for pattern in patterns:
                    if pattern.search(content):
                        matches.append({
                            "file": current_file,
                            "line": line_number,
                            "pattern": pattern.pattern,
                            "content": content.strip(),
                        })
        elif not line.startswith("-") and not line.startswith("\\"):
            line_number += 1

    return matches


def scan_file(file_path: Path, rel_path: str, patterns: list[re.Pattern]) -> list[dict]:
    """Scan a single file against all patterns."""
    matches: list[dict] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return matches

    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern in patterns:
            if pattern.search(line):
                matches.append({
                    "file": rel_path,
                    "line": line_num,
                    "pattern": pattern.pattern,
                    "content": line.strip(),
                })
    return matches


def scan_full(project_root: Path, patterns: list[re.Pattern]) -> list[dict]:
    """Scan all tracked files."""
    files_output = git_run(["ls-files"], project_root)
    matches: list[dict] = []

    for rel_path in files_output.splitlines():
        rel_path = rel_path.strip()
        if not rel_path or is_excluded(rel_path):
            continue
        file_path = project_root / rel_path
        if file_path.is_file():
            matches.extend(scan_file(file_path, rel_path, patterns))

    return matches


def scan_path(target: Path, project_root: Path, patterns: list[re.Pattern]) -> list[dict]:
    """Scan a specific file or directory."""
    matches: list[dict] = []
    target = target.resolve()

    if target.is_file():
        try:
            rel = str(target.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            rel = str(target)
        if not is_excluded(rel):
            matches.extend(scan_file(target, rel, patterns))
    elif target.is_dir():
        for file_path in sorted(target.rglob("*")):
            if file_path.is_file():
                try:
                    rel = str(file_path.relative_to(project_root)).replace("\\", "/")
                except ValueError:
                    rel = str(file_path)
                if not is_excluded(rel):
                    matches.extend(scan_file(file_path, rel, patterns))
    else:
        print(f"Path not found: {target}", file=sys.stderr)
        sys.exit(2)

    return matches


def format_report(mode: str, matches: list[dict]) -> str:
    """Format scan results as a human-readable report."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# Scrub Report",
        f"",
        f"- **Mode**: {mode}",
        f"- **Timestamp**: {timestamp}",
        f"- **Matches**: {len(matches)}",
        f"- **Status**: {'FAIL — matches found' if matches else 'PASS — clean'}",
        f"",
    ]

    if matches:
        lines.append("## Matches")
        lines.append("")
        for m in matches:
            lines.append(f"- `{m['file']}` line {m['line']}")
            lines.append(f"  - Pattern: `{m['pattern']}`")
            lines.append(f"  - Content: `{m['content'][:120]}`")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-push scan for sensitive patterns.")
    parser.add_argument("mode", nargs="?", default="diff",
                        help="Scan mode: 'diff' (default), 'full', or a file/directory path.")
    parser.add_argument("--project-root", type=Path, default=None,
                        help="Project root directory (defaults to cwd).")
    args = parser.parse_args()

    project_root = (args.project_root or Path.cwd()).resolve()
    patterns_file = SCRIPT_DIR / "patterns.txt"

    if not patterns_file.is_file():
        print(f"Pattern file not found: {patterns_file}", file=sys.stderr)
        sys.exit(2)

    patterns = load_patterns(patterns_file)
    if not patterns:
        print("No patterns loaded from patterns.txt — nothing to scan.", file=sys.stderr)
        sys.exit(0)

    mode = args.mode
    git_available = is_git_repo(project_root)

    if mode == "diff":
        if not git_available:
            print("Not a git repository — falling back to full filesystem scan.", file=sys.stderr)
            mode = "full-fallback"
            matches = scan_path(project_root, project_root, patterns)
        else:
            matches = scan_diff(project_root, patterns)
    elif mode == "full":
        if not git_available:
            print("Not a git repository — scanning all files instead of git ls-files.", file=sys.stderr)
            mode = "full-fallback"
            matches = scan_path(project_root, project_root, patterns)
        else:
            matches = scan_full(project_root, patterns)
    else:
        target = Path(mode)
        if not target.is_absolute():
            target = project_root / target
        matches = scan_path(target, project_root, patterns)
        mode = f"path:{mode}"

    report = format_report(mode, matches)
    output_dir = project_root / ".state" / "tests" / "explicit" / "scrub"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_file = output_dir / f"scrub-{timestamp}.md"
    report_file.write_text(report, encoding="utf-8")

    if matches:
        print(f"FAIL: {len(matches)} match(es) found. Report: {report_file}")
        for m in matches:
            print(f"  {m['file']}:{m['line']}  pattern={m['pattern']}")
        sys.exit(1)
    else:
        print(f"PASS: clean. Report: {report_file}")
        sys.exit(0)


if __name__ == "__main__":
    main()
