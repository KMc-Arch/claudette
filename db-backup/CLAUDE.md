---
root: true
codex: ^/^/.codex
---

# db-backup

Local backups of remote databases. Pulls and archives remote DB snapshots to `backups/` for offline retention. Starts with Supabase (DB only); designed to generalize to any Postgres-as-a-service (Neon, Railway, Render, RDS, etc.) without changes.

## Commands

- `/db-backup [<profile>]` — take a backup, validate it structurally, auto-prune per retention policy
- `/db-backup-test [<profile>]` — Tier 2 smoke test: restore the most recent backup into ephemeral Docker Postgres and compare aggregates against source manifest

Both shell into `.codex/explicit/db-backup/backup.py`. The Python script is the authoritative worker; the slash commands are thin entry points. An external scheduler (Windows Task Scheduler, cron) can call `backup.py` directly.

## What this is NOT

- **Not PITR.** Snapshot-based backups via `pg_dump`; you get point-in-time-of-backup recovery, not continuous WAL replay.
- **Not a full Supabase project backup.** Only the database is captured. Supabase Storage buckets and Auth users (where they live outside captured schemas) are NOT backed up.
- **Not a migration tool.** Dumps are portable to any Postgres ≥ the source major, but this isn't a cross-engine translator.
- **Not encrypted at rest.** Backups land in `backups/` (gitignored) as plaintext `pg_dump` custom-format files.

## Trust model

Every backup records a sidecar manifest containing row counts, per-column aggregates (MIN/MAX/AVG/SUM/STDDEV/hashes depending on tier), a structured schema hash, and a SHA256 of the dump file. The same aggregates, captured against the source inside the same transaction snapshot as `pg_dump`, are recomputed against the restored copy in Tier 2. **Match = solvent.** Mismatch anywhere = the backup is suspect.

Retention never deletes the most recent backup whose Tier 2 passed (`pinned: true` in the manifest). That "last known good" is always preserved.

## Configuration

Credentials live in `db-backup/.env` (gitignored). Profile is the env-var namespace: `/db-backup supabase-prod` reads `DB_SUPABASE_PROD_URL`. See `.env.example` for the full key taxonomy including `DB_<PROFILE>_RESTORE_IMAGE` (Tier 2 Docker image override for platforms with custom extensions) and `DB_<PROFILE>_SCHEMAS` (default: `public`).

## Supabase pooler-port gotcha

Supabase exposes two ports:
- **5432** — direct Postgres (use this)
- **6543** — Supavisor / pgBouncer transaction mode (does NOT support `pg_dump`; will fail mysteriously)

The connection string Supabase shows you by default may be the pooler port. Verify you're using 5432 in your `.env`. Same applies to other pgBouncer-fronted platforms.

Read `.state/start.md`.
