# Heartbeat (HB) — Build Plan (overnight execution)

Source spec: `spec.md` (this folder; moved from `~inbox/HEARTBEAT-SPEC.md` 2026-08-15).
Status: built overnight 2026-08-15/16 on `feature/hb`; two mileqa rounds + fixes landed; see §4 for what is verified live.

---

## 0. Decisions delta vs spec (ratified in chat 2026-08-15)

| # | Spec said | Decided | Why |
|---|---|---|---|
| D1 | one "orchestrator" that annotates GO, pops, works, writes inbox | **runner** (deterministic Python) does every live-state mutation; **worker** (`claude -p`) touches only its sandbox + its branch + remote PR | worker is hard-rooted in the sandbox — containment/gravity forbid live `.state` writes; LLM is never a state actor (extends I7; makes §5.7 structural) |
| D2 | worktree *or* clone; sandbox "distinct location" | **git worktree in-root**: `<project>/.hb-heartbeat/sandbox/<ITEM>/` (was `.tmp/sandbox/hb/`; moved with D13) | in-root = manageable/testable from a fenced session; purge-aware; branch lands directly in the live repo (spec O3 dissolves). Verified `git worktree add` works on the 9p mount 2026-08-15. |
| D3 | I2 local-only, no push, no PR | **push feature branch + `gh pr create` ALLOWED — done by the RUNNER; the WORKER has no credentials; merge/close/enact DENIED** | user ruling (push+PR). mileqa round 1 (2026-08-16) showed token-shape guards are bypassable, so authority moved out of the worker: `GH_CONFIG_DIR` empty + credential helpers reset in the worker env (verified: push fails, gh logged out); runner pushes `refs/heads/hb/<ITEM>` only and creates the PR; live scrub pre-push hook is the gate. Guards remain as depth (allowlist hb-guard). Residual: same OS user → disk-readable token; GitHub cannot distinguish worker/user on one account. |
| D4 | `.state/hb/{outbox,inflight,inbox}` at apex → (superseded: `.state/hb` → `.hb-heartbeat/state`) | **per-project mailboxes**: items in `<project>/~outbox/hb/<ITEM>.md`, claim = atomic move to `<project>/~outbox/hb/inflight/`, outcome = `<project>/~inbox/hb/<ITEM>/` (pause folder + `outcome.md`) | projects = claudette's children; each is its own repo, gets its own queue; matches the existing `~outbox/<target>/` handoff convention (`~majel/~outbox`) with target = `hb`; `~inbox` already the human-facing drop at apex. GO/quota/diag/log at apex `.hb-heartbeat/state/`. |
| D5 | orchestrator reads fresh quota via its own statusLine | quota.json is **stale-by-nature** in v1 (headless `-p` almost certainly runs no statusLine — verify in pre-flight); gate = last reading + age + `resets_at`; **count cap governs nights 1–5** | spec §13 already count-capped; don't overbuild until measured |
| D6 | tick spawns orchestrator | **tick execs runner in-process** (foreground; PID = own PID); Task Scheduler `MultipleInstances=IgnoreNew` + `ExecutionTimeLimit` as belt | sidesteps WSL "VM exits when last client leaves" uncertainty |
| D7 | O1 open | per-item wall-clock cap (default 90 min); tick refuses to spawn if `now + cap > window_closes_at`; overrun at close → let finish, log, never kill | |
| D8 | O5 open | window-close **always** writes `<apex>/~inbox/hb/night-<date>.md`: items run, corpses, orphans, quota reading, stale `hb/*` branches | positive "ran and did nothing" signal |
| D9 | §10.5 branch expiry | no auto-delete v1; nightly summary lists stale branches | |
| D10 | O6 feed source | backlog → `BL-nn` ids; branch `hb/<project-slug>/<ITEM>` (apex: `hb/BL-07`) | derivable, PR-titleable |
| D11 | night-1 item | **BL-07** (`00-preboot` row missing from `.codex/start.md` Priority Tiers table) | doc-only, one file, verifiable — plumbing test |
| D12 | claim primitive | file rename (`GO` → `GO.claim.<pid>` → rewrite → `GO`); un-mutate only if `GO` exists AND pid matches — never recreate from absent | 9p: file rename fine, avoid hot-dir renames (memory `reference_9p_rename_ghost`) → items are single files, not folders |
| D13 | code home | **`^/.hb-heartbeat/`** — max content in one git-tracked folder (spec, plan, code, templates, tests, win/); runtime `state/` + `sandbox/` untracked via its own `.gitignore`; `.codex/explicit/hb/start.md` is a 5-line shim so `/hb` exists (user ruling 2026-08-15, superseding `.codex/explicit/hb/`) | one place; portable; `~` mailboxes stay at project roots (children need theirs there) |
| D14 | permissions | worker gets the apex `settings.local.json` broad allows via `child_propagate` merge (no `--dangerously-skip-permissions`; cboot's passthrough allowlist is `--resume`/`--model` only); hooks fire in headless (verified: hb-guard block message returned by a real worker 2026-08-16) | reuse the mileqa'd dispatch channel as-is |
| D15 | worker model + bound | per-item `model:` frontmatter, default `sonnet`; wall-clock cap = min(item `time_cap_min`, config `item_cap_min`) via `CBOOT_EXEC_TIMEOUT` + process-group kill (no `--max-turns`: not passable through cboot) | cost; mileqa's 3-round/2-coda cap is real |

Deliberately unchanged from spec: I1, I3, I4, I5, I6, I7; §6 detector; §8.4 orphan sweep (attempts ≤3); §10.2 terminus table; §11.3 exhaustion-is-unexpected + dumb diag write; §13 rollout (count cap 1 → 2 → quota-bound). **Extended, not contradicted:** §5.3 gains three runner transitions (quota gate closed pre-pop → inflight→go and retry next tick; queue empty → inflight→absent; tick removes an expired `go`) and a `pid_start` field; §7 tick also touches `state/last-tick` and refuses within `item_cap_min` of close.

---

## 1. Project delta (what changes in the tree) — as built

```
/mnt/claudette
├── .hb-heartbeat/                                   [NEW, git-tracked]
│   ├── start.md · spec.md · plan.md · config.json
│   ├── hb.py · runner.py · hb-guard.sh · hb-guard.py · prompt-worker.md
│   ├── templates/{~outbox/start.md (item frontmatter spec), ~inbox/start.md, item.md}
│   ├── win/register-tasks.ps1
│   ├── tests/{test_hb.py, fake_worker.py}
│   ├── .gitignore  (state/* except start.md; sandbox/)
│   ├── state/  GO · night.json · quota.json · config.json(override) · diag/ · log/     [runtime]
│   └── sandbox/<ITEM>/  worktree; .state/{memory,work,prefs.json} copied; .claude/settings.local.json overlay; .hb-heartbeat/state/RESULT/  [runtime]
├── .codex/explicit/hb/start.md                       [NEW] 5-line shim → /hb
├── .codex/…/statusline/statusline.sh                 [MOD] rate_limits → <project_dir>/.hb-heartbeat/state/quota.json (atomic, only if dir exists)
├── .gitignore                                        [MOD] +!/.hb-heartbeat/ +!/.hb-heartbeat/**
├── ~outbox/{start.md, hb/, hb/inflight/} · ~inbox/{start.md, hb/}   [apex + every root via `hb.py install`; untracked]
└── (children) <root>/.hb-heartbeat/sandbox/<ITEM>/  created at provision only for items whose project is that root
```

Unchanged: `.state/`, `.tmp/`, `.templates/`, `.codex/settings.json`, `checkWinTasks`.

---

## 2. Sandbox controls (D3) — as built after mileqa round 1

| Layer | Where | What |
|---|---|---|
| **credential strip (structural)** | `runner.worker_env` | `GH_CONFIG_DIR`=empty dir, `GH_TOKEN`/`GITHUB_TOKEN` removed, `credential.helper=` + `core.askPass=/bin/false` via `GIT_CONFIG_*`, `GIT_TERMINAL_PROMPT=0` → worker cannot push or use gh |
| **runner publishes** | `runner.publish` | `git push -u origin refs/heads/hb/<ITEM>:refs/heads/hb/<ITEM>` from the live repo (scrub pre-push hook fires) then `gh pr create --base main`; blocked push → reported in outcome, never forced |
| apex deny + remote-guard (inherited) | `.codex/settings.json`, hooks | force push, main push, remote config, gh api/issue/release |
| sandbox deny overlay | `<sandbox>/.claude/settings.local.json` | prefix denies for the obvious forms (belt) |
| hb-guard.sh/.py | same overlay, PreToolUse(Bash) | live-tree path containment (case-insensitive, alias mounts, mentions anywhere in a token, `$VAR` paths refused, globs fail-closed); git global-option ban + subcommand allowlist + exec-option bans; gh read-only allowlist; wrapper/keyword peeling; `unset/export/env -u`; credential/env tokens; Windows interop; non-ASCII exe |
| git worktree semantics | — | *not* claimed as a control any more (live HEAD may not be main); the branch/checkout rules in hb-guard cover it |
| time/count caps | runner + tick | `min(item, config)` cap; process-group kill (also after a normal return); count cap counts crashes too |
| egress scrub | `runner.publish` | commit messages + touched paths + PR title scrubbed BEFORE the push (push withheld on a hit); PR body scrubbed before `gh pr create` (withheld on a hit); `scrub:allow` counts as a hit; long lines folded; `scope` breach withholds the push |
| worker web | sandbox overlay | `WebFetch`/`WebSearch` denied unless `worker_web: true` (exfiltration surface); only `.state/work` (not memory) is copied into the sandbox |
| alias mounts | `runner.apex_aliases` → `HB_APEX_ALIASES` | hb-guard's containment covers `/mnt/d/claudette` etc. and refuses Windows drive paths / `.exe` interop |

Honest limits: same OS user (disk-readable token, BL-44); the credential strip is env-only (hb-guard refuses `unset/export/env -u` of protected names and git exec options, but a script *file* that shells out is not inspected); a double-forking script escapes the process-group kill; GitHub can't tell worker from user on one account.

## 3. Build order (each step: build → test → commit on `feature/hb`)

| Step | Deliverable | Test |
|---|---|---|
| B0 | move spec → `.state/work/spec-heartbeat.md`; `.state/hb/start.md`; templates; `.state/start.md`, `.tmp/start.md` edits | files exist; git status shows expected |
| B1 | `hb.py` flag machine + tick + window open/close + sweeps + summary + config | unit: every §5.3 transition; claim race (two concurrent claims → exactly one wins); corpse (dead PID) & orphan (attempts++ / ≥3 → inbox); kill switch mid-flight → no recreate; spawn refusal near close |
| B2 | `hb.py install/approve/status/kill` | install idempotent over roots.db (dry-run first, then live); approve BL-07 produces `~outbox/hb/BL-07.md` from backlog text |
| B3 | `runner.py` provision + spawn + harvest + cleanup | fake worker (`HB_WORKER_CMD` env → script that writes RESULT) end-to-end, zero quota; worktree removed + pruned; outcome folder present; branch exists |
| B4 | `hb-guard.sh` + overlay writer | JSON-fed hook tests: every denied form blocked, `git push origin hb/BL-07` + `gh pr create` allowed; remote-guard adversarial pass (spec §13.1) |
| B5 | statusline sink | feed sample stdin → quota.json written with ts; no `.state/hb` dir → no write |
| B6 | `prompt-worker.md`, `start.md`, `README.md` | read-through; kill switch line 1 |
| B7 | `win/register-tasks.ps1` (generate; attempt registration via interop; else USER runs) | `checkWinTasks hb-` shows 3 tasks |
| B8 | **/mileqa** on the HB build (scope: `.codex/explicit/hb/`, statusline diff, templates) | exit CLEAN or HELD with residual list |
| B9 | **Supervised night-1 E2E**: `hb window open` (test window) → `hb tick` → real worker on BL-07 → PR + `~inbox/hb/BL-07/` | PR exists on `hb/BL-07`; outcome parses; GO back to `go`; worktree gone |
| B10 | handoff report → `~inbox/hb/night-<date>.md` + chat | |

Pre-flight before B9 (spec §13.1 + additions): remote-guard adversarial ✔(B4) · containment resolves sandbox root ✔ · quota.json path ✔ · tasks visible to checkWinTasks · kill switch documented · **does statusLine fire under `-p`?** · **do deny rules apply under `--dangerously-skip-permissions`?** · does `git` honor `GIT_CONFIG_*` env (used only if we add pushurl override — currently NOT used since push is allowed).

---

## 4. Verified this evening (2026-08-15)

- `git worktree add` on `/mnt/claudette` (9p): works.
- Windows interop from WSL: `/mnt/c/Windows/System32/wsl.exe`, `…/powershell.exe` callable by absolute path (not on PATH in bg session). Distro = `claude-context`.
- `gh auth status`: logged in as KMc-Arch, scopes `repo, workflow, gist, read:org`. origin = `https://github.com/KMc-Arch/claudette.git`.
- `claude -p … --output-format json` works headless from WSL; returns `session_id` (transcript path derivable → fills the GO `transcript_path` blank).
- Python 3.12.3.

## 5. Open (carry)

O2 sentinel ingestion; O4 conflicting diffs; per-model weekly cap blind spot (§11.2); child-project provisioning: children's `.claude/` comes from `child_propagate`, worktree needs a copy — build in B3 as `--project` path, exercise on apex only for night 1.
