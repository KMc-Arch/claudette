---
version: 1
---

# state (Heartbeat runtime)

Untracked runtime for the nightly runner. **KILL SWITCH: delete `GO`.**

| entry | writer | meaning |
|---|---|---|
| `GO` | window detector issues; tick claims; runner annotates/releases; human deletes | permission token: absent / `status: go` / `status: inflight` (+ pid, pid_start, claimed_at, transcript_path, item_id) |
| `night.json` | hb.py | tonight's ledger: night, opened_at, closes_at, count_cap, runs[], corpses[], notes[], closed |
| `last-tick` | hb.py tick | UTC timestamp of the last tick — proof the schedule runs even on quiet nights |
| `RESULT/`, `PROMPT.md`, `gh-empty/` | (inside a sandbox's copy of this dir) | worker I/O — never in the live state dir |
| `quota.json` | statusline.sh (every interactive turn) | last `rate_limits` seen + `written_at` — stale-by-nature; the runner reads it pre-pop |
| `config.json` | human (optional) | instance overrides of `../config.json` |
| `diag/` | runner / detector | unexpected-failure records: corpse, quota-exhausted, unexpected-terminus, provision-failed, runner-crash |
| `log/hb.log` | hb.py + runner.py | control-plane log; quiet ticks (GO absent) write nothing |
