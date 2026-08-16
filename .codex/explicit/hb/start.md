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
```

**Kill switch:** `rm ^/.hb-heartbeat/state/GO`.
