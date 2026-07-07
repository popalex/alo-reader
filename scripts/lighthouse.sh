#!/usr/bin/env bash
# WP-09 acceptance: Lighthouse performance budget on the built SPA.
#
# Brings up the stack (AUTH_MODE=none) so Caddy serves the production build on
# :80, runs Lighthouse (via pnpm dlx — no project dependency added) against it,
# and fails if the performance score is below the budget.
#
#   ./scripts/lighthouse.sh              # up, measure, tear down
#   LH_MIN_PERF=95 ./scripts/lighthouse.sh
#   KEEP_UP=1 ./scripts/lighthouse.sh    # leave the stack running
set -euo pipefail

cd "$(dirname "$0")/.."

URL="http://localhost/"
COMPOSE=(docker compose -f deploy/docker-compose.yml)
MIN_PERF=${LH_MIN_PERF:-90}
OUT="$(mktemp -d)/lighthouse.json"

# The API refuses to boot without an explicit AUTH_MODE; none = single user.
export AUTH_MODE=none

# Reuse a Playwright-installed Chromium rather than downloading another browser.
# Honour an explicit CHROME_PATH; else glob the Playwright cache (the build
# number varies by version); else let chrome-launcher auto-detect a system Chrome.
if [[ -z "${CHROME_PATH:-}" ]]; then
  CHROME_PATH=$(ls -1 "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | sort -V | tail -n1 || true)
fi
[[ -n "${CHROME_PATH:-}" ]] && export CHROME_PATH

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
  curl -fsS "http://localhost/api/v1/healthz" >/dev/null 2>&1 && break
  [[ $i == 60 ]] && fail "API did not become healthy"
  sleep 2
done

log "Running Lighthouse against $URL"
pnpm dlx lighthouse "$URL" \
  --only-categories=performance \
  --output=json --output-path="$OUT" \
  --chrome-flags="--headless=new --no-sandbox --disable-gpu" \
  --quiet

SCORE=$(python3 -c "import json; print(round(json.load(open('$OUT'))['categories']['performance']['score'] * 100))")
log "Performance score: ${SCORE} (budget ${MIN_PERF})"
[[ "$SCORE" -ge "$MIN_PERF" ]] || fail "performance ${SCORE} below budget ${MIN_PERF}"

printf '\n\033[32mPASS: Lighthouse performance %s >= %s.\033[0m\n' "$SCORE" "$MIN_PERF"
