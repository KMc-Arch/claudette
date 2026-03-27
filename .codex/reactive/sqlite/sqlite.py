"""SQLite connection factory with enforced safety pragmas.

All SQLite connections across child projects must use this factory.
See ^/.codex/reactive/sqlite/start.md for enforcement rules.
"""

import sqlite3
from pathlib import Path


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn
