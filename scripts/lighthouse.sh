#!/usr/bin/env bash
# WP-09 acceptance: Lighthouse performance budget on the built SPA.
#
# Brings up the stack (AUTH_MODE=none) so Caddy serves the production build on
# :80, runs Lighthouse against it, and fails if the median performance score of
# LH_RUNS runs is below the budget. Lighthouse comes from scripts/lighthouse, its own
# locked project, so every run uses the same dependency tree.
#
#   ./scripts/lighthouse.sh              # up, measure, tear down
#   LH_MIN_PERF=95 ./scripts/lighthouse.sh
#   LH_RUNS=5 ./scripts/lighthouse.sh    # more runs, steadier median
#   KEEP_UP=1 ./scripts/lighthouse.sh    # leave the stack running
set -euo pipefail

cd "$(dirname "$0")/.."

# The app, not the site root: since WP-17 the root is either the landing page
# (AUTH_MODE=clerk) or a redirect to /app/ (none), and this script measures the
# app. The landing page gets its own run once it ships.
URL="http://localhost/app/"
# Its own compose project: the teardown below runs `down -v`, and under the default
# project name that deleted the database of whatever stack `make up` was running.
COMPOSE=(docker compose -p alo-lighthouse -f deploy/docker-compose.yml)
MIN_PERF=${LH_MIN_PERF:-90}
# One run on a shared CI runner swings by about five points on unchanged code (88 to 93
# across October 2026), so a single score against a budget of 90 failed at random. The
# median of three is what Lighthouse's own variability guide recommends.
RUNS=${LH_RUNS:-3}
OUT_DIR="$(mktemp -d)"

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

# A locked install, not `pnpm dlx lighthouse`: dlx fetched the newest Lighthouse and
# resolved its dependencies afresh on every run, so two CI runs of the same commit
# could measure with different trees. Kept out of web/: Lighthouse's Sentry brings its own
# OpenTelemetry packages, and web/ must hold exactly one OTel tree.
log "Installing Lighthouse from scripts/lighthouse/pnpm-lock.yaml"
pnpm --dir scripts/lighthouse install --frozen-lockfile --silent
LIGHTHOUSE=scripts/lighthouse/node_modules/.bin/lighthouse

SCORES=()
for run in $(seq 1 "$RUNS"); do
  log "Running Lighthouse against $URL ($run of $RUNS)"
  "$LIGHTHOUSE" "$URL" \
    --only-categories=performance \
    --output=json --output-path="$OUT_DIR/lighthouse-$run.json" \
    --chrome-flags="--headless=new --no-sandbox --disable-gpu" \
    --quiet
  SCORES+=("$(python3 -c "import json; print(round(json.load(open('$OUT_DIR/lighthouse-$run.json'))['categories']['performance']['score'] * 100))")")
  log "Run $run: ${SCORES[-1]}"
done

# Compared unrounded: with an even LH_RUNS the median can fall between two scores,
# and rounding 89.5 up would pass a run that is under budget.
SCORE=$(python3 -c "import statistics, sys; print(f'{statistics.median(int(s) for s in sys.argv[1:]):g}')" "${SCORES[@]}")
log "Performance score: ${SCORE}, median of ${SCORES[*]} (budget ${MIN_PERF})"
python3 -c "import sys; sys.exit(float(sys.argv[1]) < float(sys.argv[2]))" "$SCORE" "$MIN_PERF" \
  || fail "performance ${SCORE} below budget ${MIN_PERF}"

printf '\n\033[32mPASS: Lighthouse performance %s >= %s.\033[0m\n' "$SCORE" "$MIN_PERF"
