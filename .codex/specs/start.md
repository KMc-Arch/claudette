---
version: 1
---

# Specs

Specs define what to check. They are prescriptive standards against which audits and compliance checks evaluate projects.

## Authoring Rules

- Each spec is a standalone Markdown file in this folder
- Specs define **criteria**, not procedures — the audit protocol (in `explicit/audit/`) defines how to apply specs
- Specs may reference other specs but must be independently interpretable
- Specs live in the codex (shareable) because they define standards, not observations

## Relationship to Audits

- Specs are **inputs** to the audit process
- Audit **outputs** (findings, codex snapshots) live in `.state/tests/audits/` — never here
- When a spec changes, the next audit run uses the new version; prior audit results remain immutable records of what was checked under the old spec
