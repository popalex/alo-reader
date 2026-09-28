#!/usr/bin/env bash
# Clerk-mode end-to-end suite: the real stack in AUTH_MODE=clerk against a dedicated
# Clerk *development* instance, driven by Playwright with @clerk/testing.
#
#   ./scripts/e2e-clerk.sh              # up, create test user, seed, test, clean up
#   KEEP_UP=1 ./scripts/e2e-clerk.sh    # leave the stack running afterwards
#
# Needs four values, from .env.e2e-clerk locally (gitignored) or the environment in CI:
#   CLERK_PUBLISHABLE_KEY, CLERK_ISSUER, CLERK_SECRET_KEY, CLERK_WEBHOOK_SECRET
# CLERK_SECRET_KEY is what lets the browser through the instance's bot protection
# (Clerk testing tokens) and creates/deletes the test users. It belongs to the e2e
# instance only and is never passed to the app: the API does not use it.
#
# Isolation: its own compose project, so `down -v` here can never touch the volumes
# of a stack you are running by hand. Each run uses its own +clerk_test addresses and
# deletes every Clerk user it created on exit, pass or fail.
set -euo pipefail
cd "$(dirname "$0")/.."

log() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

if [[ -f .env.e2e-clerk ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.e2e-clerk
  set +a
fi
for var in CLERK_PUBLISHABLE_KEY CLERK_ISSUER CLERK_SECRET_KEY CLERK_WEBHOOK_SECRET; do
  [[ -n "${!var:-}" ]] || fail "$var is not set (.env.e2e-clerk locally, E2E_CLERK_* secrets in CI)"
done
[[ "$CLERK_SECRET_KEY" == sk_test_* ]] || fail "CLERK_SECRET_KEY must be a development key (sk_test_)"

export AUTH_MODE=clerk
BASE="http://localhost/api/v1"
CLERK_API="https://api.clerk.com/v1"
COMPOSE=(docker compose -p alo-e2e-clerk -f deploy/docker-compose.yml)

RUN="${GITHUB_RUN_ID:-local}-$(date +%s)"
export E2E_CLERK_EMAIL="alo-e2e-${RUN}+clerk_test@example.com"
export E2E_CLERK_SIGNUP_EMAIL="alo-e2e-${RUN}-signup+clerk_test@example.com"
export E2E_CLERK_DELETE_EMAIL="alo-e2e-${RUN}-delete+clerk_test@example.com"

clerk_api() { curl -fsS -H "Authorization: Bearer $CLERK_SECRET_KEY" -H "Content-Type: application/json" "$@"; }

cleanup() {
  local status=$?
  log "Deleting this run's Clerk users"
  for email in "$E2E_CLERK_EMAIL" "$E2E_CLERK_SIGNUP_EMAIL" "$E2E_CLERK_DELETE_EMAIL"; do
    for id in $(clerk_api -G "$CLERK_API/users" --data-urlencode "email_address=$email" | jq -r '.[].id' 2>/dev/null); do
      clerk_api -X DELETE "$CLERK_API/users/$id" >/dev/null && echo "deleted $id"
    done
  done
  if [[ "${KEEP_UP:-0}" != "1" ]]; then
    log "Tearing down"
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

log "Building and starting the stack in AUTH_MODE=clerk (from an empty database)"
# Every run starts clean: a KEEP_UP=1 run leaves the previous run's user and its
# subscriptions behind, and reseeding feeds under them fails. This compose project
# is the suite's own, so dropping its volumes touches nothing else.
"${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d --build

log "Waiting for the API to be healthy"
for i in $(seq 1 60); do
  curl -fsS "$BASE/healthz" >/dev/null 2>&1 && break
  [[ $i == 60 ]] && fail "API did not become healthy"
  sleep 2
done
[[ "$(curl -fsS "$BASE/config" | jq -r .auth_mode)" == "clerk" ]] || fail "/config does not report clerk mode"

log "Creating the test user in Clerk"
USER_ID=$(clerk_api -X POST "$CLERK_API/users" \
  -d "$(jq -n --arg e "$E2E_CLERK_EMAIL" '{email_address: [$e], skip_password_requirement: true}')" | jq -r .id)
[[ "$USER_ID" == user_* ]] || fail "could not create the Clerk test user"
export E2E_CLERK_USER_ID="$USER_ID"

log "Seeding the dataset for that user"
"${COMPOSE[@]}" exec -T -e SEED_CLERK_USER_ID="$USER_ID" api python - < scripts/seed_dev.py

log "Running the Clerk-mode Playwright suite"
status=0
pnpm -C web exec playwright test --config playwright.clerk.config.ts "$@" || status=$?
if [[ $status -eq 0 ]]; then
  printf '\n\033[32mPASS: Clerk-mode e2e green.\033[0m\n'
else
  printf '\n\033[31mFAIL: Playwright reported failures (exit %d).\033[0m\n' "$status" >&2
fi
exit "$status"
