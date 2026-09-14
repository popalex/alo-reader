# Observability (OpenTelemetry → Grafana LGTM)

alo-reader is instrumented with **OpenTelemetry** — one standard for **traces,
metrics, and logs** — exported to a self-hosted **Grafana LGTM** stack (Loki, Grafana,
Tempo, Prometheus/Mimir). It's **off by default**; the OTel compose overlay turns it on.

## Run it

```sh
make otel-up      # full stack + collector + otel-lgtm (builds api/worker with .[otel])
# open Grafana at http://localhost:3001  (GRAFANA_PORT)
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

`alerting/alo-floor.yml` provisions three rules into the same folder: worker lag, API
5xx rate, and host disk free. They are file-provisioned, so the Grafana UI shows them
read-only and they survive every container recreate.

`alerting/notifications.yml` is where they go: a Pushover contact point taking its
credentials from `ALO_PUSHOVER_USER_KEY` / `ALO_PUSHOVER_API_TOKEN`, plus the policy
that routes to it. The policy half is not optional, because the otel-lgtm image's
default route points at a receiver named `empty`. Set both keys in `.env` and alerts
arrive as a push on your phone; leave them unset and they stay in Grafana. Thresholds,
reasoning, a runbook per alert and how to swap the channel:
[`docs/ALERTS.md`](../../docs/ALERTS.md).

The disk numbers are the reason the collector mounts `/`, `/proc` and `/sys` read-only:
Postgres has no SQL for free space, so the unix exporter's filesystem collector runs in
Alloy and its metrics ride the same OTLP pipeline as everything else.

## Notes

- **Edge / CDN**: the browser posts to `/otlp` same-origin through Caddy (the app never
  needs CORS). If you front Caddy with a CDN, the per-IP rate limit and client-IP already
  rely on `X-Real-IP` (see the Caddyfile) — trusted-proxy config there also governs OTLP.
- **Config knobs**: see the `OTEL_*` block in `.env.example`.
- The Grafana port should be bound to loopback / a private network in real prod — it's an
  internal ops surface.
