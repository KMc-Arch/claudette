#!/usr/bin/env python3
"""scrub.py — Pre-push scan for sensitive patterns.

Scans staged changes, tracked files, or specific paths against regex
patterns defined in patterns.txt. Reports matches with file, line number,
and matched pattern.

Usage:
    python scrub.py [diff|full|range|<path>] [--project-root <dir>] [--rev-range A..B]

Modes:
    diff   (default) Scan only added lines from git diff (staged changes).
    full   Scan all tracked files via git ls-files.
    range  Scan added lines in each commit of a range. Requires --rev-range.
    <path> Scan the specified file or directory.

Exit codes:
    0  Clean — no matches found.
    1  Matches found — review required.
    2  Could not scan. Callers gating on this MUST treat >=2 as a block, not a pass.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Exact repo-relative paths, matched by equality or directory prefix -- never by
# bare endswith, which would silently exclude any file named e.g.
# "prod-patterns.txt" and hand anyone a one-rename evasion.
SELF_EXCLUSIONS = {
    ".codex/explicit/scrub/patterns.txt",
    ".state/memory/user.md",
}

# Scrub reports embed matched lines verbatim, so a report is itself a plaintext
# secret store that matches its own patterns. Excluding the directory stops
# path-mode runs from re-reporting every prior run's findings forever.
SELF_EXCLUDED_DIRS = (
    ".state/tests/explicit/scrub/",
)

# A line carrying this marker is skipped. Without an escape hatch the only
# response to a false positive is `git push --no-verify`, which becomes habit
# and disables the gate for real secrets too.
ALLOWLIST_PRAGMA = "scrub:allow"

# Lines longer than this are not scanned. Bounds worst-case regex cost on
# machine-generated content (single-line SQL hex blobs, minified assets); a
# credential needing >2 KB of context is not what these patterns detect.
MAX_LINE_LENGTH = 2000

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
    """Return True if file_path should be excluded from scanning.

    Pure string work, no filesystem calls. The previous implementation resolve()'d
    every path -- ~4 ms per call on this 9p mount -- and was invoked once per added
    line, which made a large diff take minutes and a pre-push hook look hung.

    Matching is by exact repo-relative path or directory prefix. A bare endswith
    would exclude any file merely named "...patterns.txt" and hand anyone a
    one-rename evasion.
    """
    normalized = file_path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if Path(normalized).suffix.lower() in BINARY_EXTENSIONS:
        return True
    if normalized in SELF_EXCLUSIONS:
        return True
    return any(normalized.startswith(d) for d in SELF_EXCLUDED_DIRS)


def scan_line(line: str, patterns: list[re.Pattern]) -> list[re.Pattern]:
    """Return the patterns matching this line, honouring the allowlist pragma."""
    if len(line) > MAX_LINE_LENGTH or ALLOWLIST_PRAGMA in line:
        return []
    return [p for p in patterns if p.search(line)]


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


def _diff_header_path(line: str) -> str | None:
    """Extract the post-image path from a '+++' diff header, or None.

    git quotes paths containing non-ASCII, quotes, backslashes or control chars
    (core.quotePath defaults to true), emitting '+++ "b/caf\\303\\251.md"'. A bare
    startswith("+++ b/") test misses those entirely, so their added lines were
    attributed to the previous file or dropped -- a silent scanning gap.
    """
    if not line.startswith("+++ "):
        return None
    rest = line[4:]
    if rest.startswith('"') and rest.endswith('"') and len(rest) > 2:
        # C-quoted. Decode the escapes so the path matches exclusion entries.
        body = rest[1:-1]
        try:
            body = body.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        rest = body
    if rest == "/dev/null":
        return None
    if rest.startswith("b/"):
        rest = rest[2:]
    # git appends a tab before trailing metadata on paths containing spaces.
    return rest.split("\t", 1)[0]


def parse_diff(diff_output: str, patterns: list[re.Pattern]) -> list[dict]:
    """Scan added lines in a unified diff."""
    matches: list[dict] = []
    current_file: str | None = None
    file_excluded = True   # nothing is scanned before the first file header
    line_number = 0
    after_minus_header = False

    for line in diff_output.splitlines():
        # In unified diff a '+++' header always immediately follows its '---'
        # counterpart. Pairing them is what distinguishes a header from an added
        # line whose own content happens to begin with '++'.
        if line.startswith("--- "):
            after_minus_header = True
            continue
        if after_minus_header and line.startswith("+++ "):
            after_minus_header = False
            current_file = _diff_header_path(line)
            # Evaluated once per file, not once per added line. A None path means
            # /dev/null (deletion), which has no post-image to scan.
            file_excluded = current_file is None or is_excluded(current_file)
            continue
        after_minus_header = False
        if line.startswith("@@ "):
            hunk_match = re.search(r"\+(\d+)", line)
            if hunk_match:
                line_number = int(hunk_match.group(1)) - 1
            continue
        # An added line whose own content begins with "++" still starts with "+"
        # and must be scanned; only the diff's own "+++" header is metadata, and
        # that is already consumed above.
        if line.startswith("+"):
            line_number += 1
            if current_file and not file_excluded:
                content = line[1:]
                for pattern in scan_line(content, patterns):
                    matches.append({
                        "file": current_file,
                        "line": line_number,
                        "pattern": pattern.pattern,
                        "content": content.strip(),
                    })
        elif not line.startswith("-") and not line.startswith("\\"):
            line_number += 1

    return matches


def scan_diff(project_root: Path, patterns: list[re.Pattern]) -> list[dict]:
    """Scan added lines in the staged diff. Pre-commit scope."""
    return parse_diff(
        git_run(["diff", "--cached", "-U0", "--diff-filter=ACMRT"], project_root),
        patterns,
    )


def validate_rev_range(rev_range: str) -> str:
    """Validate a rev specification and return it unchanged.

    Accepts 'A..B' (commits in B but not A) or a bare 'B' (every commit reachable
    from B). The bare form is needed when the oldest new commit is a root commit
    and therefore has no parent to use as a base.

    Components are rejected if empty or option-shaped: these values reach git as
    arguments, and something like '--output=/tmp/x' would make git write the patch
    to that file and emit nothing on stdout, which a scanner reads as an empty
    diff and reports as clean.
    """
    if rev_range.count("..") > 1:
        print(f"--rev-range must be 'A..B' or 'B', got {rev_range!r}", file=sys.stderr)
        sys.exit(2)
    for part in rev_range.split(".."):
        if not part or part.startswith("-"):
            print(f"--rev-range component empty or option-like: {part!r}", file=sys.stderr)
            sys.exit(2)
    return rev_range


def scan_range(project_root: Path, patterns: list[re.Pattern], rev_range: str) -> list[dict]:
    """Scan added lines in EACH COMMIT of a range. Pre-push scope.

    `git diff A..B` is a two-endpoint tree comparison, not a range walk. Content
    added in one commit and removed in a later one nets out to nothing, while the
    push still delivers the intermediate blob to the remote permanently and
    `git show <sha>:<path>` retrieves it forever. That is the commonest way a
    secret escapes -- commit, notice, delete, commit the fix, push -- so this
    walks each commit individually instead.

    (Separately: the staged diff is empty by push time, so `diff` mode cannot
    serve as a push gate at all.)

    Merge commits emit no diff here by design; their content arrives via the
    parents' own commits, which are in this list whenever they are new. Content
    introduced only in a merge resolution -- an "evil merge" -- is not covered.
    """
    spec = validate_rev_range(rev_range)
    revs = git_run(
        ["rev-list", "--reverse", "--topo-order", "--end-of-options", spec],
        project_root,
    ).split()

    matches: list[dict] = []
    for sha in revs:
        diff = git_run(
            ["diff-tree", "-p", "-r", "--root", "-U0", "--no-commit-id",
             "--diff-filter=ACMRT", "--end-of-options", sha],
            project_root,
        )
        matches.extend(parse_diff(diff, patterns))
    return matches


def scan_file(file_path: Path, rel_path: str, patterns: list[re.Pattern]) -> list[dict]:
    """Scan a single file against all patterns."""
    matches: list[dict] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return matches

    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern in scan_line(line, patterns):
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
                        help="Scan mode: 'diff' (default), 'full', 'range', or a file/directory path.")
    parser.add_argument("--project-root", type=Path, default=None,
                        help="Project root directory (defaults to cwd).")
    parser.add_argument("--rev-range", default=None,
                        help="Commit range for 'range' mode, e.g. abc123..def456. Used by the pre-push hook.")
    args = parser.parse_args()

    project_root = (args.project_root or Path.cwd()).resolve()
    patterns_file = SCRIPT_DIR / "patterns.txt"

    if not patterns_file.is_file():
        print(f"Pattern file not found: {patterns_file}", file=sys.stderr)
        sys.exit(2)

    patterns = load_patterns(patterns_file)
    if not patterns:
        # Exit 2, never 0. A truncated or fully commented-out patterns.txt would
        # otherwise report "clean" and pass every push in every repo that
        # inherits this codex -- fail-open in a fail-closed boundary.
        print("No patterns loaded from patterns.txt — refusing to report clean.",
              file=sys.stderr)
        sys.exit(2)

    mode = args.mode
    if args.rev_range and mode != "range":
        # Silently ignoring it means dropping the word 'range' from a caller turns
        # the gate into an unconditional pass: mode falls back to 'diff', the
        # staged diff is empty at push time, and the result is "PASS: clean".
        print(f"--rev-range is only valid in 'range' mode (got mode {mode!r})",
              file=sys.stderr)
        sys.exit(2)

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
    elif mode == "range":
        if not git_available:
            print("range mode requires a git repository.", file=sys.stderr)
            sys.exit(2)
        if not args.rev_range:
            print("range mode requires --rev-range.", file=sys.stderr)
            sys.exit(2)
        matches = scan_range(project_root, patterns, args.rev_range)
        mode = f"range:{args.rev_range}"
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
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - deliberate catch-all
        # An uncaught traceback exits 1, and a gating caller reads 1 as "secret
        # found" -- so a bad regex, an unreadable .state/ or a KeyboardInterrupt
        # would print "BLOCKED: secret-shaped content" and send the reader
        # hunting for a secret that does not exist. Anything unexpected is
        # "could not scan", which still blocks but says so honestly.
        print(f"scrub: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
