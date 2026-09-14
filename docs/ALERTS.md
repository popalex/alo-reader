# Alerts

Three alarms, provisioned into Grafana with the OpenTelemetry overlay. They are the
floor for a self-hosted instance: the failures that silently break the product rather
than announce themselves.

| Alert | Fires when | Waits | What it means |
| --- | --- | --- | --- |
| Worker lag | oldest due feed unclaimed > 300s | 10m | feeds are going stale |
| API 5xx rate | over 5% of responses are 5xx | 10m | readers are losing requests |
| Disk free | least free real filesystem < 15% | 15m | Postgres is about to stop writing |

Rules live in [`deploy/observability/alerting/alo-floor.yml`](../deploy/observability/alerting/alo-floor.yml).
Grafana loads them from a file, so they cannot be edited in the UI and they come back
identically after every container recreate. To change a threshold, edit the evaluator
params in that file and recreate the `otel-lgtm` container.

## Before any of this works

Telemetry is off by default. `make up` runs the app with no collector, no Grafana and
no alert evaluation at all. The alerts exist only under the OTel overlay:

```sh
make otel-up          # app + collector + Grafana, alerts provisioned
# Grafana at http://localhost:3001 (loopback only), Alerting > Alert rules > alo-reader
```

Two of the three read metrics the app exports itself. The disk numbers come from the
collector, which runs the unix exporter's filesystem collector over read-only host
mounts (`/`, `/proc`, `/sys`, see `docker-compose.otel.yml`). Postgres has no SQL for
free space, so there is no in-app way to get this.

## Getting the alerts on your phone

Alerts go to [Pushover](https://pushover.net): a push notification, not an email you
read the next morning. Setup is three steps.

1. Install the app and buy it. $4.99 once per platform after a 30-day trial. Your
   **user key** is on the dashboard at pushover.net.
2. Register an application at pushover.net/apps/build (call it `alo-reader`). That
   gives you an **API token**. 10,000 messages a month are free, and this alert floor
   sends single digits.
3. Put both in `.env` and recreate the `otel-lgtm` container:

```sh
ALO_PUSHOVER_USER_KEY=...
ALO_PUSHOVER_API_TOKEN=...
```

Grafana expands those into the contact point in
[`alerting/notifications.yml`](../deploy/observability/alerting/notifications.yml).
Leave them unset and everything still runs: alerts evaluate, they show in Grafana, and
only delivery fails, with Pushover's own rejection in the Grafana log.

Four things worth knowing up front:

- **Routing is provisioned, not just the destination.** The otel-lgtm image ships a
  default route pointing at a receiver named `empty`, so alerts fire into a black hole.
  The file provisions the policy as well, which is why this works out of the box.
  Grafana then marks the policy read-only in the UI. To route somewhere else, edit the
  file, or drop its mount from `docker-compose.otel.yml` and take the policy back in
  the UI.
- **Firing goes out at priority 1, resolved at -1.** Priority 1 is red and ignores your
  quiet hours, which is the point of a push. The all-clear stays quiet. For priority 2,
  which retries until you acknowledge it, add `retry` and `expire` alongside it in the
  same file. That is the right setting for something that pages a rota, and overkill
  for a feed reader.
- **Set `GRAFANA_ROOT_URL` to your public URL.** Every link in the notification is
  built from it, so on the default it sends you to `localhost`.
- **Notifications are batched, not instant.** One 30s after a rule fires, at most one
  more every 5 minutes while alerts join the group, then a reminder every 12 hours
  while it keeps firing. Change `group_wait` / `repeat_interval` in the same file.

### Wanting a different channel

Grafana speaks Pushover natively, which is why there is no webhook template here to
escape by hand. If you want something else, add the contact point in
`notifications.yml` and point the policy at it:

- **Email** needs a contact point of type `email` plus `GF_SMTP_*` settings on the
  `otel-lgtm` service. Workable, but it is the channel you read late.
- **ntfy** is open source and free, and goes through a `webhook` contact point with a
  custom JSON payload. Two things to know: Grafana's template functions have no
  `toJson`, so a quote or newline in an annotation produces invalid JSON and the
  notification fails; and self-hosting ntfy on this same host means the disk-full alert
  dies with the box it is reporting on.
- **Slack, Telegram, Discord, PagerDuty and OpsGenie** all have native integrations,
  same shape as the Pushover block.

## Worker lag

```promql
max(alo_worker_lag_seconds)
```

The age of the oldest feed that is due for a check and not claimed by any worker.
It sits at 0 in the steady state and climbs the moment the worker stops draining.

**Why 300 seconds.** The WP-15 load test drains a 1000-feed backlog in about six
seconds, and the shortest interval any feed gets is 900s, so five minutes of unclaimed
backlog is far outside normal jitter. The 10 minute wait covers a worker restart and a
slow batch without paging.

The api computes this gauge, not the worker, which is what makes a dead worker visible.
It also means missing data is itself a failure, so this rule alerts on no data: either
the api is down or telemetry stopped reaching the collector.

**When it fires:**

1. `docker compose ps` and `docker compose logs worker --tail=100`. A crashed worker
   exits non-zero and restarts, and the exit is logged as `<loop>_crashed`.
2. Check the lag panel's shape. A step means the worker stopped; a steady climb means
   it is running but too slow.
3. Too slow is usually one of: `WORKER_MAX_CONCURRENCY` too low for the feed count,
   one host tarpitting every request (`alo_fetch_duration_milliseconds` p95 by host),
   or the DB pool exhausted (`DB_POOL_SIZE` must be at least the worker concurrency).
4. A worker stuck on a lease it cannot finish shows as feeds with `claimed_until` in
   the future and no progress. `WORKER_LEASE_S` must exceed the worst-case batch drain,
   or two replicas fight over the same feeds.

## API 5xx rate

```promql
100 * sum(rate(http_server_duration_milliseconds_count{service_name="alo-api",http_status_code=~"5.."}[5m]))
    / sum(rate(http_server_duration_milliseconds_count{service_name="alo-api"}[5m]))
```

Share of API responses that are server errors. `/healthz` is excluded from
instrumentation, so probe traffic does not pad the denominator and hide a burst on a
quiet instance. 4xx never counts here: a 404 storm or a rate-limited client is not the
server failing.

No traffic means no ratio, and this rule treats that as fine rather than as an outage.

**When it fires:**

1. Filter Loki for `unhandled_error` on `service_name="alo-api"`. Each line carries the
   method, the path and the request id, and the traceback follows it.
2. Take a `request_id` from one of those lines and search Tempo for the same trace to
   see which query or upstream call failed.
3. If Sentry is configured (`SENTRY_DSN`), the same exceptions are grouped there with
   the stack, which is faster than reading Loki.
4. The common causes are the database being unreachable (check `postgres` health and
   the pool settings) and a migration that has not been applied to a new image.

## Disk

```promql
min(100 * node_filesystem_avail_bytes{fstype!~"tmpfs|ramfs|vfat|squashfs|overlay|iso9660"}
      / node_filesystem_size_bytes{fstype!~"tmpfs|ramfs|vfat|squashfs|overlay|iso9660"})
```

Free space on the emptiest real filesystem, which includes whichever one holds
`/var/lib/docker` and therefore the Postgres volume and the backups.

**Why 15%.** A full disk is not a gradual failure. Postgres refuses writes, the nightly
`pg_dump` produces a file it then rejects, and the recovery is manual. 15% on a small
VPS still leaves room to purge and breathe.

This rule resolves on no data, because a non-Linux Docker host may not expose the host
filesystem to the collector at all. Confirm the query returns a number on your host,
then switch `noDataState` to `Alerting` so a dead collector is not mistaken for a
healthy disk.

**When it fires:**

1. `df -h` on the host. If it is not the app, it is logs or images: `docker system df`.
2. Inside the app, the two things that grow are entries and backups. Table sizes are on
   the metrics dashboard (`alo_table_bytes`); backups keep 14 days by default
   (`BACKUP_RETENTION_DAYS`).
3. Shorten `RETENTION_HORIZON_DAYS` and let the worker's next maintenance sweep purge.
   It purges in batches, each its own transaction, so it will not lock the table.
4. Reclaiming space from Postgres after a large purge needs a `VACUUM FULL` or a
   dump/restore. Neither is instant, which is the argument for not reaching 0%.

## What is deliberately not here

- **Backup freshness.** The one gap I would close next. The sidecar verifies every dump
  (`zstd -t` plus `pg_restore -l`) and refuses to publish a broken one, but it exports
  no metric, so a sidecar that has been failing for a week is invisible here. Until it
  does, check `ls -l` on the backups volume when you touch the box, and read
  [`deploy/BACKUP.md`](../deploy/BACKUP.md).
- **Certificate expiry.** Caddy renews on its own and the failure mode is loud.
- **Per-host fetch failures.** Feeds break constantly. That is a dashboard, not a page.
- **DB growth rate.** The disk alert catches the consequence, and a rate alert on a
  reader that is simply being used would be noise.

## Proving they work

Do this once, on purpose, before you rely on them.

**Any rule, in one minute.** Copy a rule through the provisioning API with a threshold
it already breaches and `for: 0s`, watch it fire, then delete it. This tests the query,
the evaluator and the delivery path without waiting for a real outage:

```sh
curl -u admin:admin http://localhost:3001/grafana/api/v1/provisioning/alert-rules
# POST a copy with a loose threshold and X-Disable-Provenance: true, then DELETE it
```

**Worker lag, for real.** Stop the worker and backdate the schedule:

```sh
docker compose ... stop worker
docker compose ... exec postgres psql -U alo -d alo \
  -c "update feeds set next_check_at = now() - interval '30 minutes';"
```

The gauge climbs within about a minute (the api samples it every 15s, the collector
exports every 60s) and the rule fires ten minutes later. Start the worker again and it
drains back to 0.

**5xx, for real.** Stop Postgres and hit an endpoint that needs it. Every request comes
back 500 with the uniform envelope, and the ratio crosses 5% almost immediately.
