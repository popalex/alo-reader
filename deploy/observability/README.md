# Observability (OpenTelemetry → Grafana LGTM)

alo-reader is instrumented with **OpenTelemetry** — one standard for **traces,
metrics, and logs** — exported to a self-hosted **Grafana LGTM** stack (Loki, Grafana,
Tempo, Prometheus/Mimir). It's **off by default**; the OTel compose overlay turns it on.

## Run it

```sh
make otel-up      # full stack + collector + otel-lgtm (builds api/worker with .[otel])
# open Grafana at http://localhost:3001/grafana/  (GRAFANA_PORT; the sub-path is
# required — Grafana runs with serve_from_sub_path so Caddy's /grafana route works)
make otel-down
```

`make up` (no overlay) runs the app with telemetry **off** and no `/metrics` endpoint.

## Topology

```
browser SPA ──/otlp/v1/traces──▶ Caddy ──▶ otel-collector (Alloy) ──▶ otel-lgtm
   api  ──OTLP gRPC :4317──────────────────▶      (Loki / Tempo / Prometheus + Grafana)
 worker ──OTLP gRPC :4317──────────────────▶
```

- **api / worker**: OTLP gRPC to the collector (`OTEL_EXPORTER_OTLP_ENDPOINT`).
- **browser**: the SPA reads `otel_enabled` + `otel_traces_url` from `/api/v1/config`,
  lazy-loads the web SDK, and POSTs spans to the same-origin `/otlp/v1/traces`, which
  Caddy proxies to the collector. `traceparent` is propagated into `/api` calls, so a
  browser trace continues into the backend as **one waterfall**.

## What's exported

- **Traces** (Tempo): `ui.open_article / ui.subscribe / ui.search` → the API server span
  → `SELECT …` (SQLAlchemy). Worker: `poll_once → process_feed → GET <host> (httpx) →
  INSERT`, and `run_maintenance`.
- **Metrics** (Prometheus): domain instruments `alo_fetch_outcomes_total`,
  `alo_fetch_duration_milliseconds` (histogram → p95), `alo_entries_inserted_total`,
  and SQL-derived gauges `alo_worker_lag_seconds`, `alo_db_bytes`, `alo_table_{bytes,rows}`.
  HTTP server latency is auto-instrumented by FastAPI. Exemplars link a latency bucket to
  the trace that produced it.
- **Logs** (Loki): the api/worker/uvicorn loggers, trace-id stamped — filter by `trace_id`
  to jump from a trace to its logs.

Dashboards under `dashboards/` auto-provision into an **alo-reader** Grafana folder; drop
a new `*.json` there to add one.

## Alerts

`alerting/alo-floor.yml` provisions four rules into the same folder: worker lag, API
5xx rate, backup freshness, and host disk free. They are file-provisioned, so the
Grafana UI shows them read-only and they survive every container recreate.

`alerting/notifications.yml` is where they go: a Pushover contact point taking its
credentials from `ALO_PUSHOVER_USER_KEY` / `ALO_PUSHOVER_API_TOKEN`, plus the policy
that routes to it. The policy half is not optional, because the otel-lgtm image's
default route points at a receiver named `empty`. Set both keys in `.env` and alerts
arrive as a push on your phone; leave them unset and they stay in Grafana. Thresholds,
reasoning, a runbook per alert and how to swap the channel:
[`docs/ALERTS.md`](../../docs/ALERTS.md).

The disk numbers are the reason the collector mounts `/`, `/proc` and `/sys` read-only:
Postgres has no SQL for free space, so the unix exporter's filesystem collector runs in
Alloy and its metrics ride the same OTLP pipeline as everything else. Backup freshness
arrives the same way — the sidecar has no OTLP client and no port to scrape, so it
writes node_exporter textfile metrics onto the backups volume and the collector reads
that volume read-only.

## Disk budget, and why it is shaped like this

The telemetry stack writes to the same disk the alert floor watches, so it has to be
bounded. None of the three stores takes a disk quota, so read this table as *what the
bound is worth*, not as a guarantee:

| Store | Bound | Default | Sustained flood reaches |
| --- | --- | --- | --- |
| Prometheus | block retention, by size and age | 1 GB / 15d | ~1 GB of blocks, plus the head |
| Loki | ingestion rate x retention | 2 MB/s, 72h | ~500 GB |
| Tempo | ingestion rate x retention | 500 KB/s, 48h | ~86 GB |

Loki and Tempo reject writes over their rate and log the rejection; what got in expires
on the retention schedule, so their bound is the product of the two. A flood at the
limit for the whole window exceeds a small host's disk. That is the honest statement —
a rate limit slows an abuser, it does not stop one, and neither store exposes a storage
quota to set instead.

Prometheus is different but not a quota either. `--storage.tsdb.retention.size` is, in
its own `--help` wording, the "maximum number of bytes that can be stored for blocks":
it throttles nothing, and enforcement is a compaction noticing the total has been passed
and deleting the oldest blocks. The head block can't be deleted, so leave headroom above
the number instead of sizing a partition at exactly it. Units are powers of two — `1GB`
reads back from `/api/v1/status/flags` as `1GiB`. Both flags are deprecated in Prometheus
3.11 in favour of config-file fields and both are still honoured; the otel-lgtm image
exposes an argument hook and no config file, so arguments are what we have.

So the numbers are chosen to make the *expected* footprint trivial and the *pathological*
one slow, while the real protection stays where it belongs: **nothing untrusted can
reach these endpoints.** `/otlp` and `/grafana` are loopback-only in `deploy/Caddyfile`.
Reach them from your laptop with a tunnel rather than by widening the allow-list:

```sh
# A tunnel reproduces the URL Grafana already thinks it lives at, so nothing else to do:
ssh -N -L 3001:127.0.0.1:3001 you@your-host    # Grafana at http://localhost:3001/grafana/

# Any other origin needs GRAFANA_ROOT_URL set to the URL you will actually type:
tailscale serve --bg 3001                       # https://<host>.<tailnet>.ts.net/grafana/
```

`GF_SERVER_ROOT_URL` (from `GRAFANA_ROOT_URL` in `.env`) is what Grafana builds absolute
URLs from, and it ignores the request's `Host` header. Leave it at the loopback default
and a visitor opening `https://<host>.<tailnet>.ts.net/` is 301'd to
`http://localhost:3001/grafana/` — their own machine, where nothing is listening. Every
link in an alert notification comes from the same setting. Login redirects are relative
and keep working either way, which is what makes this easy to miss: most of Grafana
looks fine while the entry point and the alert links point somewhere private to the
server. Set it, then `docker compose ... up -d --force-recreate otel-lgtm`.

Both allow-lists are evaluated by Caddy, which runs in a container: the peer address it
sees for a request to the published port is the docker bridge gateway (`172.17.0.1` on a
default install), not `127.0.0.1`. So the loopback default denies the host too, and the
tunnel above deliberately targets Grafana's own loopback-published port (`3001`) instead
of going through Caddy. The two routes fail differently when denied — `/otlp` answers
403, while `/grafana` falls through to the SPA and answers 200 with `index.html`, which
keeps the ops surface invisible but also means a 200 there is not proof you got in.
Check the `Content-Type`: `application/json` is Grafana, `text/html` is the app.

Widening `ALO_GRAFANA_ALLOW_IPS` / `ALO_OTLP_ALLOW_IPS` is for a private CIDR you
control (a tailnet is `100.64.0.0/10`), not for the public internet. Adding the bridge
CIDR to reach Caddy's routes from the host also admits every other container on that
network, so prefer the port-forward. Browser tracing
from remote users is the one feature that genuinely needs a public `/otlp`; if you
want it, size these limits against your actual disk first and accept that the endpoint
is unauthenticated.

To resize, budget **per store** — they share one volume, so a number that makes only
Tempo's bound real still leaves Loki's ~500 GB standing beside it. Split the allowance
first, then divide each share by its retention window:

```
rate = share / retention_seconds, rounded DOWN

Tempo  2 GB over 48h  ->  2e9 / 172800          = 11574 B/s  -> TEMPO_INGEST_RATE_BYTES=11000
Loki   2 GB over 72h  ->  2e9 / 259200 / 2^20   = 0.0073 MiB -> LOKI_INGEST_RATE_MB=0.007
Prometheus            ->  its own size cap                   -> PROM_RETENTION_SIZE=512MB
```

Round down, and mind the unit: Loki's `_MB` flag is MiB (`1048576`), so `0.008` would
have been 2.17 GB against a 2 GB share, and `12000` B/s would have been 2.07 GB against
the same. Both are now under.

Those numbers are a **nominal allocation, not a ceiling**. They leave out the burst
allowances below, compaction lag between "expired" and "deleted", Prometheus's head, and
the scratch space compactors need while they work. What they buy is proportion — each
store gets a share instead of one store's bound being real and the rest unbounded — and
they are deliberately far below the defaults, which are sized so normal traffic never
trips them. **The disk alert is the backstop, not this arithmetic.**

**The burst allowances are not part of this arithmetic, and must not be scaled with the
rate.** Both stores admit a burst on top of the rate — Loki 6 MB, Tempo 20 MB by default,
now set explicitly in the overlay at those same values — but the burst is also **the
largest single push either store will accept**. Undersize it and a compliant batch is
rejected outright, while average throughput sits far below the rate limit. Dropped
telemetry, from a limit you set to protect a disk.

And the push that reaches the store is not ours to bound. Alloy's
`otelcol.processor.batch` batches by item count and timeout with `send_batch_max_size`
unset, so it emits no size limit of its own — and even capping it there is not enough,
because the `otel-lgtm` image runs its **own** collector in front of the stores, whose
config is a bare `batch:` with defaults:

```yaml
# /otel-lgtm/otelcol-config.yaml, inside the image
processors:
  batch:
```

That processor re-batches whatever Alloy sends before exporting to Tempo, Loki and
Prometheus, so a cap on our side can be recombined into a larger store-facing push.

The earlier hops do have limits, and they are worth knowing when you are diagnosing a
rejected export rather than sizing a disk — they just do not decide what the store sees:

| Hop | Limit |
| --- | --- |
| browser → Caddy `/otlp/v1/traces` | `request_body max_size 1MB` (`deploy/Caddyfile`) |
| api / worker → Alloy, OTLP gRPC | the receiver's default max receive size, 4 MiB |
| Alloy → otel-lgtm → the stores | re-batched, no size cap |

Bounding the store-facing push reliably means controlling that last hop, which means
building your own image or running the stores separately.

So: **leave the bursts at the defaults** unless you are doing exactly that. They are
spelled out in the overlay to be visible, not to be tuned.

One more thing at these rates: Loki's flag takes a float and reads back verbatim
(`0.007` appears as `ingestion_rate_mb: 0.007` in `/config`), and a rate far under your
real traffic drops telemetry rather than filling the disk slowly. Check the Loki and
Tempo logs for ingestion rejections before assuming the numbers are free.

## Notes

- **Edge / CDN**: the browser posts to `/otlp` same-origin through Caddy (the app never
  needs CORS). If you front Caddy with a CDN, the per-IP rate limit and client-IP already
  rely on `X-Real-IP` (see the Caddyfile) — trusted-proxy config there also governs OTLP.
- **Config knobs**: see the `OTEL_*` block in `.env.example`.
- The Grafana port should be bound to loopback / a private network in real prod — it's an
  internal ops surface.
