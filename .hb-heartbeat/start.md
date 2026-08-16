---
version: 1
short-desc: Heartbeat — nightly unattended backlog execution (window → GO flag → tick → runner → worker → ~inbox)
---

# Heartbeat (HB)

> **KILL SWITCH: `rm .hb-heartbeat/state/GO`** — everything stops at the next tick (≤ 5 min). A running
> worker finishes its current item and cannot re-arm; nothing relaunches. Re-arm only by the window
> detector at the next scheduled open (or `hb.py window open` by hand).

Nightly, unattended, one item at a time: pop one **approved** item from a project's `~outbox/hb/`, work it on
a branch in a throwaway worktree, push + open a PR (never merge), and drop an outcome in that project's
`~inbox/hb/<ITEM>/` for the human in the morning. Deterministic control plane; the LLM only ever runs as the
sandboxed *worker* and never touches the flag or the queues.

| file | role |
|---|---|
| `spec.md` | the design contract (invariants I1–I7, components, flag states, terminus table) |
| `plan.md` | decisions delta vs spec + build order + verified facts |
| `config.json` | defaults (window 00:30–06:30, tick 5m, item cap 90m, count cap 1, model sonnet); instance override `state/config.json` |
| `hb.py` | control plane: `tick`, `window open|close`, `install`, `approve`, `status`, `kill`, `summary` |
| `runner.py` | one item: quota gate → pop → provision worktree → spawn credential-less worker via `cboot.py --project SANDBOX --exec-file` → harvest → **push + PR (runner-side)** → outcome → release |
| `prompt-worker.md` | the worker's brief (rules, outcome contract); rendered per item |
| `hb-guard.sh` / `hb-guard.py` | sandbox-only PreToolUse(Bash) hook: live-tree path containment, git/gh allowlists, wrapper peeling, credential tokens |
| `templates/` | `~outbox/start.md` (**item frontmatter spec**), `~inbox/start.md`, `item.md` — materialized to every root by `hb.py install` |
| `win/register-tasks.ps1` · `win/run-tick.ps1` | Task Scheduler: `hb-window-open` (wake), `hb-window-close`, `hb-tick` (repeats only inside the window; wrapper holds a keep-awake power request) → `wsl.exe -d claude-context -u KMc -- python3 …/hb.py …` |
| `tests/test_hb.py` | 42 zero-quota tests (flag machine, claim race, sweeps, pop order, fake-worker E2E incl. runner push to a local bare origin, crash-as-corpse, window bounds, guard allow/block corpus) — `python3 .hb-heartbeat/tests/test_hb.py` |
| `state/` | runtime (untracked): `GO`, `night.json`, `quota.json`, `last-tick`, `diag/`, `log/hb.log` — see `state/start.md` |
| `sandbox/<ITEM>/` | runtime worktrees (untracked); removed after harvest, kept only on an unexpected terminus |

## Daily use

```
python3 .hb-heartbeat/hb.py approve BL-07 [--priority 0-9] [--project <root>]   # backlog section -> ~outbox/hb/BL-07.md
python3 .hb-heartbeat/hb.py status                                              # flag, tonight, queues, quota
python3 .hb-heartbeat/hb.py kill                                                # = rm state/GO
python3 .hb-heartbeat/hb.py window open --force                                 # arm by hand outside the window (plain `open` refuses)
python3 .hb-heartbeat/hb.py install [--dry-run]                                 # mailboxes at every root in roots.db (idempotent)
/checkWinTasks hb-                                                              # scheduler health
```

Morning review: `~inbox/hb/night-<date>.md` (always written, even for a quiet night) and `~inbox/hb/<ITEM>/outcome.md`
(terminus + qa_result + branch + PR). Merge awake, by hand. Bad → prune the branch or re-approve with a better brief.

## Controls on the worker (what stops a 3am disaster)

**Structural (not prompt, not pattern-matching):**
- The worker has **no git or gh credentials**: `GH_CONFIG_DIR` points at an empty dir, inherited credential helpers are
  reset, `GIT_TERMINAL_PROMPT=0`. A push from inside the sandbox fails with "could not read Username"; `gh` is logged out.
  Verified 2026-08-16.
- **The runner publishes**, not the worker: after an expected terminus it pushes `refs/heads/hb/<ITEM>` only (the live
  repo's scrub pre-push hook is the gate) and runs `gh pr create`. Nobody merges.
- Hard-rooted sandbox worktree (`cboot.py --project SANDBOX --exec-file`), fresh per item, discarded after harvest; only `.state/work` is copied in; `WebFetch`/`WebSearch` denied by default (`worker_web`).
- PR title/body (worker text) pass the codex scrub before `gh pr create`; otherwise withheld.

**Guards (defense in depth — allowlist-oriented, unknown shapes fail closed):** apex deny + `remote-guard.sh`
(inherited); sandbox `settings.local.json` deny overlay + `hb-guard.sh` (path containment to the sandbox for any Bash
token that resolves into the live tree; git subcommand allowlist with no global options; gh read-only `pr view|list|
diff|status|checks`; wrapper peeling for env/command/eval/xargs/`bash -c`/`$(…)`/`<(…)`/shell keywords; glob expansion (fail closed toward the apex); alias mounts (`/mnt/d/claudette`) + Windows paths/.exe; `unset/export/env -u` of protected vars; git exec options (`rebase -x`, `bisect run`, `-c core.pager`…); credential-file tokens; non-ASCII executables). Time cap (`CBOOT_EXEC_TIMEOUT` + process-group kill), count cap, GO flag.

**Honest residuals:** the worker runs as OS user KMc, so anything KMc can read on disk (e.g. `~/.config/gh/hosts.yml`)
is readable in principle — the guard blocks the obvious spellings, a script *file* that shells out is not inspected, and the
credential strip is environment-only (reversible by an `unset` the guard doesn't see, e.g. from inside such a script).
Real separation = a dedicated OS user or a dedicated GitHub identity for the worker (user decision, not built).
GitHub cannot tell worker from user on one account, so "no merge" is guard-level on the gh side and structural only via
the credential strip.

## Rollout (spec §13)

Night 1: one hand-approved item, `count_cap: 1`. Nights 2–5: `count_cap: 2`, watch corpse/orphan rate + diff quality.
Then quota-bound. Quota gate is stale-by-nature in v1 (statusLine sink) — see `plan.md` D5.
