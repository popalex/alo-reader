#!/usr/bin/env bash
# WP-09/10 acceptance: the SPA boots to the three-pane app and drives the entry
# list + reading pane against real data.
#
# Brings up the compose stack (AUTH_MODE=none), seeds a large realistic dataset
# directly via the app inside the api container (scripts/seed_dev.py — no host
# Python needed), then runs Playwright against the Caddy-served SPA on :80.
#
#   ./scripts/e2e.sh              # up, seed, test, tear down
#   KEEP_UP=1 ./scripts/e2e.sh    # leave the stack running afterwards
set -euo pipefail

cd "$(dirname "$0")/.."

BASE="http://localhost/api/v1"
COMPOSE=(docker compose -f deploy/docker-compose.yml)

# AUTH_MODE=none → one auto-provisioned user; both seed_dev and the SPA resolve
# to it.
export AUTH_MODE=none

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

log "Seeding the dataset (20 feeds / ~5k entries) inside the api container"
"${COMPOSE[@]}" exec -T api python - < scripts/seed_dev.py

log "Running Playwright against the SPA"
pnpm -C web exec playwright test "$@"

printf '\n\033[32mPASS: entry list + reading pane e2e green.\033[0m\n'
