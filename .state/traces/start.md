---
version: 1
---

# Traces

Session observability records. Captures what happened during a session — distinct from compliance (were rules followed?) and tests (did code work?).

Traces answer: **"what happened?"** Compliance answers: "was it allowed?"

---

## What Gets Traced

| Category | Examples |
|---|---|
| Codex loading | Which implicit entries loaded, in what order, any failures |
| Trigger activity | Which reactive triggers matched, which reflexive triggers fired, which didn't |
| Module invocations | Which explicit modules were invoked, with what parameters |
| Tool calls | Which tools were called, in what sequence |
| Session context | Working directory, project root, active `root: true` chain |

---

## Format

Each trace is a single log file per day, appended to throughout the day's sessions.

**Filename:** `YYYY-MM-DD.trace`

**Entry format:**
```
[YYYY-MM-DDTHH:MM:SS] CATEGORY: description
```

Categories match the table above: `CODEX`, `TRIGGER`, `MODULE`, `TOOL`, `CONTEXT`.

---

## Signal Prefixes

See `.state/start.md` for the canonical taxonomy. In trace context:
- `SURPRISE:` — unexpected loading order, trigger match on an unintended condition, or tool call outside normal patterns

---

## Retention

Traces are high-volume, low-archival-value. Keep last 5 sessions. Older traces deleted unless explicitly preserved.

---

## Relationship to Other Verification

| Concern | Location | Question answered |
|---|---|---|
| Traces | `traces/` | What happened? (observability) |
| Compliance | `tests/compliance/` | Were rules followed? (governance) |
| Module tests | `tests/explicit/`, etc. | Does the code work? (correctness) |
| Audits | `tests/audits/` | Does the project meet specs? (standards) |
