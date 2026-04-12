---
version: 1
short-desc: Tier 2 restore test — restore latest backup into ephemeral Docker Postgres and verify aggregates
runtime: python
reads:
  - "^/.env"
  - "^/backups/"
writes:
  - "^/backups/"
---

# db-backup-test

Run a Tier 2 smoke test against the most recent backup of a profile: spin up an ephemeral Docker Postgres container, restore the dump, recompute per-column aggregates, and compare them to the manifest. **Mismatches = the backup is not trustworthy.**

## Usage

```
/db-backup-test [<profile>]
```

If exactly one profile is defined, the argument is optional.

## What it does

1. Resolves Docker image: `DB_<PROFILE>_RESTORE_IMAGE` env var → `postgres:<source-major>` fallback. Fails if image major < source major.
2. `docker run -d --rm` an ephemeral Postgres container, random host port.
3. Polls `pg_isready` until container accepts connections (or 60s timeout).
4. `pg_restore --no-owner --no-privileges` the dump into the container.
5. Reconnects to the restored database and recomputes per-column aggregates matching the manifest's captured tier per column.
6. Compares every aggregate (integers exact, floats with 1e-9 relative epsilon, strings/UUIDs/hashes exact).
7. Writes result into `manifest.validation.tier_2`: `{passed, at, checked_tables, mismatch_count, mismatches}`.
8. If passed: pins this backup as "last known good" and unpins any previous pinned backup.
9. `docker stop` the container (which has `--rm`, so cleanup is automatic).

## Execution

```
python .codex/explicit/db-backup/backup.py --project-root ^ verify <profile>
```

Flags (after `verify`):
- `--at <YYYY-MM-DDTHH-MM-SSZ>` — verify a specific backup instead of the newest

## Cadence

Weekly per profile is the recommended default. Run manually via this slash command, or wire to an external scheduler.

## Exit codes

- `0` — Tier 2 passed; manifest updated and pin refreshed
- `1` — Tier 2 failed (mismatches found), or pg_restore unrecoverable error
- `2` — environment issue (docker not on PATH, pg_restore missing)

## Requirements

- `docker` on PATH (Docker Desktop / Podman Desktop / colima all fine)
- `pg_restore` on PATH
- Enough disk for the ephemeral container image (~200MB for `postgres:<major>`, ~2GB for `supabase/postgres`)
