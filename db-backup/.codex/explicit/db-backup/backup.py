#!/usr/bin/env python3
"""
db-backup worker — single-file entry for the /db-backup and /db-backup-test slash commands.

Subcommands:
    run <profile>     Take a new backup (dump + aggregates + Tier 1 + auto-prune)
    verify <profile>  Tier 2 smoke test: restore latest backup into ephemeral Docker Postgres,
                      compare aggregates against source manifest
    prune <profile>   Apply calendar-bucketed retention policy
    list <profile>    List backups with tier membership (retention debugging)

All subcommands accept --project-root (defaults to cwd).
Credentials come from db-backup/.env as DB_<PROFILE_UPPER>_URL (+ optional _RESTORE_IMAGE, _SCHEMAS).
See db-backup/.env.example.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as _platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("error: psycopg not installed. run: pip install 'psycopg[binary]'", file=sys.stderr)
    sys.exit(2)

try:
    from dotenv import load_dotenv
except ImportError:
    print("error: python-dotenv not installed. run: pip install python-dotenv", file=sys.stderr)
    sys.exit(2)


# ─── Constants ──────────────────────────────────────────────────────────────

MANIFEST_VERSION = 1
DEFAULT_SCHEMAS = "public"

AGGREGATE_TIER_MEDIUM_MAX = 10_000_000   # rows — at or below, do medium-tier aggregates
AGGREGATE_TIER_EXPENSIVE_MAX = 1_000_000 # rows — at or below AND --thorough, do expensive

SIZE_ANOMALY_LOW = 0.5
SIZE_ANOMALY_HIGH = 2.0

RETENTION_KEEP_PER_TIER = 3

DOCKER_READY_TIMEOUT_SECS = 60
DOCKER_CONTAINER_PREFIX = "db-backup-verify"

PARTIAL_GC_HOURS = 24
LOCK_STALE_HOURS = 6

FLOAT_EPSILON = 1e-9


# ─── Time helpers ───────────────────────────────────────────────────────────

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_filename_ts(dt: Optional[datetime] = None) -> str:
    return (dt or utcnow()).strftime("%Y-%m-%dT%H-%M-%SZ")


def parse_filename_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=timezone.utc)


# ─── Profile / config ───────────────────────────────────────────────────────

@dataclass
class Profile:
    name: str          # lowercase-hyphenated: "supabase-prod"
    upper: str         # UPPER_SNAKE: "SUPABASE_PROD"
    url: str
    restore_image: Optional[str]
    schemas: list[str]


def discover_profiles(env: dict) -> list[Profile]:
    """Scan env for DB_<NAME>_URL keys, build Profile objects."""
    profiles = []
    for key, val in env.items():
        m = re.fullmatch(r"DB_(.+)_URL", key)
        if not m or not val:
            continue
        upper = m.group(1)
        # Name is lowercase with single hyphens in place of underscores.
        name = upper.lower().replace("_", "-")
        schemas_raw = env.get(f"DB_{upper}_SCHEMAS", DEFAULT_SCHEMAS)
        schemas = [s.strip() for s in schemas_raw.split(",") if s.strip()]
        profiles.append(Profile(
            name=name,
            upper=upper,
            url=val,
            restore_image=env.get(f"DB_{upper}_RESTORE_IMAGE") or None,
            schemas=schemas,
        ))
    profiles.sort(key=lambda p: p.name)
    return profiles


def select_profile(profiles: list[Profile], requested: Optional[str]) -> Profile:
    if requested:
        for p in profiles:
            if p.name == requested:
                return p
        names = ", ".join(p.name for p in profiles) or "(none)"
        print(f"error: profile '{requested}' not found. available: {names}", file=sys.stderr)
        sys.exit(1)
    if not profiles:
        print("error: no profiles defined. create db-backup/.env with DB_<NAME>_URL entries. see .env.example.", file=sys.stderr)
        sys.exit(1)
    if len(profiles) == 1:
        return profiles[0]
    names = ", ".join(p.name for p in profiles)
    print(f"error: multiple profiles; specify one: {names}", file=sys.stderr)
    sys.exit(1)


# ─── URL parsing (keep password out of argv) ────────────────────────────────

@dataclass
class PgConn:
    host: str
    port: int
    user: str
    password: str
    database: str
    sslmode: Optional[str] = None


def parse_pg_url(url: str) -> PgConn:
    u = urlparse(url)
    if u.scheme not in ("postgres", "postgresql"):
        raise ValueError(f"not a postgres URL: {url}")
    q = parse_qs(u.query)
    return PgConn(
        host=u.hostname or "localhost",
        port=u.port or 5432,
        user=u.username or "postgres",
        password=u.password or "",
        database=(u.path or "/").lstrip("/") or "postgres",
        sslmode=q.get("sslmode", [None])[0],
    )


def pg_subprocess_env(conn: PgConn) -> dict:
    """Env for pg_dump/pg_restore — password via PGPASSWORD, never argv."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn.password
    if conn.sslmode:
        env["PGSSLMODE"] = conn.sslmode
    return env


def psycopg_kwargs(conn: PgConn) -> dict:
    kw = dict(
        host=conn.host, port=conn.port, user=conn.user,
        password=conn.password, dbname=conn.database,
    )
    if conn.sslmode:
        kw["sslmode"] = conn.sslmode
    return kw


# ─── Process / lock helpers ─────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _platform.system() == "Windows":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in out.stdout
        except Exception:
            return True  # unknown — assume alive, don't risk breaking a live lock
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True


class Lock:
    """File-based lock via O_EXCL; works on Windows and Unix."""

    def __init__(self, path: Path):
        self.path = path
        self.fd: Optional[int] = None

    def _break_stale(self) -> None:
        if not self.path.exists():
            return
        try:
            content = self.path.read_text(encoding="utf-8").strip()
            parts = {}
            for line in content.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    parts[k.strip()] = v.strip()
            pid = int(parts.get("pid", "0"))
            ts = parts.get("time", "")
            age_ok_to_break = False
            if ts:
                try:
                    lock_time = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    if (utcnow() - lock_time).total_seconds() > LOCK_STALE_HOURS * 3600:
                        age_ok_to_break = True
                except Exception:
                    pass
            if pid and not _pid_alive(pid):
                print(f"warning: breaking stale lock (pid {pid} not running): {self.path}", file=sys.stderr)
                self.path.unlink()
            elif age_ok_to_break:
                print(f"warning: breaking stale lock (>{LOCK_STALE_HOURS}h old): {self.path}", file=sys.stderr)
                self.path.unlink()
        except Exception:
            pass  # corrupt — leave it and let acquire fail clearly

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._break_stale()
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            print(f"error: another run holds the lock: {self.path} (exit 2)", file=sys.stderr)
            sys.exit(2)
        os.write(self.fd, f"pid={os.getpid()}\ntime={utcnow_iso()}\n".encode("utf-8"))

    def release(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.fd = None

    def __enter__(self) -> "Lock":
        self.acquire()
        return self

    def __exit__(self, *args) -> None:
        self.release()


# ─── Partial file garbage collection ────────────────────────────────────────

def gc_stale_partials(backups_dir: Path) -> None:
    if not backups_dir.exists():
        return
    cutoff = utcnow().timestamp() - PARTIAL_GC_HOURS * 3600
    collected = []
    for p in backups_dir.glob("*.partial"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                collected.append(p.name)
        except Exception:
            continue
    if collected:
        print(f"[gc] removed {len(collected)} stale partial(s): {', '.join(collected)}")


# ─── SHA256 helper ──────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ─── Column type classification ─────────────────────────────────────────────

NUMERIC_TYPES = {
    "smallint", "integer", "bigint", "numeric", "decimal",
    "real", "double precision", "money",
}
INT_TYPES = {"smallint", "integer", "bigint"}
FLOAT_TYPES = {"real", "double precision", "numeric", "decimal", "money"}
STRING_TYPES = {"character varying", "character", "text", "name", "citext"}
TIMESTAMP_TYPES = {
    "timestamp without time zone", "timestamp with time zone",
    "date", "time without time zone", "time with time zone",
}
BOOL_TYPES = {"boolean"}
UUID_TYPES = {"uuid"}
JSON_TYPES = {"json", "jsonb"}
BYTEA_TYPES = {"bytea"}


def classify_column(data_type: str, udt_name: str) -> str:
    """Return one of: numeric, int, float, string, timestamp, bool, uuid, json, bytea, array, other."""
    if data_type == "ARRAY" or (udt_name and udt_name.startswith("_")):
        return "array"
    if data_type in INT_TYPES:
        return "int"
    if data_type in FLOAT_TYPES:
        return "float"
    if data_type in NUMERIC_TYPES:
        return "numeric"
    if data_type in STRING_TYPES:
        return "string"
    if data_type in TIMESTAMP_TYPES:
        return "timestamp"
    if data_type in BOOL_TYPES:
        return "bool"
    if data_type in UUID_TYPES:
        return "uuid"
    if data_type in JSON_TYPES:
        return "json"
    if data_type in BYTEA_TYPES:
        return "bytea"
    return "other"


def qident(name: str) -> str:
    """Quote an identifier (table, column, schema name)."""
    return '"' + name.replace('"', '""') + '"'


# ─── Aggregate expressions per column ────────────────────────────────────────

def aggregate_exprs(col_name: str, kind: str, tier: str) -> list[tuple[str, str]]:
    """Return list of (label, SQL expression) for the column at the given tier.

    tier: "cheap" | "medium" | "expensive"
    Expressions operate on the aliased table — caller composes SELECT.
    """
    q = qident(col_name)
    exprs: list[tuple[str, str]] = []

    # Universal: null count
    exprs.append((f"{col_name}__null_count", f"COUNT(*) FILTER (WHERE {q} IS NULL)"))

    if kind in ("int", "float", "numeric"):
        exprs.append((f"{col_name}__min", f"MIN({q})::text"))
        exprs.append((f"{col_name}__max", f"MAX({q})::text"))
        if tier in ("medium", "expensive"):
            exprs.append((f"{col_name}__sum", f"SUM({q}::numeric)::text"))
            exprs.append((f"{col_name}__avg", f"AVG({q}::numeric)::text"))
            exprs.append((f"{col_name}__stddev", f"COALESCE(STDDEV_POP({q}::numeric), 0)::text"))
        if tier == "expensive":
            exprs.append((f"{col_name}__md5_sorted",
                          f"MD5(COALESCE(string_agg({q}::text, ',' ORDER BY {q}), ''))"))

    elif kind == "string":
        exprs.append((f"{col_name}__min", f"MIN({q})"))
        exprs.append((f"{col_name}__max", f"MAX({q})"))
        if tier in ("medium", "expensive"):
            exprs.append((f"{col_name}__avg_length", f"AVG(LENGTH({q}))::text"))
            exprs.append((f"{col_name}__sum_length", f"SUM(LENGTH({q}))::text"))
        if tier == "expensive":
            exprs.append((f"{col_name}__md5_sorted",
                          f"MD5(COALESCE(string_agg({q}, ',' ORDER BY {q}), ''))"))

    elif kind == "timestamp":
        exprs.append((f"{col_name}__min", f"MIN({q})::text"))
        exprs.append((f"{col_name}__max", f"MAX({q})::text"))

    elif kind == "bool":
        exprs.append((f"{col_name}__true_count", f"COUNT(*) FILTER (WHERE {q} = TRUE)"))
        exprs.append((f"{col_name}__false_count", f"COUNT(*) FILTER (WHERE {q} = FALSE)"))

    elif kind == "uuid":
        exprs.append((f"{col_name}__min", f"MIN({q})::text"))
        exprs.append((f"{col_name}__max", f"MAX({q})::text"))
        if tier == "expensive":
            exprs.append((f"{col_name}__md5_sorted",
                          f"MD5(COALESCE(string_agg({q}::text, ',' ORDER BY {q}), ''))"))

    elif kind == "json":
        if tier in ("medium", "expensive"):
            exprs.append((f"{col_name}__sum_size", f"SUM(octet_length({q}::text))::text"))

    elif kind == "bytea":
        if tier in ("medium", "expensive"):
            exprs.append((f"{col_name}__sum_size", f"SUM(octet_length({q}))::text"))

    elif kind == "array":
        if tier in ("medium", "expensive"):
            exprs.append((f"{col_name}__sum_cardinality",
                          f"COALESCE(SUM(cardinality({q})), 0)::text"))

    # "other" (enums, custom types) — just null count already emitted

    return exprs


def unpack_aggregates(col_name: str, row_dict: dict) -> dict:
    """Pull the col's aggregates out of a flat result row into a nested dict."""
    prefix = f"{col_name}__"
    return {k[len(prefix):]: v for k, v in row_dict.items() if k.startswith(prefix)}


# ─── Schema structure / hash ────────────────────────────────────────────────

def capture_schema_structure(cur, schemas: list[str]) -> dict:
    """Query information_schema + pg_catalog for a structured schema snapshot."""
    schemas_tuple = tuple(schemas)

    cur.execute(
        """
        SELECT table_schema, table_name,
               column_name, ordinal_position,
               data_type, udt_name, is_nullable, column_default
          FROM information_schema.columns
         WHERE table_schema = ANY(%s)
         ORDER BY table_schema, table_name, ordinal_position
        """, (list(schemas),))
    columns = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT tc.table_schema, tc.table_name, tc.constraint_name, tc.constraint_type,
               kcu.column_name, kcu.ordinal_position
          FROM information_schema.table_constraints tc
          LEFT JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name
           AND kcu.table_schema = tc.table_schema
         WHERE tc.table_schema = ANY(%s)
         ORDER BY tc.table_schema, tc.table_name, tc.constraint_name, kcu.ordinal_position
        """, (list(schemas),))
    constraints = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT schemaname, tablename, indexname, indexdef
          FROM pg_indexes
         WHERE schemaname = ANY(%s)
         ORDER BY schemaname, tablename, indexname
        """, (list(schemas),))
    indexes = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT n.nspname AS schema, p.proname AS name, pg_get_function_identity_arguments(p.oid) AS args
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = ANY(%s)
         ORDER BY n.nspname, p.proname, args
        """, (list(schemas),))
    functions = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT extname, extversion
          FROM pg_extension
         ORDER BY extname
        """)
    extensions = [dict(r) for r in cur.fetchall()]

    return {
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "functions": functions,
        "extensions": extensions,
    }


def hash_schema_structure(structure: dict) -> str:
    canonical = json.dumps(structure, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


# ─── Table enumeration + aggregate execution ─────────────────────────────────

def enumerate_tables(cur, schemas: list[str]) -> list[dict]:
    """Return list of {schema, name, est_rows} for user tables in schemas."""
    cur.execute(
        """
        SELECT n.nspname AS schema, c.relname AS name, c.reltuples::bigint AS est_rows
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = ANY(%s)
           AND c.relkind = 'r'
         ORDER BY n.nspname, c.relname
        """, (list(schemas),))
    return [dict(r) for r in cur.fetchall()]


def enumerate_columns(cur, schema: str, table: str) -> list[dict]:
    cur.execute(
        """
        SELECT column_name, data_type, udt_name, ordinal_position
          FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s
         ORDER BY ordinal_position
        """, (schema, table))
    return [dict(r) for r in cur.fetchall()]


def pick_tier(est_rows: int, thorough: bool) -> str:
    if est_rows <= AGGREGATE_TIER_EXPENSIVE_MAX and thorough:
        return "expensive"
    if est_rows <= AGGREGATE_TIER_MEDIUM_MAX:
        return "medium"
    return "cheap"


def compute_table_aggregates(cur, schema: str, table: str, tier: str) -> dict:
    """Run one SELECT gathering all per-column aggregates + row count for a table."""
    cols = enumerate_columns(cur, schema, table)
    select_parts = ["COUNT(*) AS __row_count"]
    col_kinds: dict[str, str] = {}

    for col in cols:
        kind = classify_column(col["data_type"], col["udt_name"])
        col_kinds[col["column_name"]] = kind
        for label, expr in aggregate_exprs(col["column_name"], kind, tier):
            select_parts.append(f"{expr} AS {qident(label)}")

    sql = f"SELECT {', '.join(select_parts)} FROM {qident(schema)}.{qident(table)}"
    cur.execute(sql)
    row = cur.fetchone()

    aggregates: dict[str, Any] = {"_tier": tier}
    for col in cols:
        col_name = col["column_name"]
        kind = col_kinds[col_name]
        agg = unpack_aggregates(col_name, row)
        agg["_kind"] = kind
        aggregates[col_name] = agg

    return {
        "row_count": int(row["__row_count"]),
        "aggregates": aggregates,
    }


# ─── Manifest I/O ───────────────────────────────────────────────────────────

def manifest_path_for(dump_path: Path) -> Path:
    # dump: <ts>.dump → manifest: <ts>.manifest.json
    return dump_path.with_name(dump_path.stem + ".manifest.json")


def write_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ─── Tier 1 validation ──────────────────────────────────────────────────────

def tier_1_validate(dump_path: Path) -> bool:
    """pg_restore --list parses the dump TOC. Non-zero exit = unparseable."""
    try:
        r = subprocess.run(
            ["pg_restore", "--list", str(dump_path)],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode == 0 and "Archive created at" in r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"error: tier 1 validation failed: {e}", file=sys.stderr)
        return False


# ─── Docker helpers (Tier 2) ────────────────────────────────────────────────

def docker_check() -> None:
    if shutil.which("docker") is None:
        print("error: docker not found on PATH. Tier 2 requires Docker.", file=sys.stderr)
        sys.exit(2)


def docker_run_postgres(image: str, password: str) -> tuple[str, int]:
    """Start an ephemeral Postgres container. Returns (container_name, host_port)."""
    name = f"{DOCKER_CONTAINER_PREFIX}-{uuid.uuid4().hex[:8]}"
    # Use -p 0:5432 to let docker pick a free host port
    r = subprocess.run(
        ["docker", "run", "-d", "--rm",
         "-e", f"POSTGRES_PASSWORD={password}",
         "-p", "0:5432",
         "--name", name, image],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"error: docker run failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    # Discover mapped port
    r = subprocess.run(["docker", "port", name, "5432"], capture_output=True, text=True)
    if r.returncode != 0:
        docker_stop(name)
        print(f"error: docker port query failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    # Output line looks like "0.0.0.0:49154" — grab last colon-separated segment
    port_line = r.stdout.strip().splitlines()[0]
    host_port = int(port_line.split(":")[-1])
    return name, host_port


def docker_stop(name: str) -> None:
    subprocess.run(["docker", "stop", name], capture_output=True, text=True)


def docker_wait_ready(name: str, timeout: int = DOCKER_READY_TIMEOUT_SECS) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        r = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "postgres"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return
        time.sleep(1)
    docker_stop(name)
    print(f"error: docker Postgres did not become ready within {timeout}s", file=sys.stderr)
    sys.exit(1)


# ─── Retention (calendar-bucketed) ──────────────────────────────────────────

def tier_keys(dt: datetime) -> dict[str, str]:
    iso_year, iso_week, _ = dt.isocalendar()
    quarter = (dt.month - 1) // 3 + 1
    return {
        "daily":     dt.strftime("%Y-%m-%d"),
        "weekly":    f"{iso_year}-W{iso_week:02d}",
        "monthly":   dt.strftime("%Y-%m"),
        "quarterly": f"{dt.year}-Q{quarter}",
        "yearly":    f"{dt.year}",
    }


@dataclass
class BackupEntry:
    ts_str: str              # filename ts
    ts: datetime
    dump_path: Path
    manifest_path: Path
    manifest: dict
    pinned: bool = False
    tiers: dict[str, str] = field(default_factory=dict)


def list_backups(backups_dir: Path) -> list[BackupEntry]:
    """Enumerate backups in descending timestamp order (newest first)."""
    entries: list[BackupEntry] = []
    if not backups_dir.exists():
        return entries
    for mp in backups_dir.glob("*.manifest.json"):
        try:
            m = read_manifest(mp)
            ts_str = mp.name.removesuffix(".manifest.json")
            ts = parse_filename_ts(ts_str)
            dump_path = mp.with_name(ts_str + ".dump")
            if not dump_path.exists():
                continue
            entries.append(BackupEntry(
                ts_str=ts_str, ts=ts,
                dump_path=dump_path, manifest_path=mp,
                manifest=m,
                pinned=bool(m.get("pinned", False)),
                tiers=tier_keys(ts),
            ))
        except Exception as e:
            print(f"warning: skipping unreadable manifest {mp.name}: {e}", file=sys.stderr)
    entries.sort(key=lambda e: e.ts, reverse=True)
    return entries


def compute_retention_keep(entries: list[BackupEntry]) -> tuple[set[str], dict[str, dict[str, str]]]:
    """
    Returns (keep_ts_strs, tier_membership).

    keep_ts_strs: the set of backup ts_strs that must be retained.
    tier_membership: ts_str → {tier: bucket_key} for every tier this backup wins.
    """
    # entries are newest-first
    keep: set[str] = set()
    membership: dict[str, dict[str, str]] = {e.ts_str: {} for e in entries}

    for tier in ("daily", "weekly", "monthly", "quarterly", "yearly"):
        # Pick the newest entry per bucket (first occurrence wins since sorted desc)
        seen_buckets: dict[str, BackupEntry] = {}
        for e in entries:
            k = e.tiers[tier]
            if k not in seen_buckets:
                seen_buckets[k] = e
        # Take the newest RETENTION_KEEP_PER_TIER bucket winners
        bucket_winners = list(seen_buckets.values())
        bucket_winners.sort(key=lambda e: e.ts, reverse=True)
        for winner in bucket_winners[:RETENTION_KEEP_PER_TIER]:
            keep.add(winner.ts_str)
            membership[winner.ts_str][tier] = winner.tiers[tier]

    # Pinned backups are always kept
    for e in entries:
        if e.pinned:
            keep.add(e.ts_str)

    return keep, membership


def update_pinning(entries: list[BackupEntry]) -> None:
    """Unpin all, then pin the single newest backup whose tier_2 passed."""
    newest_passing: Optional[BackupEntry] = None
    for e in entries:  # newest first
        v2 = (e.manifest.get("validation") or {}).get("tier_2") or {}
        if v2.get("passed") is True and newest_passing is None:
            newest_passing = e
    for e in entries:
        desired = (e is newest_passing)
        if bool(e.manifest.get("pinned")) != desired:
            e.manifest["pinned"] = desired
            write_manifest(e.manifest_path, e.manifest)
            e.pinned = desired


# ─── Subcommand: run ────────────────────────────────────────────────────────

def cmd_run(profile: Profile, backups_dir: Path, thorough: bool, do_prune: bool) -> int:
    gc_stale_partials(backups_dir)
    lock = Lock(backups_dir / ".lock")

    with lock:
        conn_info = parse_pg_url(profile.url)
        ts_str = utc_filename_ts()
        dump_partial = backups_dir / f"{ts_str}.dump.partial"
        manifest_partial = backups_dir / f"{ts_str}.manifest.json.partial"
        dump_final = backups_dir / f"{ts_str}.dump"
        manifest_final = backups_dir / f"{ts_str}.manifest.json"

        print(f"[{profile.name}] connecting to source …")
        try:
            conn = psycopg.connect(**psycopg_kwargs(conn_info), autocommit=True)
        except Exception as e:
            print(f"error: connection failed: {e}", file=sys.stderr)
            return 1

        server_version_num = None
        server_version_text = None
        schema_struct = None
        schema_hash = None
        row_counts: dict[str, int] = {}
        aggregates: dict[str, dict] = {}

        try:
            # Explicit REPEATABLE READ txn so we can export a snapshot for pg_dump to share.
            conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur = conn.cursor(row_factory=dict_row)

            cur.execute("SELECT pg_export_snapshot() AS snap")
            snap_id = cur.fetchone()["snap"]
            print(f"[{profile.name}] snapshot exported: {snap_id}")

            cur.execute("SHOW server_version_num")
            server_version_num = cur.fetchone()["server_version_num"]
            cur.execute("SHOW server_version")
            server_version_text = cur.fetchone()["server_version"]

            # Launch pg_dump with the shared snapshot in parallel.
            dump_cmd = [
                "pg_dump",
                "-h", conn_info.host,
                "-p", str(conn_info.port),
                "-U", conn_info.user,
                "-d", conn_info.database,
                "--format=custom",
                "--compress=6",
                "--no-owner",
                "--no-privileges",
                f"--snapshot={snap_id}",
                "--file", str(dump_partial),
            ]
            for s in profile.schemas:
                dump_cmd.extend(["--schema", s])

            print(f"[{profile.name}] starting pg_dump (schemas: {', '.join(profile.schemas)})")
            dump_proc = subprocess.Popen(
                dump_cmd,
                env=pg_subprocess_env(conn_info),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )

            # Capture schema + aggregates on the snapshot-holding connection.
            print(f"[{profile.name}] capturing schema structure …")
            schema_struct = capture_schema_structure(cur, profile.schemas)
            schema_hash = hash_schema_structure(schema_struct)

            print(f"[{profile.name}] capturing row counts + aggregates …")
            tables = enumerate_tables(cur, profile.schemas)
            for t in tables:
                fqn = f"{t['schema']}.{t['name']}"
                tier = pick_tier(int(t["est_rows"] or 0), thorough)
                try:
                    result = compute_table_aggregates(cur, t["schema"], t["name"], tier)
                    row_counts[fqn] = result["row_count"]
                    aggregates[fqn] = result["aggregates"]
                except Exception as e:
                    print(f"warning: aggregate capture failed for {fqn}: {e}", file=sys.stderr)
                    aggregates[fqn] = {"_tier": tier, "_error": str(e)}

            # Wait for pg_dump to finish before committing (it still needs the snapshot).
            stdout, stderr = dump_proc.communicate()
            if dump_proc.returncode != 0:
                print(f"error: pg_dump failed (exit {dump_proc.returncode}):", file=sys.stderr)
                if stderr:
                    print(stderr, file=sys.stderr)
                conn.execute("ROLLBACK")
                return 1

            conn.execute("COMMIT")
        except Exception as e:
            print(f"error: source capture failed: {e}", file=sys.stderr)
            try: conn.execute("ROLLBACK")
            except Exception: pass
            return 1
        finally:
            try: conn.close()
            except Exception: pass

        if not dump_partial.exists() or dump_partial.stat().st_size == 0:
            print(f"error: dump file is missing or empty: {dump_partial}", file=sys.stderr)
            return 1

        # Tier 1 validation
        print(f"[{profile.name}] tier 1 validation …")
        if not tier_1_validate(dump_partial):
            print(f"error: tier 1 validation failed; leaving {dump_partial.name} for inspection", file=sys.stderr)
            return 1

        # Sidecar SHA256 + size
        size_bytes = dump_partial.stat().st_size
        sha256 = sha256_file(dump_partial)

        # Build manifest
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "profile": profile.name,
            "created_at": utcnow_iso(),
            "source": {
                "server_version_num": int(server_version_num),
                "server_version_text": server_version_text,
                "schemas": profile.schemas,
                "extensions": schema_struct["extensions"],
            },
            "dump": {
                "file": f"{ts_str}.dump",
                "format": "custom",
                "size_bytes": size_bytes,
                "sha256": sha256,
            },
            "schema": {
                "hash": schema_hash,
                "structure": schema_struct,
            },
            "row_counts": row_counts,
            "aggregates": aggregates,
            "validation": {
                "tier_1": {"passed": True, "at": utcnow_iso()},
                "tier_2": None,
            },
            "pinned": False,
        }

        write_manifest(manifest_partial, manifest)

        # Atomic rename both
        os.replace(str(dump_partial), str(dump_final))
        os.replace(str(manifest_partial), str(manifest_final))
        print(f"[{profile.name}] backup ok: {dump_final.name} ({size_bytes} bytes)")

        # Size anomaly warning
        prev_size = _previous_size(backups_dir, exclude_ts=ts_str)
        if prev_size and prev_size > 0:
            ratio = size_bytes / prev_size
            if ratio < SIZE_ANOMALY_LOW or ratio > SIZE_ANOMALY_HIGH:
                print(
                    f"warning: size anomaly — current {size_bytes} vs previous {prev_size} (ratio {ratio:.2f})",
                    file=sys.stderr,
                )

    # prune is outside the lock (it does its own integrity — reads entries + deletes)
    if do_prune:
        cmd_prune(profile, backups_dir, dry_run=False)

    return 0


def _previous_size(backups_dir: Path, exclude_ts: str) -> Optional[int]:
    entries = list_backups(backups_dir)
    for e in entries:
        if e.ts_str == exclude_ts:
            continue
        return int(e.manifest.get("dump", {}).get("size_bytes", 0))
    return None


# ─── Subcommand: verify (Tier 2) ────────────────────────────────────────────

def cmd_verify(profile: Profile, backups_dir: Path, at: Optional[str]) -> int:
    docker_check()
    if shutil.which("pg_restore") is None:
        print("error: pg_restore not found on PATH", file=sys.stderr)
        return 2

    entries = list_backups(backups_dir)
    if not entries:
        print(f"error: no backups for profile '{profile.name}'", file=sys.stderr)
        return 1

    if at:
        target = next((e for e in entries if e.ts_str == at), None)
        if not target:
            print(f"error: backup '{at}' not found for profile '{profile.name}'", file=sys.stderr)
            return 1
    else:
        target = entries[0]  # newest

    print(f"[{profile.name}] verifying {target.ts_str} …")

    src_version = int(target.manifest["source"]["server_version_num"])
    src_major = src_version // 10000

    image = profile.restore_image or f"postgres:{src_major}"
    print(f"[{profile.name}] restore image: {image}")

    docker_pw = uuid.uuid4().hex
    name, port = docker_run_postgres(image, docker_pw)
    started_ok = False
    try:
        print(f"[{profile.name}] waiting for container {name} (port {port}) …")
        docker_wait_ready(name)
        started_ok = True

        restore_url = f"postgresql://postgres:{docker_pw}@localhost:{port}/postgres"
        print(f"[{profile.name}] pg_restore …")
        r = subprocess.run(
            ["pg_restore", "--dbname", restore_url,
             "--no-owner", "--no-privileges",
             str(target.dump_path)],
            capture_output=True, text=True,
        )
        # pg_restore frequently exits 1 for ACL warnings while still restoring data.
        # We treat it as warnings-only unless return code > 1 or no relations populated.
        if r.returncode > 1:
            print(f"error: pg_restore failed (exit {r.returncode}):\n{r.stderr}", file=sys.stderr)
            return 1
        if r.stderr:
            # Emit stderr but don't fail
            for line in r.stderr.splitlines():
                if line.strip():
                    print(f"  pg_restore: {line}")

        # Connect + recompute aggregates
        restored = psycopg.connect(
            host="localhost", port=port, user="postgres",
            password=docker_pw, dbname="postgres", autocommit=True,
        )
        try:
            cur = restored.cursor(row_factory=dict_row)

            mismatches = []
            checked_tables = 0
            for fqn, saved_agg in target.manifest.get("aggregates", {}).items():
                if "_error" in saved_agg:
                    # Skip tables the source couldn't aggregate
                    continue
                try:
                    schema, table = fqn.split(".", 1)
                except ValueError:
                    continue
                tier = saved_agg.get("_tier", "cheap")

                # Rebuild the same aggregates on the restored copy
                try:
                    restored_result = compute_table_aggregates(cur, schema, table, tier)
                except Exception as e:
                    mismatches.append({
                        "table": fqn, "kind": "query_error", "error": str(e),
                    })
                    continue

                checked_tables += 1
                src_rows = target.manifest.get("row_counts", {}).get(fqn)
                restored_rows = restored_result["row_count"]
                if src_rows is not None and src_rows != restored_rows:
                    mismatches.append({
                        "table": fqn, "kind": "row_count",
                        "source": src_rows, "restored": restored_rows,
                    })

                restored_agg = restored_result["aggregates"]
                for col_name, saved_col in saved_agg.items():
                    if col_name.startswith("_"):
                        continue
                    restored_col = restored_agg.get(col_name, {})
                    for metric, saved_val in saved_col.items():
                        if metric.startswith("_"):
                            continue
                        restored_val = restored_col.get(metric)
                        if not _aggregates_equal(saved_val, restored_val):
                            mismatches.append({
                                "table": fqn, "column": col_name, "metric": metric,
                                "source": saved_val, "restored": restored_val,
                            })
        finally:
            try: restored.close()
            except Exception: pass

        passed = len(mismatches) == 0
        target.manifest["validation"]["tier_2"] = {
            "passed": passed,
            "at": utcnow_iso(),
            "checked_tables": checked_tables,
            "mismatch_count": len(mismatches),
            "mismatches": mismatches[:100],  # cap to prevent huge manifests
        }
        write_manifest(target.manifest_path, target.manifest)

        # Update pinning across all entries
        refreshed = list_backups(backups_dir)
        update_pinning(refreshed)

        if passed:
            print(f"[{profile.name}] ✓ tier 2 passed ({checked_tables} tables)")
            return 0
        else:
            summary_counts: dict[str, int] = {}
            for m in mismatches:
                summary_counts[m["kind"] if "kind" in m else "aggregate"] = \
                    summary_counts.get(m["kind"] if "kind" in m else "aggregate", 0) + 1
            print(f"[{profile.name}] ✗ tier 2 FAILED: {len(mismatches)} mismatch(es) across {checked_tables} tables")
            # Structured diff to stderr
            print(json.dumps({"mismatches": mismatches[:20]}, indent=2, default=str), file=sys.stderr)
            return 1

    finally:
        if started_ok or name:
            docker_stop(name)


def _aggregates_equal(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    # Try integer equality
    try:
        ai, bi = int(a), int(b)
        return ai == bi
    except (ValueError, TypeError):
        pass
    # Try float equality with epsilon
    try:
        af, bf = float(a), float(b)
        if af == 0 and bf == 0:
            return True
        denom = max(abs(af), abs(bf), 1.0)
        return abs(af - bf) / denom < FLOAT_EPSILON
    except (ValueError, TypeError):
        pass
    # Fallback: string equality
    return str(a) == str(b)


# ─── Subcommand: prune ──────────────────────────────────────────────────────

def cmd_prune(profile: Profile, backups_dir: Path, dry_run: bool) -> int:
    entries = list_backups(backups_dir)
    if not entries:
        print(f"[{profile.name}] no backups to prune")
        return 0

    keep, membership = compute_retention_keep(entries)
    to_delete = [e for e in entries if e.ts_str not in keep]

    prefix = "[dry-run] " if dry_run else ""

    if not to_delete:
        print(f"[{profile.name}] {prefix}nothing to prune ({len(entries)} backup(s), all retained)")
        return 0

    print(f"[{profile.name}] {prefix}pruning {len(to_delete)} of {len(entries)} backup(s):")
    for e in to_delete:
        print(f"  - {e.ts_str}")
        if not dry_run:
            try:
                e.dump_path.unlink(missing_ok=True)
                e.manifest_path.unlink(missing_ok=True)
            except Exception as ex:
                print(f"    warning: deletion failed: {ex}", file=sys.stderr)
    return 0


# ─── Subcommand: list ───────────────────────────────────────────────────────

def cmd_list(profile: Profile, backups_dir: Path) -> int:
    entries = list_backups(backups_dir)
    if not entries:
        print(f"[{profile.name}] no backups")
        return 0

    _, membership = compute_retention_keep(entries)

    print(f"{'timestamp':<22} {'size':>10}  {'T1':^3} {'T2':^3} {'pin':^4}  tiers")
    print("-" * 80)
    for e in entries:
        size = int(e.manifest.get("dump", {}).get("size_bytes", 0))
        v = e.manifest.get("validation") or {}
        t1 = "✓" if (v.get("tier_1") or {}).get("passed") else "·"
        t2_raw = v.get("tier_2")
        if t2_raw is None:
            t2 = "·"
        elif t2_raw.get("passed"):
            t2 = "✓"
        else:
            t2 = "✗"
        pin = "PIN" if e.pinned else ""
        tiers = ",".join(sorted(membership.get(e.ts_str, {}).keys())) or "(prunable)"
        print(f"{e.ts_str:<22} {_fmt_size(size):>10}  {t1:^3} {t2:^3} {pin:^4}  {tiers}")
    return 0


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}{unit}"
        n /= 1024
    return f"{n}B"


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="backup.py",
        description="db-backup — local backups for remote Postgres databases",
    )
    parser.add_argument(
        "--project-root", type=Path, default=Path.cwd(),
        help="project root (default: cwd — should be the db-backup/ folder)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="take a new backup")
    p_run.add_argument("profile", nargs="?")
    p_run.add_argument("--no-prune", action="store_true")
    p_run.add_argument("--thorough", action="store_true",
                       help="enable expensive aggregates (MD5 of sorted values)")

    p_verify = sub.add_parser("verify", help="Tier 2 restore test on most recent backup")
    p_verify.add_argument("profile", nargs="?")
    p_verify.add_argument("--at", help="verify a specific backup by YYYY-MM-DDTHH-MM-SSZ")

    p_prune = sub.add_parser("prune", help="apply retention policy")
    p_prune.add_argument("profile", nargs="?")
    p_prune.add_argument("--dry-run", action="store_true")

    p_list = sub.add_parser("list", help="list backups with tier membership")
    p_list.add_argument("profile", nargs="?")

    args = parser.parse_args()
    project_root = args.project_root.resolve()

    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    profiles = discover_profiles(os.environ)
    profile = select_profile(profiles, getattr(args, "profile", None))

    backups_dir = project_root / "backups" / profile.name
    backups_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "run":
        return cmd_run(profile, backups_dir, thorough=args.thorough, do_prune=not args.no_prune)
    if args.command == "verify":
        return cmd_verify(profile, backups_dir, at=args.at)
    if args.command == "prune":
        return cmd_prune(profile, backups_dir, dry_run=args.dry_run)
    if args.command == "list":
        return cmd_list(profile, backups_dir)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
