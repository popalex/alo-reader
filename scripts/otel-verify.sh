#!/usr/bin/env bash
# Prove traces, metrics and logs still reach Grafana LGTM, end to end. Run it before and
# after any change to the OpenTelemetry packages (web or API), FastAPI, the collector
# or otel-lgtm. Those upgrades fail quietly: an instrumentor outside its supported
# range instruments nothing, and a renamed Tempo flag leaves otel-lgtm restarting,
# while tests, lint and types all stay green.
#
# Brings up the full stack with the OTel overlay and a fixture feed, drives the real
# SPA in Chromium (subscribe, open an article, search), then queries Tempo, Prometheus,
# Loki and Grafana for what arrived. Exits 1 if any check fails. Like e2e.sh, it needs
# port 80 free and Playwright's Chromium. deploy/observability/README.md lists the checks.
#
#   ./scripts/otel-verify.sh                        # report in .otel-verify/<commit>
#   ./scripts/otel-verify.sh before                 # report in .otel-verify/before
#   BASELINE=before ./scripts/otel-verify.sh after  # also list what changed since "before"
#   OVERRIDE=images.yml ./scripts/otel-verify.sh    # one more compose overlay (e.g. image tags)
#   KEEP_UP=1 ./scripts/otel-verify.sh              # leave the stack up (Grafana on :3001)
set -euo pipefail

[[ -n "${OVERRIDE:-}" ]] && OVERRIDE=$(realpath "$OVERRIDE")
cd "$(dirname "$0")/.."

HERE=scripts/otel-verify
LABEL="${1:-$(git rev-parse --short HEAD)$(git diff --quiet HEAD || echo -dirty)}"
OUT=".otel-verify/$LABEL"
BASE_URL="http://localhost"
# Its own compose project, like e2e.sh and lighthouse.sh: the teardown runs `down -v`.
PROJECT=alo-otel-verify
COMPOSE=(docker compose -p "$PROJECT"
  -f deploy/docker-compose.yml -f deploy/docker-compose.otel.yml
  -f deploy/docker-compose.smoke.yml -f "$HERE/compose.yml"
  ${OVERRIDE:+-f "$OVERRIDE"})

export AUTH_MODE=none FETCH_ALLOW_HOSTS=feedfixture
# Caddy accepts browser OTLP only from ALO_OTLP_ALLOW_IPS. Chromium on the host reaches
# Caddy through the docker bridge, not from 127.0.0.1, so the default would refuse it.
# Opening it is safe only because compose.yml publishes Caddy on loopback alone.
export ALO_OTLP_ALLOW_IPS="0.0.0.0/0 ::/0"
# No --env-file, so .env is not read and Grafana keeps its default login; check.py uses it.

log() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

cleanup() {
  if [[ "${KEEP_UP:-0}" != "1" ]]; then
    log "Tearing down"
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

[[ -z "${BASELINE:-}" || -f ".otel-verify/$BASELINE/report.json" ]] \
  || fail "no earlier run named $BASELINE in .otel-verify/"
rm -rf "$OUT" && mkdir -p "$OUT"

log "Building and starting the stack with the OTel overlay ($LABEL)"
"${COMPOSE[@]}" up -d --build >"$OUT/up.log" 2>&1 || { tail -30 "$OUT/up.log"; fail "compose up failed"; }

log "Waiting for the API to be healthy"
for i in $(seq 1 90); do
  curl -fsS "$BASE_URL/api/v1/healthz" >/dev/null 2>&1 && break
  [[ $i == 90 ]] && fail "API did not become healthy"
  sleep 2
done

log "Recording installed OTel packages and instrumentor conflicts"
for svc in api worker; do
  "${COMPOSE[@]}" exec -T "$svc" python - <"$HERE/pkgs.py" >"$OUT/pkgs-$svc.json"
done

log "Browser: subscribe to the fixture feed"
BASE_URL="$BASE_URL" node "$HERE/drive.mjs" subscribe >"$OUT/drive-1.json"

log "Making the worker poll now"
"${COMPOSE[@]}" exec -T postgres psql -U alo -d alo -qc "update feeds set next_check_at = now()" >/dev/null
entries=0
for i in $(seq 1 45); do
  entries=$("${COMPOSE[@]}" exec -T postgres psql -U alo -d alo -tAc "select count(*) from entries")
  [[ $entries -gt 0 ]] && break
  sleep 2
done
[[ $entries -gt 0 ]] || fail "the worker ingested nothing from the fixture feed"

log "Browser: open an article and search"
BASE_URL="$BASE_URL" node "$HERE/drive.mjs" read >"$OUT/drive-2.json"

# Metrics leave every 60 s (the SDK's default export interval), then need a few
# seconds to be ingested.
log "Waiting 75 s for a metric export"
sleep 75

"${COMPOSE[@]}" logs --no-color otel-collector 2>&1 | grep -iE "error|fail|drop" >"$OUT/collector-errors.log" || true
log "Querying Tempo, Prometheus, Loki and Grafana"
docker run --rm --network "${PROJECT}_default" -v "$PWD/$HERE:/check:ro" python:3.14-slim \
  python -I /check/check.py >"$OUT/report.json"

[[ -s "$OUT/collector-errors.log" ]] && log "Collector logged errors: see $OUT/collector-errors.log"
if [[ -n "${BASELINE:-}" ]]; then
  log "Changes since $BASELINE"
  python3 "$HERE/report.py" compare ".otel-verify/$BASELINE" "$OUT"
fi
log "Results ($OUT)"
python3 "$HERE/report.py" summary "$OUT"
