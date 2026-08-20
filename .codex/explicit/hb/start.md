---
version: 1
short-desc: Heartbeat — nightly unattended backlog runner (status/approve/kill/install)
reads:
  - "^/.hb-heartbeat/"
writes:
  - "^/.hb-heartbeat/state/"
  - "^/~outbox/hb/"
---

# hb

Thin shim. Everything Heartbeat lives in `^/.hb-heartbeat/` — read `^/.hb-heartbeat/start.md` and follow it.

```
python3 ^/.hb-heartbeat/hb.py status | approve <ID> [--project P] [--priority 0-9] | kill | install [--dry-run] | summary
python3 ^/.hb-heartbeat/hb.py run                              # session-driven, apex-only: process ONE item now
python3 ^/.hb-heartbeat/hb.py loop start [--interval S] | stop | status   # detached ticker (default 1h); non-persistent
```

`run`/`loop` drive HB from a session without the native scheduler. **Apex-only** — they hard-abort (exit 3)
if invoked from a child project's context. `loop` runs `tick` (keep-alive + run-*if-armed*), so a stray loop
keeps Majel's DB awake but cannot open PRs on its own. **Non-persistent:** a loop survives the terminal
closing but dies on reboot/shutdown and never self-restarts — for unattended nightly runs, register Task Scheduler.

**Kill switch:** `rm ^/.hb-heartbeat/state/GO` (stops backlog runs, not the keep-alive; stop a loop with `hb.py loop stop`).
