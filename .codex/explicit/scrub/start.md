---
version: 2
short-desc: Scan for secrets and PII before pushing
runtime: python
reads:
  - "./patterns.txt"
  - "^/.state/"
writes:
  - "^/.state/tests/explicit/scrub/"
---

# scrub

Pre-push scan for sensitive patterns. Checks staged changes (or specified paths) against a pattern file and reports matches.

## Usage

`scrub` — scan staged git changes (diff mode)
`scrub full` — scan all tracked files
`scrub <path>` — scan a specific file or directory

## Modes

### Diff (default)
Scans only changed lines (`git diff`). Used by the pre-push hook and for quick manual checks.

### Full
Scans all tracked files. Use for periodic audits or before first push of a new project.

## Pattern File

`patterns.txt` (sibling file) contains one regex per line. Lines starting with `#` are comments. Patterns are matched against added lines (diff mode) or all lines (full mode).

## Self-Exclusions

These files are excluded from scanning to avoid self-matches:
- `patterns.txt` (contains the patterns themselves)
- `.state/memory/user.md` (legitimate identity store)

## Automated Enforcement

A pre-push git hook calls scrub in diff mode. Blocks the push if any patterns match. Override with `git push --no-verify` (conscious decision).

**Required git config** (set once after `git init`):
```
git config core.hooksPath .codex/explicit/scrub/hooks
```

## Output

Writes scan results to `.state/tests/explicit/scrub/`. Reports matches with file, line number, and matched pattern. Exit status: 0 = clean, 1 = matches found.

## Execution

```
python .codex/explicit/scrub/scrub.py [diff|full|<path>] --project-root ^
```

1. Determine mode (diff, full, or path-specific).
2. Run `scrub.py` with the appropriate mode.
3. Report findings to user. If matches found, advise on remediation.
