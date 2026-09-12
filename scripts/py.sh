#!/usr/bin/env bash
# Run a Python gate inside the project's toolchain container.
#
# The point is that `make lint` on a laptop and the `lint` job in CI execute on
# the same interpreter, whatever python3 the host happens to have. PY_IMAGE is
# the single place that version is decided.
#
#   ./scripts/py.sh 'ruff check .'
#   PY_IMAGE=python:3.12-slim ./scripts/py.sh 'pytest -q'
#
# ./api is mounted read-only and copied to a writable /app inside, so nothing the
# container does (egg-info, __pycache__, tool caches) can land root-owned in the
# working tree. Anything a gate genuinely needs to produce goes to /out, which is
# ./api read-write — see `make lock`, which chowns what it writes back to the
# invoking user.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${PY_IMAGE:-python:3.14-slim}"
[[ $# -gt 0 ]] || { echo "usage: $0 '<command>'" >&2; exit 64; }

# --network host + the docker socket: the suite provisions its own Postgres via
# Testcontainers, which publishes on a host port and is then reached at localhost.
# That only resolves if the test process shares the host network namespace. Ryuk
# (the reaper) is disabled because it cannot see containers outside that namespace;
# the suite stops its own container on exit.
exec docker run --rm --network host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD/api:/src:ro" \
  -v "$PWD/api:/out" \
  -e TESTCONTAINERS_RYUK_DISABLED=true \
  -e ALO_TEST_PG_IMAGE="${ALO_TEST_PG_IMAGE:-alo-reader-postgres:local}" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PIP_ROOT_USER_ACTION=ignore \
  -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  "$IMAGE" sh -ec 'mkdir -p /app && cp -a /src/. /app/ && cd /app && '"$*"
