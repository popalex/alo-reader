#!/usr/bin/env bash
# End-to-end smoke test: the reader is usable via curl with a PAT (WP-07).
#
# Brings up the compose stack plus a static feed server, then drives the real
# product flow against the API through Caddy: create a PAT, subscribe, let the
# worker poll the fixture, list entries, read one, mark read, and watch the
# unread count go to zero. Prints PASS/FAIL and exits non-zero on failure.
#
#   ./scripts/smoke.sh              # up, test, then tear the stack down
#   KEEP_UP=1 ./scripts/smoke.sh    # leave the stack running afterwards
set -euo pipefail

cd "$(dirname "$0")/.."

BASE="http://localhost/api/v1"
FEED_URL="http://feedfixture/rss.xml"
COMPOSE=(docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.smoke.yml)

# AUTH_MODE=none → single auto-provisioned user; FETCH_ALLOW_HOSTS lets the worker
# reach the compose-internal fixture past the SSRF guard.
export AUTH_MODE=none
export FETCH_ALLOW_HOSTS=feedfixture

log() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

# Extract a field from a JSON stdin using python3 (no jq dependency).
jget() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }

cleanup() {
  if [[ "${KEEP_UP:-0}" != "1" ]]; then
    log "Tearing down"
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

log "Building and starting the stack"
"${COMPOSE[@]}" up -d --build

log "Waiting for the API to be healthy"
for i in $(seq 1 60); do
  if curl -fsS "$BASE/healthz" >/dev/null 2>&1; then break; fi
  [[ $i == 60 ]] && fail "API did not become healthy"
  sleep 2
done
echo "API is up."

log "Creating a PAT (AUTH_MODE=none auto-provisions the single user)"
TOKEN=$(curl -fsS -X POST "$BASE/tokens" -H 'content-type: application/json' \
  -d '{"label":"smoke"}' | jget "['token']")
[[ -n "$TOKEN" ]] || fail "no token returned"
AUTH=(-H "Authorization: Bearer $TOKEN")
echo "Got a PAT."

log "Subscribing to the fixture feed"
curl -fsS -X POST "$BASE/subscriptions" "${AUTH[@]}" -H 'content-type: application/json' \
  -d "{\"feed_url\":\"$FEED_URL\"}" | jget "['feed_id']" >/dev/null
echo "Subscribed to $FEED_URL."

log "Waiting for the worker to poll and ingest entries"
UNREAD=0
for i in $(seq 1 30); do
  UNREAD=$(curl -fsS "$BASE/counts" "${AUTH[@]}" | jget "['total_unread']")
  [[ "$UNREAD" -gt 0 ]] && break
  sleep 2
done
[[ "$UNREAD" -gt 0 ]] || fail "no entries ingested (unread still 0)"
echo "Unread count: $UNREAD."

log "Listing entries in the 'all' stream"
ENTRIES=$(curl -fsS "$BASE/streams/all/entries?status=unread" "${AUTH[@]}")
COUNT=$(echo "$ENTRIES" | jget "['entries'].__len__()")
FIRST_ID=$(echo "$ENTRIES" | jget "['entries'][0]['id']")
MAX_ID=$(echo "$ENTRIES" | jget "['entries'][0]['id']")
echo "Listed $COUNT entries; newest id=$FIRST_ID."

log "Reading one entry in full"
TITLE=$(curl -fsS "$BASE/entries/$FIRST_ID" "${AUTH[@]}" | jget "['title']")
echo "Read entry: $TITLE"

log "Marking the stream read up to the newest entry"
curl -fsS -X POST "$BASE/streams/all/mark-read" "${AUTH[@]}" -H 'content-type: application/json' \
  -d "{\"max_entry_id\":$MAX_ID}" | jget "['updated']" >/dev/null

AFTER=$(curl -fsS "$BASE/counts" "${AUTH[@]}" | jget "['total_unread']")
echo "Unread after mark-read: $AFTER."
[[ "$AFTER" == "0" ]] || fail "expected 0 unread after mark-read, got $AFTER"

printf '\n\033[32mPASS: subscribe -> poll -> list -> read -> mark-read -> count all worked.\033[0m\n'
