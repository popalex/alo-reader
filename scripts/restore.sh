#!/usr/bin/env bash
# Restore the database from a backup taken by the `backup` sidecar.
#
#   scripts/restore.sh                      # the newest backup, after confirming
#   scripts/restore.sh alo-2026...Z.dump.zst
#   scripts/restore.sh --yes --latest       # no prompt, for a scripted drill
#
# This throws away the current contents of the database. The stack is stopped
# around the restore because pg_restore --clean cannot drop objects that open
# connections are holding, and a half-restored database served to users is worse
# than a few seconds of downtime.
#
# DESIGN.md §1.5 makes the restore drill a release gate rather than a footnote:
# a backup nobody has restored is a guess, not a backup.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_ENV=()
[[ -f .env ]] && COMPOSE_ENV=(--env-file .env)
DC=(docker compose "${COMPOSE_ENV[@]}" -f deploy/docker-compose.yml)

assume_yes=false
target=""
for arg in "$@"; do
	case "$arg" in
		--yes | -y) assume_yes=true ;;
		--latest) target="" ;;
		-h | --help) sed -n '2,12p' "$0" | sed 's/^# \?//'; exit 0 ;;
		-*) echo "unknown option: $arg" >&2; exit 64 ;;
		*) target="$arg" ;;
	esac
done

# The database name and role live in .env; compose defaults them to alo.
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
PG_DB=$(env_value POSTGRES_DB); PG_DB=${PG_DB:-alo}
PG_USER=$(env_value POSTGRES_USER); PG_USER=${PG_USER:-alo}

if ! "${DC[@]}" ps --status running --services 2>/dev/null | grep -qx postgres; then
	echo "postgres is not running; start the stack first (make up)" >&2
	exit 1
fi

if [[ -z "$target" ]]; then
	target=$("${DC[@]}" exec -T backup backup list | head -1 | xargs basename)
	echo "newest backup: $target"
fi

if [[ "$assume_yes" != true ]]; then
	echo
	echo "About to restore ${target} into database '${PG_DB}'."
	echo "Everything currently in that database is replaced. This cannot be undone."
	read -r -p "Type the database name to continue: " confirm
	if [[ "$confirm" != "$PG_DB" ]]; then
		echo "aborted" >&2
		exit 1
	fi
fi

echo "==> stopping api, worker and the backup sidecar"
"${DC[@]}" stop api worker backup >/dev/null

# Anything still attached blocks the DROPs that --clean issues. The api and worker
# are down by now; this catches psql sessions and anything else holding a handle.
echo "==> closing remaining connections to $PG_DB"
"${DC[@]}" exec -T postgres psql -U "$PG_USER" -d postgres -qtAc \
	"select pg_terminate_backend(pid) from pg_stat_activity
	 where datname = '$PG_DB' and pid <> pg_backend_pid()" >/dev/null

echo "==> restoring"
"${DC[@]}" run --rm -T backup restore "$target"

echo "==> starting api, worker and the backup sidecar"
"${DC[@]}" start api worker backup >/dev/null

echo
echo "Restored $target."
echo "Check it: curl -s localhost/api/v1/healthz"
