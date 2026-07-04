#!/bin/sh
# One image, three commands. `api` runs the FastAPI server; `worker` runs the
# poller; `migrate` brings the DB to head and exits (run as a one-shot before
# api/worker start — see the `migrate` service in docker-compose.yml).
set -e

case "${1:-api}" in
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
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
