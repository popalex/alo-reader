#!/usr/bin/env bash
# Prove the alert path reaches your phone, without waiting for something to break.
#
#   ./scripts/test-alerts.sh              # credentials, then a real firing alert
#   ./scripts/test-alerts.sh --no-probe   # skip the credential check, exercise Grafana only
#
# Stage 1 posts straight to Pushover with the keys from .env, which separates "wrong
# keys" from "wrong wiring". Stage 2 creates a temporary alert rule that breaches
# immediately, so Grafana notifies through the same contact point and policy the real
# floor uses, then deletes it. Deleting it sends the resolved notification too, so you
# see both ends. Needs the OTel stack up (make otel-up).
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
PROBE=1
[[ "${1:-}" == "--no-probe" ]] && PROBE=0

read_env() {
	[[ -f $ENV_FILE ]] || return 0
	# Last uncommented assignment wins, quotes stripped: the same precedence compose uses.
	# The `|| true` is load-bearing. Without it a key that is simply absent makes grep
	# exit 1, which under `set -e` kills the script mid-assignment, before it can print
	# the message explaining what is missing.
	{ grep -E "^[[:space:]]*$1=" "$ENV_FILE" || true; } | tail -1 | cut -d= -f2- |
		sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

USER_KEY="${ALO_PUSHOVER_USER_KEY:-$(read_env ALO_PUSHOVER_USER_KEY)}"
API_TOKEN="${ALO_PUSHOVER_API_TOKEN:-$(read_env ALO_PUSHOVER_API_TOKEN)}"
GRAFANA_PORT="${GRAFANA_PORT:-$(read_env GRAFANA_PORT)}"
GRAFANA_PORT="${GRAFANA_PORT:-3001}"
GRAFANA_USER="${GRAFANA_ADMIN_USER:-$(read_env GRAFANA_ADMIN_USER)}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASS="${GRAFANA_ADMIN_PASSWORD:-$(read_env GRAFANA_ADMIN_PASSWORD)}"
GRAFANA_PASS="${GRAFANA_PASS:-admin}"
GRAFANA="http://localhost:${GRAFANA_PORT}/grafana"
CURL=(curl -sS -u "${GRAFANA_USER}:${GRAFANA_PASS}")

if [[ -z $USER_KEY || -z $API_TOKEN ]]; then
	echo "ALO_PUSHOVER_USER_KEY / ALO_PUSHOVER_API_TOKEN are not set in $ENV_FILE." >&2
	echo "User key: pushover.net dashboard. API token: pushover.net/apps/build." >&2
	exit 1
fi

if ((PROBE)); then
	echo "1/2  Posting straight to Pushover with your keys..."
	response=$(curl -sS -F "token=${API_TOKEN}" -F "user=${USER_KEY}" \
		-F "title=alo-reader" -F "message=credential check, ignore me" \
		https://api.pushover.net/1/messages.json)
	if [[ $response != *'"status":1'* ]]; then
		echo "     Pushover rejected it: $response" >&2
		echo "     A bad token usually means the user key was pasted in its place." >&2
		exit 1
	fi
	echo "     Accepted. That is one push on your phone already."
fi

echo "2/2  Firing a temporary alert through Grafana..."
if ! "${CURL[@]}" -o /dev/null "${GRAFANA}/api/health" 2>/dev/null; then
	echo "     Grafana is not answering on ${GRAFANA}. Start it with: make otel-up" >&2
	exit 1
fi

folder=$("${CURL[@]}" "${GRAFANA}/api/v1/provisioning/alert-rules" |
	python3 -c 'import json,sys; rules=json.load(sys.stdin); print(rules[0]["folderUID"] if rules else "")')
if [[ -z $folder ]]; then
	echo "     No provisioned alert rules found, so there is no folder to put the test in." >&2
	exit 1
fi

uid="alo-alert-selftest"
cleanup() {
	"${CURL[@]}" -o /dev/null -X DELETE -H 'X-Disable-Provenance: true' \
		"${GRAFANA}/api/v1/provisioning/alert-rules/${uid}" 2>/dev/null || true
}
trap cleanup EXIT

# vector(1) > 0 is true the moment it is evaluated, and "for": "0s" means no pending
# period, so this goes straight to Alerting on the next evaluation tick.
"${CURL[@]}" -o /dev/null -X POST -H 'Content-Type: application/json' -H 'X-Disable-Provenance: true' \
	-d '{"uid":"'"$uid"'","title":"alert self-test","folderUID":"'"$folder"'","ruleGroup":"verify",
       "orgID":1,"condition":"THRESHOLD","for":"0s","noDataState":"OK","execErrState":"Alerting",
       "annotations":{"summary":"self-test from scripts/test-alerts.sh, nothing is wrong"},
       "data":[{"refId":"QUERY","datasourceUid":"prometheus","relativeTimeRange":{"from":600,"to":0},
                "model":{"refId":"QUERY","instant":true,"expr":"vector(1)"}},
               {"refId":"THRESHOLD","datasourceUid":"__expr__",
                "model":{"refId":"THRESHOLD","type":"threshold","expression":"QUERY",
                         "conditions":[{"evaluator":{"type":"gt","params":[0]}}]}}]}' \
	"${GRAFANA}/api/v1/provisioning/alert-rules"

# Grafana's alertmanager records the last delivery attempt per integration, which is
# the only authoritative answer to "did it actually send". Remember where it stands
# before the test so a stale attempt from an earlier run cannot be mistaken for ours.
notify_state() {
	"${CURL[@]}" "${GRAFANA}/api/alertmanager/grafana/config/api/v1/receivers" |
		python3 -c '
import json, sys
for receiver in json.load(sys.stdin):
    for integration in receiver.get("integrations", []):
        if receiver["name"] == sys.argv[1]:
            print(integration.get("lastNotifyAttempt", ""), integration.get("lastNotifyAttemptError", ""), sep="\t")
' "$RECEIVER"
}

RECEIVER="${RECEIVER:-alo-pushover}"
before=$(notify_state | cut -f1)

state=""
for _ in $(seq 1 24); do
	sleep 5
	state=$("${CURL[@]}" "${GRAFANA}/api/prometheus/grafana/api/v1/rules" |
		python3 -c '
import json, sys
rules = [r for g in json.load(sys.stdin)["data"]["groups"] for r in g["rules"]]
print(next((r["state"] for r in rules if r["name"] == "alert self-test"), ""))')
	[[ $state == firing ]] && break
done

if [[ $state != firing ]]; then
	echo "     The rule never reached firing (state: ${state:-unknown}). Grafana evaluates" >&2
	echo "     on its own tick, so try again, or look at Alerting > Alert rules." >&2
	exit 1
fi
echo "     Rule is firing. Waiting for Grafana to send (group_wait is 30s)..."

# Poll until the attempt timestamp moves. Deleting the rule any earlier cancels the
# pending notification, which is how an earlier version of this script managed to
# report success without anything being sent.
attempt=""
error=""
for _ in $(seq 1 30); do
	sleep 5
	IFS=$'\t' read -r attempt error < <(notify_state)
	[[ -n $attempt && $attempt != "$before" ]] && break
done

if [[ -z $attempt || $attempt == "$before" ]]; then
	echo "     Grafana never attempted a delivery. Check that the notification policy" >&2
	echo "     routes to ${RECEIVER} (Alerting > Notification policies)." >&2
	exit 1
fi

if [[ -n $error ]]; then
	echo "     Delivery failed: $error" >&2
	echo "     Wrong keys are the usual cause; ./scripts/test-alerts.sh without" >&2
	echo "     --no-probe checks them against Pushover directly." >&2
	exit 1
fi

echo "     Grafana delivered it at ${attempt} with no error."

echo
echo "Done. One push now, the one Grafana just confirmed. A second follows about five"
echo "minutes later: deleting the test rule does not resolve the alert, it lets it"
echo "expire, and the resolved notification goes out on that timeout."
echo
echo "Grafana can only vouch for the handoff to Pushover. If your phone stayed quiet,"
echo "pushover.net's own notification log says whether the message reached a device."
