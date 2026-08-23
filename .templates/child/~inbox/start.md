---
version: 1
---

# ~inbox

Drops **addressed to this project** — inputs another actor left for this project's human /
next session. Visible (`~`-prefixed: not `.`-internal, not `_`-invisible).

    ~inbox/<sender>/...        # per-sender subfolder — a person or a sibling project (roots.db name)

Per the apex **Exchange Surfaces** rule: on an interactive boot, read each drop and act on it,
or explicitly defer it — never silently skip one. The inbox is read by a human / the next
session, never by an automated runner.

Specific senders may define their own drop format. Heartbeat (`hb`) writes per-item outcome
folders and a nightly summary — see `^/^/.hb-heartbeat/` for that recipient's spec.
