# Backup and restore

Postgres runs inside compose against the `pgdata` volume, so backups are the
operator's job (DESIGN.md §1.5). The `backup` sidecar does them on a schedule,
and `scripts/restore.sh` puts one back.

Files: `deploy/Dockerfile.backup`, `deploy/backup.sh`, `scripts/restore.sh`.

## Run it

The sidecar starts with the stack. Nothing to enable.

```sh
make up                                          # backup sidecar comes up too
docker compose -f deploy/docker-compose.yml exec backup backup list
docker compose -f deploy/docker-compose.yml exec backup backup once   # don't wait for tonight
```

`backup` takes four subcommands: `loop` (the default), `once`, `list`, and
`restore <file>`.

## What a backup is

`pg_dump -Fc -Z0` piped through `zstd`, landing in the `backups` volume as
`alo-<UTC timestamp>.dump.zst`.

Custom format (`-Fc`) rather than plain SQL, so `pg_restore` can do selective and
parallel restores later. `-Z0` turns off pg_dump's own gzip, so zstd is not
compressing already-compressed bytes.

### Why every dump is verified

A failed dump that leaves a plausible-looking file is worse than no dump, and
this pipeline can produce one. POSIX sh has no `pipefail`, so a `pg_dump` that
dies mid-stream does not fail the pipeline, and zstd will happily write a valid
frame around a truncated or empty input. The file looks fine. It restores to
nothing.

So before a file counts as a backup:

1. `zstd -t` tests the frame.
2. `pg_restore -l` has to read the archive's table of contents.

Only then is it renamed from `.partial` to its real name. A crash mid-dump leaves
a `.partial`, which `list` does not show and retention sweeps after a day.

A failing run logs and leaves the sidecar running. It does not exit, because a
restart loop buries the one log line that says what broke, and tomorrow's run
should still happen.

## Schedule, retention, off-box

| Variable | Default | Meaning |
| --- | --- | --- |
| `BACKUP_SCHEDULE_UTC` | `03:30` | time of day, UTC |
| `BACKUP_RETENTION_DAYS` | `14` | applies locally and to the remote |
| `BACKUP_ON_START` | `false` | also dump on container start |
| `BACKUP_ZSTD_LEVEL` | `10` | 19 is much slower for a few percent |
| `BACKUP_RCLONE_REMOTE` | empty | e.g. `s3:my-bucket/alo-reader` |

Backups sitting on the same host are not backups if the host is what you lose.
Set `BACKUP_RCLONE_REMOTE` and each dump is copied off-box and pruned on the same
retention. rclone reads its entire configuration from `RCLONE_CONFIG_*` variables
in `.env`, so there is no config file to mount. A failed remote copy warns and
keeps the local backup rather than failing the run.

## Is it still working?

The sidecar publishes what it knows to `/backups/metrics/alo_backup.prom` in
node_exporter textfile format, on every attempt and once at start-up:

```
alo_backup_last_success_timestamp_seconds   when a dump last passed both checks
alo_backup_last_success_bytes               how big it was
alo_backup_last_attempt_timestamp_seconds   whether it is still trying
alo_backup_last_attempt_success             whether that attempt worked
```

The success timestamp is the newest `alo-*.dump.zst` on the volume rather than a
remembered value, so a restarted sidecar recomputes it and an unverified dump never
counts. With the OTel overlay running, the collector reads that file through a
read-only mount and the **Backup freshness** alert pages when it passes 26 hours —
see [`docs/ALERTS.md`](../docs/ALERTS.md#backup-freshness). Without the overlay the
file is still written, so `cat` it on the volume:

```sh
docker compose -f deploy/docker-compose.yml exec backup cat /backups/metrics/alo_backup.prom
```

This covers the local volume only. A failing `rclone copy` warns and keeps the local
backup, which is the right call for the run and means the off-box copy has no alarm of
its own: check the remote by hand.

## Restore

```sh
scripts/restore.sh                        # newest backup, asks for confirmation
scripts/restore.sh alo-20260913T033000Z.dump.zst
scripts/restore.sh --latest --yes         # no prompt
```

It stops `api`, `worker` and `backup`, terminates any remaining connections,
restores with `pg_restore --clean --if-exists`, and starts everything again.

The stop is not politeness. `--clean` drops each object before recreating it, and
it cannot drop what an open connection is holding, so a live api would make the
restore fail halfway. A half-restored database being served is worse than a few
seconds of downtime.

Because it replaces everything in the database, it makes you type the database
name unless you pass `--yes`.

## Drill it

A backup nobody has restored is a guess. Run this against a scratch stack, not
production:

```sh
make up
make seed                                             # 20 feeds, ~5000 entries
docker compose -f deploy/docker-compose.yml exec backup backup once
docker compose -f deploy/docker-compose.yml exec -T postgres \
  psql -U alo -d alo -c 'truncate entries, feeds, users restart identity cascade'
scripts/restore.sh --latest --yes
```

Then check more than the row counts, because row counts are the part that is
almost never wrong:

```sql
-- sequences resumed? A fresh insert must not collide at id 1.
insert into folders (user_id, name) values (1, 'post-restore') returning id;

-- the RUM index for search still exists?
select count(*) from pg_indexes where indexdef ilike '%rum%';

-- search_tsv is a GENERATED column, which pg_restore carries no data for.
-- It has to have recomputed for every row.
select count(*) from entries where search_tsv is not null;
select count(*) from entries where search_tsv @@ websearch_to_tsquery('english', 'postgres');
```

All three passed on the drill run for the original implementation: sequences
resumed, the RUM index came back, and `search_tsv` recomputed for all 5001 rows
with real queries matching.

## Gotchas

**The image's Postgres major version has to track the server's.**
`deploy/Dockerfile.backup` is `postgres:18-alpine` because `pg_dump` refuses to
dump a server newer than itself. Bumping `deploy/Dockerfile.postgres` means
bumping that line in the same commit, or backups start failing the next night
with nothing else obviously broken.

**`DATABASE_URL` is not usable here.** It is SQLAlchemy-flavoured
(`postgresql+asyncpg://`) and libpq will not parse it. The sidecar takes the
standard `PGHOST` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` variables, which
compose fills from `POSTGRES_*`.

**Retention is by file mtime**, so copying backups around with a tool that resets
mtime will confuse the sweep.
