#!/bin/sh
# One image, three commands. `api` runs the FastAPI server; `worker` runs the
# poller; `migrate` brings the DB to head and exits (run as a one-shot before
# api/worker start — see the `migrate` service in docker-compose.yml).
set -e

case "${1:-api}" in
  api)
    # --timeout-keep-alive outlasts Caddy's ~2m upstream keep-alive pool so Caddy
    # recycles idle connections first (clean FIN). Otherwise uvicorn times out the
    # idle connection at its 5s default and emits a closing 400 that Caddy logs as
    # an "unsolicited response on idle HTTP channel" (harmless, but noisy).
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 150
    ;;
  worker)
    exec python -m app.worker.main
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    echo "unknown command: $1 (expected 'api', 'worker', or 'migrate')" >&2
    exit 64
    ;;
esac
