---
version: 1
---

# ~outbox

Outbound handoffs **from this project to another actor**. Pull-staged: the recipient reads its
own subfolder here; nothing is written across the fence into the recipient's tree. Visible
(`~`-prefixed).

    ~outbox/<X>/<topic>/<YYYY-MM-DD>-<name>    # an artifact addressed to project X

Per the apex **Exchange Surfaces** rule: any external-facing result — a report, export, or
handoff — lands here, not inline-only. `<X>` is the recipient's project name (roots.db name) or
a well-known channel.

Recipients with their own item protocol define it themselves: Heartbeat (`hb`) takes approved
work items with a frontmatter spec and an atomic-rename claim lifecycle — see `^/^/.hb-heartbeat/`
before writing to `~outbox/hb/`.
