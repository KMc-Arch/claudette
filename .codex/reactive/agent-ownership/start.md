---
version: 1
trigger: "writing or deleting files under the apex .claude/agents/ directory"
runtime: python
reads:
  - "./agent_ownership.py"
  - "^/.state/roots.db"
writes: []
short-desc: "Single implementation of who owns a file in .claude/agents/"
---

# agent-ownership

The one implementation of file ownership in the apex `.claude/agents/` directory. `cboot.py` and `.codex/explicit/purge/purge.py` both consume it. Neither may reimplement it.

## The rule

> A file in `^/.claude/agents/` belongs to cboot **if and only if the durable `agent_registry` in `^/.state/roots.db` currently claims it.**

Ownership is a lookup of the file's path against current registry rows (`valid_to IS NULL`). It is **never** inferred from the file's contents. No code path decodes a candidate file in order to decide whether it may be written or deleted.

## Why a module

Two divergent implementations of one ownership test is the defect this module exists to make impossible. When `cboot` and `purge` each carried their own version, they disagreed on real inputs and `purge` was the one that deleted. A caller that reimplements the rule is a defect, not an optimisation.

## The marker is advisory

Generated files carry `<!-- cboot:agent root="…" generated="…" -->` as their first body line. It is a human-readable "generated, do not hand-edit" banner plus a tamper check. **It confers nothing and removes nothing.** A forged marker cannot make a file ours. A missing marker cannot make our file foreign.

| registry says | marker says | cboot | purge |
|---|---|---|---|
| ours | present, matching | write / refresh normally | remove (cboot regenerates it) |
| ours | absent or altered | **warn and leave alone** — never overwrite | **preserve** — a human has been in the file |
| not ours | present | leave alone — a forged or stale marker confers nothing | preserve |
| not ours | absent | not our business; untouched | preserve |

cboot warns only about the second row, where a file it *claims* has been edited. It says nothing about unclaimed files: they are none of its business, and warning about each one on every boot would be noise. `test-safe` T64 inventories them instead.

**Why purge consults the marker at all.** Ownership is still the registry lookup — the marker is read only to *decline* a deletion, never to justify one. That can only ever narrow what purge removes, so it does not reintroduce deciding ownership from content. Without it the two callers disagree on a real input (a file cboot refuses to overwrite because a human edited it, and purge deletes), which is precisely the failure this module exists to prevent.

## Fail-safe

`claims_for()` raises `RegistryUnavailable` if `roots.db` is missing, locked, or structurally unusable. There is no partial answer.

- **Deleters** (purge) MUST treat it as *cboot owns nothing* and preserve every file.
- **Writers** (cboot) MUST abort the agent pass.

Guessing is never safe: the failure modes are "delete a project's live agent" and "overwrite a hand-authored file".

## API

| function | contract |
|---|---|
| `claims_for(db_path, agents_dir)` | `{abs_path: {agent_name, rel_path}}` for current registry rows. Raises `RegistryUnavailable`. Opens `immutable=1&mode=ro` (true read-only on a WAL db). |
| `owns(path, claims)` | Pure path lookup. Does not stat, open, decode, or parse. |
| `is_tmp_artifact(path)` | `<name>.md.tmp` — cboot's own staging leftover, never hand-authored, always removable. |
| `render_marker(rel_path, generated_at)` | Banner line. `rel_path` JSON-quoted so quotes/backslashes round-trip. |
| `read_marker(path)` | Advisory `root=` value or `None`. **Never raises** — unreadable or undecodable yields `None`. |
| `derive_agent_name(basename)` | Leading punctuation stripped, case kept, everything outside `[A-Za-z0-9-]` collapsed to `-`. |
| `yaml_scalar(value)` | JSON string form — always reads back as the same string. Unquoted, `name: 2025` is an int and `name: null` is None. |

## Path comparison

`_key()` makes paths absolute and collapses `..` **lexically** — it does not call `resolve()`. Resolving would follow a symlinked `agents/` and let a claim match a file outside the directory.

## When generating code

- Never test ownership by reading a file. Call `owns()`.
- Never catch `RegistryUnavailable` and continue with an empty claim set as if that meant "owns nothing, proceed to delete". Preserve, then report.
- Never write a `name:` or a path into YAML unquoted. Use `yaml_scalar()`.
