#!/bin/sh
# Nightly pg_dump -> zstd, kept on a volume and optionally copied off-box.
#
# Subcommands:
#   loop              take a backup at BACKUP_SCHEDULE_UTC every day (the default)
#   once              take one backup and exit; non-zero if it fails
#   list              list the backups on the volume, newest first
#   restore <file>    restore one into the live database (scripts/restore.sh drives this)
#
# Connection comes from the standard PG* variables, not the app's DATABASE_URL,
# which is SQLAlchemy-flavoured (postgresql+asyncpg://) and libpq rejects it.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_SCHEDULE_UTC="${BACKUP_SCHEDULE_UTC:-03:30}"
BACKUP_ON_START="${BACKUP_ON_START:-false}"
BACKUP_ZSTD_LEVEL="${BACKUP_ZSTD_LEVEL:-10}"
BACKUP_RCLONE_REMOTE="${BACKUP_RCLONE_REMOTE:-}"
# node_exporter textfile format. The collector's unix exporter reads this directory
# (deploy/observability/alloy/config.alloy) and the "Backup freshness" rule alerts on
# it (deploy/observability/alerting/alo-floor.yml). Lives on the backups volume because
# that volume is already the state: the newest dump's mtime *is* the answer, so a
# restarted sidecar, or one that lost its memory, recomputes it instead of resetting it.
BACKUP_METRICS_DIR="${BACKUP_METRICS_DIR:-$BACKUP_DIR/metrics}"
BACKUP_METRICS_FILE="$BACKUP_METRICS_DIR/alo_backup.prom"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: $*"; }
# Exits the current shell. That is deliberately two different things depending on who
# calls it: take_backup has a ( ) body, so die aborts one attempt and the caller sees a
# non-zero return; cmd_restore has a { } body, so die ends the process, which is what a
# one-shot restore command should do.
#
# take_backup's subshell is the fix for a real bug: `exit` from a { } body ends the
# whole script, which made the `take_backup || log WARNING` guards in cmd_loop dead
# code — a failed dump exited 1, restart: unless-stopped brought the container straight
# back, and the retry failed the same way, a restart loop that buries the one line
# saying what broke.
#
# `return 1` would be worse than either: it only returns from die, so the caller
# carries on past the failure (mv of a file that was never renamed, du of a file that
# is not there) before reporting anything.
die() { log "ERROR: $*"; exit 1; }

# Seconds until the next BACKUP_SCHEDULE_UTC. awk does the arithmetic because
# POSIX sh reads a zero-padded hour like 08 as octal and errors out.
seconds_until_schedule() {
	date -u +%H:%M:%S | awk -F: -v target="$BACKUP_SCHEDULE_UTC" '
		BEGIN { split(target, t, ":") }
		{
			now = $1 * 3600 + $2 * 60 + $3
			want = t[1] * 3600 + t[2] * 60
			delta = want - now
			if (delta <= 0) delta += 86400
			print delta
		}'
}

# Value of one metric in the file we wrote last time, or 0. Used only for the things
# the volume cannot answer on its own (was the last attempt a failure, and when).
prev_metric() {
	[ -f "$BACKUP_METRICS_FILE" ] || { echo 0; return 0; }
	awk -v name="$1" '$1 == name { v = $2 } END { print (v == "" ? "0" : v) }' \
		"$BACKUP_METRICS_FILE"
}

# Publish the freshness metrics. $1/$2 are this attempt's unix time and 1|0, or "-" to
# keep whatever the last write recorded (used at start-up, which is not an attempt).
#
# Written to a temporary file and renamed, because the exporter reads this directory on
# its own schedule and a half-written file is a scrape error, not a missing sample.
write_metrics() {
	attempt_ts="$1"
	attempt_ok="$2"
	if [ "$attempt_ts" = "-" ]; then
		attempt_ts=$(prev_metric alo_backup_last_attempt_timestamp_seconds)
	fi
	if [ "$attempt_ok" = "-" ]; then
		attempt_ok=$(prev_metric alo_backup_last_attempt_success)
	fi

	newest=$(ls -1t "$BACKUP_DIR"/alo-*.dump.zst 2>/dev/null | head -1 || true)
	if [ -n "$newest" ]; then
		success_ts=$(stat -c %Y "$newest")
		success_bytes=$(stat -c %s "$newest")
	else
		# Nothing on the volume: a fresh install, or every dump has aged past
		# BACKUP_RETENTION_DAYS because backups stopped that long ago. Carry the last
		# published timestamp so the second case keeps ageing instead of silently
		# resetting the alert; on a fresh install there is nothing to carry, so the
		# clock starts now and the first scheduled run has one interval to land.
		success_ts=$(prev_metric alo_backup_last_success_timestamp_seconds)
		success_bytes=0
		if [ "$success_ts" = "0" ]; then
			success_ts=$(date -u +%s)
			log "no backups on the volume yet; freshness clock starts now"
		fi
	fi

	mkdir -p "$BACKUP_METRICS_DIR"
	cat >"$BACKUP_METRICS_FILE.tmp" <<EOF
# HELP alo_backup_last_success_timestamp_seconds Unix time of the newest verified backup on the volume.
# TYPE alo_backup_last_success_timestamp_seconds gauge
alo_backup_last_success_timestamp_seconds $success_ts
# HELP alo_backup_last_success_bytes Compressed size of that backup, 0 if none is on the volume.
# TYPE alo_backup_last_success_bytes gauge
alo_backup_last_success_bytes $success_bytes
# HELP alo_backup_last_attempt_timestamp_seconds Unix time of the last attempt, successful or not.
# TYPE alo_backup_last_attempt_timestamp_seconds gauge
alo_backup_last_attempt_timestamp_seconds $attempt_ts
# HELP alo_backup_last_attempt_success 1 if that attempt produced a verified backup. 0 alongside a zero timestamp means no attempt yet, not a failure.
# TYPE alo_backup_last_attempt_success gauge
alo_backup_last_attempt_success $attempt_ok
EOF
	mv "$BACKUP_METRICS_FILE.tmp" "$BACKUP_METRICS_FILE"
}

take_backup() (
	stamp=$(date -u +%Y%m%dT%H%M%SZ)
	final="$BACKUP_DIR/alo-$stamp.dump.zst"
	partial="$final.partial"

	mkdir -p "$BACKUP_DIR"
	log "dumping $PGDATABASE to $final"

	# -Fc keeps pg_restore's selective and parallel restore available; -Z0 turns
	# off pg_dump's own gzip so zstd is not compressing compressed bytes.
	#
	# A failing pg_dump in a pipeline is invisible here -- POSIX sh has no pipefail,
	# and zstd happily writes a valid frame around a truncated or empty stream, so
	# the backup would look like it worked. The integrity checks below are what
	# actually catch it, which is why they are not optional.
	if ! pg_dump -Fc -Z0 2>/tmp/dump.err | zstd -q -"$BACKUP_ZSTD_LEVEL" -T0 -o "$partial"; then
		rm -f "$partial"
		die "pg_dump failed: $(head -3 /tmp/dump.err 2>/dev/null)"
	fi

	# Two integrity checks before the file is allowed to count as a backup: the
	# zstd frame is intact, and pg_restore can read the archive's table of
	# contents. A truncated dump passes neither, and finding that out now beats
	# finding it out during a restore.
	zstd -q -t "$partial" || { rm -f "$partial"; die "zstd verify failed"; }
	zstd -dc "$partial" | pg_restore -l >/dev/null 2>&1 ||
		{ rm -f "$partial"; die "pg_restore could not read the archive"; }

	# Rename last, so a crash mid-dump leaves a .partial rather than something
	# that looks restorable.
	#
	# Checked explicitly, not left to set -e: take_backup is called as
	# `take_backup || log ...`, and POSIX shells suppress errexit for the whole of a
	# command on the left of ||, subshell included. A failed rename would otherwise
	# fall straight through to the success line and report a backup that does not
	# exist — the one failure mode worse than no backup at all.
	mv "$partial" "$final" || { rm -f "$partial"; die "could not finalize $final"; }
	log "wrote $final ($(du -h "$final" | cut -f1))"

	prune_local
	if [ -n "$BACKUP_RCLONE_REMOTE" ]; then
		push_remote "$final"
	fi
	return 0
)

# take_backup plus the metric write, so every exit path publishes an outcome — the
# failing sidecar is the case the freshness alert exists for, and it is the one that
# would otherwise leave yesterday's numbers standing with nothing marking them stale.
attempt_backup() {
	if take_backup; then
		write_metrics "$(date -u +%s)" 1
		return 0
	fi
	write_metrics "$(date -u +%s)" 0
	return 1
}

prune_local() {
	# -delete is not in every busybox build; -exec rm is.
	found=$(find "$BACKUP_DIR" -name 'alo-*.dump.zst' -mtime "+$BACKUP_RETENTION_DAYS" -print)
	if [ -z "$found" ]; then
		return 0
	fi
	echo "$found" | while read -r old; do log "pruning $old"; done
	find "$BACKUP_DIR" -name 'alo-*.dump.zst' -mtime "+$BACKUP_RETENTION_DAYS" -exec rm -f {} +
	# Leftover .partial files from a killed dump are not backups; clear them too.
	find "$BACKUP_DIR" -name '*.partial' -mtime +1 -exec rm -f {} + 2>/dev/null || true
}

push_remote() {
	file="$1"
	log "copying to $BACKUP_RCLONE_REMOTE"
	if ! rclone copy "$file" "$BACKUP_RCLONE_REMOTE"; then
		# A failed off-box copy must not lose the local backup or kill the loop.
		log "WARNING: rclone copy failed; the local backup is still good"
		return 0
	fi
	rclone delete --min-age "${BACKUP_RETENTION_DAYS}d" --include 'alo-*.dump.zst' \
		"$BACKUP_RCLONE_REMOTE" || log "WARNING: remote prune failed"
}

cmd_list() {
	ls -1t "$BACKUP_DIR"/alo-*.dump.zst 2>/dev/null || {
		echo "no backups in $BACKUP_DIR" >&2
		return 1
	}
}

cmd_restore() {
	file="${1:-}"
	[ -n "$file" ] || die "restore needs a file name"
	case "$file" in
		/*) path="$file" ;;
		*) path="$BACKUP_DIR/$file" ;;
	esac
	[ -f "$path" ] || die "no such backup: $path"

	zstd -q -t "$path" || die "$path is not a valid zstd file"
	log "restoring $path into $PGDATABASE"

	# --clean --if-exists drops each object before recreating it, so this works
	# against a database that already has a schema. --no-owner and --no-privileges
	# keep it working when the restoring role differs from the one that dumped.
	zstd -dc "$path" | pg_restore --clean --if-exists --no-owner --no-privileges \
		--exit-on-error -d "$PGDATABASE"
	log "restore finished"
}

cmd_loop() {
	log "sidecar up: schedule ${BACKUP_SCHEDULE_UTC} UTC, keeping ${BACKUP_RETENTION_DAYS} days in $BACKUP_DIR"
	if [ -n "$BACKUP_RCLONE_REMOTE" ]; then
		log "off-box target: $BACKUP_RCLONE_REMOTE"
	fi

	# Publish before the first sleep, so a stack that has just come up already has a
	# freshness number instead of NoData for the rest of the day.
	write_metrics - -

	if [ "$BACKUP_ON_START" = "true" ]; then
		attempt_backup || log "WARNING: start-up backup failed; staying up for the next scheduled run"
	fi

	while true; do
		wait_s=$(seconds_until_schedule)
		log "next backup in ${wait_s}s"
		sleep "$wait_s"
		# A failure must not take the sidecar down: tomorrow's run should still
		# happen, and restart loops make the logs useless.
		attempt_backup || log "WARNING: scheduled backup failed; will retry at the next schedule"
	done
}

case "${1:-loop}" in
	loop) cmd_loop ;;
	once) attempt_backup ;;
	list) cmd_list ;;
	restore) shift; cmd_restore "$@" ;;
	*) echo "usage: backup [loop|once|list|restore <file>]" >&2; exit 64 ;;
esac
