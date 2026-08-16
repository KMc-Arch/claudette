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
| `runner.py` | one item: quota gate → pop → provision worktree → spawn worker via `cboot.py --project SANDBOX --exec-file` → harvest → release |
| `prompt-worker.md` | the worker's brief (rules, outcome contract); rendered per item |
| `hb-guard.sh` / `hb-guard.py` | sandbox-only PreToolUse hook: no PR merge/close/ready, no remote branch deletion, no main checkout, no update-ref/worktree |
| `templates/` | `~outbox/start.md` (**item frontmatter spec**), `~inbox/start.md`, `item.md` — materialized to every root by `hb.py install` |
| `win/register-tasks.ps1` | Task Scheduler: `hb-window-open`, `hb-window-close`, `hb-tick` → `wsl.exe -d claude-context -u KMc -- python3 …/hb.py …` |
| `tests/test_hb.py` | 30 zero-quota tests (flag machine, claim race, sweeps, pop order, fake-worker E2E, guard) — `python3 .hb-heartbeat/tests/test_hb.py` |
| `state/` | runtime (untracked): `GO`, `night.json`, `quota.json`, `diag/`, `log/hb.log` — see `state/start.md` |
| `sandbox/<ITEM>/` | runtime worktrees (untracked); removed after harvest, kept only on an unexpected terminus |

## Daily use

```
python3 .hb-heartbeat/hb.py approve BL-07 [--priority 0-9] [--project <root>]   # backlog section -> ~outbox/hb/BL-07.md
python3 .hb-heartbeat/hb.py status                                              # flag, tonight, queues, quota
python3 .hb-heartbeat/hb.py kill                                                # = rm state/GO
python3 .hb-heartbeat/hb.py install [--dry-run]                                 # mailboxes at every root in roots.db (idempotent)
/checkWinTasks hb-                                                              # scheduler health
```

Morning review: `~inbox/hb/night-<date>.md` (always written, even for a quiet night) and `~inbox/hb/<ITEM>/outcome.md`
(terminus + qa_result + branch + PR). Merge awake, by hand. Bad → prune the branch or re-approve with a better brief.

## Controls on the worker (what stops a 3am disaster)

apex deny + `remote-guard.sh` (inherited) · sandbox `settings.local.json` deny overlay + `hb-guard.sh` (runner-written) ·
git worktree semantics (`main` is checked out in the live tree, so the sandbox cannot check it out or `branch -f` it) ·
`/scrub` before push (worker rule) · time cap (`CBOOT_EXEC_TIMEOUT`) · count cap · GO flag.
Honest limit: the worker uses your `gh` token — merge is denied by guards, not made impossible.

## Rollout (spec §13)

Night 1: one hand-approved item, `count_cap: 1`. Nights 2–5: `count_cap: 2`, watch corpse/orphan rate + diff quality.
Then quota-bound. Quota gate is stale-by-nature in v1 (statusLine sink) — see `plan.md` D5.
