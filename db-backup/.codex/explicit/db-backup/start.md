---
version: 1
short-desc: Take a backup of a remote DB profile (dump + Tier 1 validate + auto-prune)
runtime: python
reads:
  - "^/.env"
writes:
  - "^/backups/"
---

# db-backup

Take a backup of a configured remote database profile.

## Usage

```
/db-backup [<profile>]
```

If exactly one profile is defined in `.env`, the argument is optional. Otherwise specify which profile to back up.

## What it does

1. Garbage-collects stale `.partial` files (>24h old) in the profile's backup directory.
2. Acquires a per-profile lockfile to prevent concurrent backups.
3. Opens a `REPEATABLE READ READ ONLY` transaction against the source, exports a snapshot.
4. Runs `pg_dump --format=custom --snapshot=<id>` into `<timestamp>.dump.partial`.
5. In parallel on the same snapshot: captures structured schema (information_schema + pg_catalog), per-table row counts, per-column aggregates (tier chosen by `pg_class.reltuples`).
6. Waits for pg_dump, commits the source transaction.
7. Runs Tier 1 validation (`pg_restore --list`) on the dump. Must pass.
8. Computes SHA256, writes sidecar `<timestamp>.manifest.json.partial`.
9. Atomic rename `.partial` → final for both files.
10. Emits stderr warning if dump size is <50% or >200% of the prior backup (anomaly detector).
11. Runs the retention pruner unless `--no-prune` was passed.

## Execution

```
python .codex/explicit/db-backup/backup.py --project-root ^ run <profile>
```

Flags (after `run`):
- `--no-prune` — skip automatic retention pruning
- `--thorough` — enable expensive aggregates (MD5 of sorted column values) on tables ≤1M rows

## Configuration

See `^/.env.example`. Required per profile: `DB_<PROFILE>_URL`. Optional: `DB_<PROFILE>_RESTORE_IMAGE`, `DB_<PROFILE>_SCHEMAS` (default: `public`).

## Pooler gotcha (Supabase, PlanetScale, etc.)

pgBouncer in transaction mode does NOT support `pg_dump`. If your connection string uses port 6543 or goes through a pooler, dumps will fail. Use the direct port (5432 for Supabase).

## Exit codes

- `0` — backup successful and validated
- `1` — backup failed (source connection, pg_dump error, Tier 1 validation, etc.)
- `2` — environment / dependency error (missing tool, lock held)

## Related

- `/db-backup-test` — Tier 2 smoke test (restores to ephemeral Docker Postgres, compares aggregates)
- `backup.py prune <profile> [--dry-run]` — manual retention pruning
- `backup.py list <profile>` — show backups with tier membership (retention debugging)
