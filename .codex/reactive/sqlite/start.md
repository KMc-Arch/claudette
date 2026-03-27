---
version: 2
trigger: "child project imports sqlite3 or uses SQLite/DuckDB"
runtime: python
reads:
  - "./sqlite.py"
writes: []
---

# sqlite

Connection factory for SQLite/DuckDB databases. Activates when a child project uses a local database.

## When It Triggers

When the current session involves a project that imports `sqlite3`, `duckdb`, or references `.db`/`.duckdb` files.

## What the Factory Enforces

| Pragma | Value | Why |
|---|---|---|
| `foreign_keys` | `ON` | Off by default in SQLite; must be set per-connection |
| `journal_mode` | `WAL` | Safe concurrent reads/writes; persists to the database file |
| `busy_timeout` | `5000` | Wait 5s instead of immediately throwing `SQLITE_BUSY` |
| `row_factory` | `sqlite3.Row` | Named column access instead of positional tuples |

## How to Use

Child projects import the factory rather than `sqlite3` directly:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".codex/reactive/sqlite"))
from sqlite import connect

conn = connect("data.db")
```

Or, if the project has its own wrapper, that wrapper must delegate to this factory.

## When Generating Code

- Never write `sqlite3.connect()` directly — always use the factory.
- If a child project already has direct `sqlite3.connect()` calls, flag them for remediation.
- If a project needs additional pragmas beyond the defaults, extend locally but never remove the factory defaults.
