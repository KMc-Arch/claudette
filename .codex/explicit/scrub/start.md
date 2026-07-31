---
version: 5
short-desc: Scan for secrets and PII before pushing
runtime: python
reads:
  - "./patterns.txt"
  - "^/.state/"
writes:
  - "^/.state/tests/explicit/scrub/"
---

# scrub

Scan for sensitive patterns. Checks a diff, a commit range, the tracked set, or an arbitrary path against a pattern file and reports matches.

## Usage

`scrub` — scan staged git changes (diff mode)
`scrub full` — scan all tracked files
`scrub range --rev-range A..B` — scan added lines across a commit range
`scrub <path>` — scan a specific file or directory

## Modes

### Diff (default)
Scans added lines in the **staged** diff (`git diff --cached`). Pre-commit scope — useful before committing, and for quick manual checks.

### Range
Scans added lines in **each commit** of a range, walking `git rev-list` and running `git diff-tree` per commit. Accepts `A..B` or a bare `B` (every reachable commit — needed when the oldest new commit is a root commit with no parent). This is what the pre-push hook uses.

**Two traps this mode exists to avoid, both of which produce a gate that passes everything:**

- **Diff mode cannot be a push gate.** By push time the changes are committed and the index is empty, so `git diff --cached` returns nothing and the scan passes unconditionally.
- **`git diff A..B` cannot be a push gate either.** It is a two-endpoint *tree* comparison, not a range walk. Content added in one commit and removed in a later one nets out to nothing, while the push still delivers the intermediate blob and `git show <sha>:<path>` retrieves it forever. That is the commonest way a secret escapes — commit, notice, delete, commit the fix, push. Measured against this repo's own history: `.codex/explicit/majel/start.md` showed **0** added lines under an endpoint diff and **174** under the per-commit walk.

Merge commits emit no diff of their own; their content arrives via the parents' commits, which are in the list whenever they are new. Content introduced only in a merge resolution — an "evil merge" — is not covered.

### Full
Scans all tracked files. Use for periodic audits or before first push of a new project.

**`full` is a push gate, not a copy gate.** It reads `git ls-files`, so anything gitignored is invisible to it — including every credential file (`.env`, `*.pem`, `*.key`). Under this instance's inverted `.gitignore` the tracked set is the framework skeleton, a small fraction of the tree.

If the question is "is it safe to copy this tree somewhere else" — a backup, a bundle, a cloud sync — use **path mode**. On 2026-07-29 a `full` scan returned PASS while four live `.env` files were mirrored into cloud storage.

## Pattern File

`patterns.txt` (sibling file) contains one regex per line; `#` starts a comment.

Name-based patterns constrain the **value**, not just the name: it must be ≥8 characters from a credential charset, contain a digit, and not begin with a template sigil (`$ < { % *`). That one requirement is what separates `password: str`, `api_key=os.environ[...]`, `PASSWORD=changeme` and `${{ secrets.X }}` from a real credential. The trade-off is that a purely alphabetic passphrase is missed by the name patterns — provider tokens are covered independently by format.

Every repetition is bounded. An unbounded `[a-z0-9_]*` before a literal is O(n²): a single-line SQL hex blob cost 59 s at 128 KB and roughly an hour at 1 MB, with no timeout anywhere and fail-closed semantics, so Ctrl-C blocked the push too.

### Escape hatch

Put `scrub:allow` anywhere on a line to skip it. Without an escape hatch the only response to a false positive is `git push --no-verify`, which becomes habit and disables the gate for real secrets as well. Lines longer than 2,000 characters are also skipped — a credential needing that much context is not what these patterns detect.

## Self-Exclusions

Matched by **exact repo-relative path or directory prefix**, never by bare `endswith` — that would exclude any file merely named `…patterns.txt` and hand anyone a one-rename evasion.

- `.codex/explicit/scrub/patterns.txt` (contains the patterns themselves)
- `.state/memory/user.md` (legitimate identity store)
- `.state/tests/explicit/scrub/` — reports embed matched lines verbatim, so without this a path-mode run re-reports every prior run's findings and the match count grows monotonically

## Automated Enforcement (BDRY-03)

`hooks/pre-push` is the second defence layer on the Push boundary; this protocol, invoked by hand, is the first.

Git supplies the refs being pushed on stdin. For each, the hook resolves a commit range and runs `scrub range` over it:

- **branch deletion** (`local_sha` all zeros) — skipped, nothing to scan
- **new branch** (`remote_sha` all zeros) — bounded to commits no remote has yet, via `git rev-list --not --remotes`, so a first push does not re-scan all of history
- **otherwise** — `remote_sha..local_sha`

It **fails closed** on every path: missing `scrub.py`, absent python, no work tree (bare repo / `GIT_DIR`-only invocation), a failed `rev-list`, a scan error, or a scan exceeding the 120 s timeout. The block message distinguishes "found something" (exit 1) from "could not scan" (exit ≥2) — conflating them sends the reader hunting for a secret that is not there.

Exit-code contract: **0 clean, 1 matches found, ≥2 could not scan.** Any caller gating on this must treat ≥2 as a block. `scrub.py` wraps `main()` so an unexpected exception exits 2 rather than 1, because a bad regex or an unwritable `.state/` would otherwise be reported as a discovered secret.

Two subtleties worth keeping:

- The new-ref exclusion is scoped to **this** remote (`--remotes=<name>`). Bare `--not --remotes` subtracts everything reachable from *any* remote, so pushing an already-fetched branch onward to a second remote yielded an empty commit list — which then read as "nothing to scan" and skipped the ref entirely.
- The all-zero OID is matched by content, not against a 40-character literal, so new-branch and deletion detection still work in a SHA-256 repository.

Override deliberately with `git push --no-verify`.

**Required git config** (set once per clone — `core.hooksPath` is local, not committed):
```
git config core.hooksPath .codex/explicit/scrub/hooks
```

Two caveats:

- `core.hooksPath` **replaces the entire hooks directory** for the repo. Any other hook must live in `hooks/` alongside `pre-push`, or it silently stops running.
- On a drvfs/9p mount `git config` fails with `chmod on .git/config.lock: Operation not permitted`. Add the key by editing `.git/config` directly:
  ```
  [core]
      hooksPath = .codex/explicit/scrub/hooks
  ```

### Scope

This gate scans **diffs**, so it only ever sees tracked content. Gitignored credential files never appear in a diff and are out of scope here by construction — keeping those out of a *copied* tree is `/backup`'s `exclude_files` layer, not this one. Two boundaries, two controls.

## Output

Writes scan results to `.state/tests/explicit/scrub/`. Reports matches with file, line number, and matched pattern. Exit status: 0 = clean, 1 = matches found.

**Reports embed the matched line verbatim** (first 120 chars, see `format_report`). A report from a failing scan therefore *contains* the secrets it found, in a file under `.state/`. Treat `scrub-*.md` as sensitive: never sync, mirror, or bundle it. `/backup` excludes the pattern for this reason.

## Execution

```
python .codex/explicit/scrub/scrub.py [diff|full|range|<path>] --project-root ^
```

1. Determine mode (diff, full, range, or path-specific).
2. Run `scrub.py` with the appropriate mode. `range` additionally requires `--rev-range A..B`.
3. Report findings to user. If matches found, advise on remediation.
