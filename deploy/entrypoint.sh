#!/bin/sh
# One image, two commands. `api` runs the FastAPI server; `worker` runs the poller.
set -e

case "${1:-api}" in
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec python -m app.worker.main
    ;;
  *)
    echo "unknown command: $1 (expected 'api' or 'worker')" >&2
    exit 64
    ;;
esac
