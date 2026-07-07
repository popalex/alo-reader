#!/usr/bin/env bash
# WP-09 acceptance: the SPA boots to the three-pane app with real sidebar data.
#
# Brings up the compose stack (AUTH_MODE=none) plus the fixture feed server,
# seeds a folder + subscription, waits for the worker to poll it, then runs
# Playwright against the built SPA served by Caddy on :80.
#
#   ./scripts/e2e.sh              # up, test, tear down
#   KEEP_UP=1 ./scripts/e2e.sh    # leave the stack running afterwards
set -euo pipefail

cd "$(dirname "$0")/.."

BASE="http://localhost/api/v1"
FEED_URL="http://feedfixture/rss.xml"
COMPOSE=(docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.smoke.yml)

# AUTH_MODE=none → one auto-provisioned user; bare requests (curl below and the
# SPA alike) resolve to it. FETCH_ALLOW_HOSTS lets the worker reach the internal
# fixture past the SSRF guard.
export AUTH_MODE=none
export FETCH_ALLOW_HOSTS=feedfixture

jget() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }
log() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

cleanup() {
  if [[ "${KEEP_UP:-0}" != "1" ]]; then
    log "Tearing down"
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

log "Building and starting the stack (Caddy serves the built SPA)"
"${COMPOSE[@]}" up -d --build

log "Waiting for the API to be healthy"
for i in $(seq 1 60); do
  curl -fsS "$BASE/healthz" >/dev/null 2>&1 && break
  [[ $i == 60 ]] && fail "API did not become healthy"
  sleep 2
done

log "Seeding a folder + subscription to the fixture feed"
FID=$(curl -fsS -X POST "$BASE/folders" -H 'content-type: application/json' \
  -d '{"name":"Tech"}' | jget "['id']")
curl -fsS -X POST "$BASE/subscriptions" -H 'content-type: application/json' \
  -d "{\"feed_url\":\"$FEED_URL\",\"folder_id\":$FID}" >/dev/null

log "Waiting for the worker to poll the fixture feed"
for i in $(seq 1 30); do
  U=$(curl -fsS "$BASE/counts" | jget "['total_unread']")
  [[ "$U" -gt 0 ]] && break
  [[ $i == 30 ]] && fail "no entries ingested (unread still 0)"
  sleep 2
done

log "Running Playwright against the SPA"
pnpm -C web exec playwright test "$@"

printf '\n\033[32mPASS: SPA boots to the three-pane app with live sidebar data.\033[0m\n'
