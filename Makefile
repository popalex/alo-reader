# alo-reader standard commands. The Python gates run inside a container pinned to
# the interpreter the images ship, so they do not depend on whatever python3 the
# host happens to have; the frontend uses pnpm on the host.

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Every Python gate runs through scripts/py.sh, a container pinned to the same
# interpreter the images ship — so `make lint` on a laptop and the `lint` job in CI
# execute on the same Python. PY_IMAGE (read by the script) is the single place
# that version is decided; export it to try another interpreter and change nothing
# else. Nothing the container does can land root-owned in the tree: ./api goes in
# read-only and is copied to a writable /app inside.
PY_RUN := ./scripts/py.sh
# The pinned set, then the project itself without letting pip re-resolve it.
PY_INSTALL := pip install --quiet -r requirements-dev.txt
PY_PROJECT := pip install --quiet -e . --no-deps
COMPOSE := docker compose -f deploy/docker-compose.yml
COMPOSE_DEV := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml
COMPOSE_OTEL := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.otel.yml
COMPOSE_DEV_OTEL := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml -f deploy/docker-compose.otel.yml

# Host-run alembic/pytest talk to the dockerized Postgres over its localhost port
# (see `make db`). Postgres itself is never installed on the host.
TEST_DATABASE_URL ?= postgresql+asyncpg://alo:alo@localhost:5432/alo

.PHONY: venv lock lock-upgrade lint typecheck test-api test-web e2e lighthouse size up seed dev down db db-down migrate generate-client bench-search loadtest pg-image

## Optional: a local virtualenv, for editor tooling (autocomplete, go-to-def).
## The gates below do not use it — they run in the toolchain container — so this
## needs only a host python3 the project still supports, and skipping it breaks
## nothing. --no-deps on the editable install: the pins in requirements-dev.txt
## are the resolution, and pip must not re-resolve them from pyproject's ranges.
venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r api/requirements-dev.txt
	$(PIP) install -e ./api --no-deps

## Recompile the Python lockfiles from api/pyproject.toml. Run after changing a
## dependency range, and commit the result — CI installs from these, not from the
## ranges, so an upstream release can never land in CI unannounced. Resolved inside
## the toolchain container: environment markers are evaluated against whichever
## interpreter does the resolving, so the host's python must not be the one deciding.
##
## This does NOT pick up new releases. pip-compile keeps any pin that still satisfies
## the ranges, so re-running it after a dependency publishes a fix is a no-op — use
## `make lock-upgrade` for that. Nothing else updates these files: Dependabot does not
## watch /api (see .github/dependabot.yml for why), so the upgrade target is the only
## way a newer Python dependency enters the tree.
lock:
	$(PY_RUN) 'pip install --quiet pip-tools \
	  && pip-compile --quiet --strip-extras $(PIP_COMPILE_ARGS) -o requirements.txt pyproject.toml \
	  && pip-compile --quiet --strip-extras $(PIP_COMPILE_ARGS) --extra dev -o requirements-dev.txt pyproject.toml \
	  && pip-compile --quiet --strip-extras $(PIP_COMPILE_ARGS) --extra otel -o requirements-otel.txt pyproject.toml \
	  && cp requirements.txt requirements-dev.txt requirements-otel.txt /out/ \
	  && chown "$$HOST_UID:$$HOST_GID" /out/requirements*.txt'

## Re-resolve every pin to the newest release its range allows, then review the diff.
## The three files are regenerated together in one pass so they cannot disagree —
## a shared dependency resolved separately per file is how a lockfile set goes
## unsatisfiable (Dependabot's per-file edits did exactly that in PR #38).
lock-upgrade:
	$(MAKE) lock PIP_COMPILE_ARGS=--upgrade

lint:
	$(PY_RUN) '$(PY_INSTALL) && ruff check . && ruff format --check .' 

## mypy needs the otel extra or it cannot resolve the OpenTelemetry imports in
## app/telemetry.py (imported lazily at runtime, but typecheck follows them).
## The web half stays on the host with pnpm.
typecheck:
	$(PY_RUN) '$(PY_INSTALL) -r requirements-otel.txt && $(PY_PROJECT) && mypy .'
	pnpm -C web tsc
	pnpm -C web lint

## Build the project Postgres image (postgres:18 + rum). Cheap when layers cache.
pg-image:
	docker build -f deploy/Dockerfile.postgres -t alo-reader-postgres:local deploy

## Tests provision their own throwaway Postgres via Testcontainers — no `make db`
## needed, and the real/dev DB is never touched. Needs the rum image (migration 0003).
test-api: pg-image
	$(PY_RUN) '$(PY_INSTALL) && $(PY_PROJECT) && pytest -q' 

test-web:
	pnpm -C web test

## End-to-end (Playwright): bring up the stack (AUTH_MODE=none) with a fixture
## feed, seed a folder + subscription, and drive the real SPA through Caddy.
## KEEP_UP=1 leaves the stack running afterwards.
e2e:
	./scripts/e2e.sh

## Lighthouse performance budget (>=90) against the built SPA served by Caddy.
lighthouse:
	./scripts/lighthouse.sh

## Search latency benchmark (WP-13, p95 < 100ms). Needs `make db` + `make migrate`.
## BENCH_PROFILE=pr (100k, default) | nightly (5M); BENCH_KEEP=1 keeps the corpus.
bench-search:
	DATABASE_URL=$(TEST_DATABASE_URL) $(PY) scripts/bench_search.py

## Multi-tenant load test (WP-15): API p95, worker backlog drain, cross-tenant probe.
## Needs `make db` + `make migrate`. LOAD_PROFILE=smoke (default) | ci-nightly (5M);
## LOAD_KEEP=1 keeps the synthetic tenants.
loadtest:
	DATABASE_URL=$(TEST_DATABASE_URL) $(PY) scripts/loadtest.py

## Build the SPA and check the initial bundle stays within the size budget.
size:
	cd web && pnpm build && pnpm size

## Build and start the full stack; SPA + API served through Caddy on :80.
## Needs AUTH_MODE set (prod compose has no default, by design): put it in a
## repo-root .env (see .env.example) or prefix, e.g. `AUTH_MODE=none make up`.
## For local hacking, `make dev` defaults AUTH_MODE=none and adds hot-reload.
up:
	$(COMPOSE) up --build -d

## Full stack + OpenTelemetry → Grafana LGTM (collector + otel-lgtm). Grafana on :3001.
otel-up:
	$(COMPOSE_OTEL) up --build -d

otel-down:
	$(COMPOSE_OTEL) down

## Hot-reload dev stack + OpenTelemetry (app on :3000, Grafana on :3001).
dev-otel:
	$(COMPOSE_DEV_OTEL) up --build

## Seed a large, realistic dataset (20 feeds in folders, ~5k mixed read/starred
## entries) into the running stack — no host Python needed. Idempotent: it resets
## this user's seeded feeds/folders/state first. Needs `make up` (or `make dev`)
## running. Scale knob: SEED_ENTRIES_PER_FEED (default 250), e.g.
##   make seed SEED_ENTRIES_PER_FEED=50
seed:
	$(COMPOSE) exec -T $(if $(SEED_ENTRIES_PER_FEED),-e SEED_ENTRIES_PER_FEED=$(SEED_ENTRIES_PER_FEED)) api python - < scripts/seed_dev.py

## Hot-reload dev stack (uvicorn --reload + Vite HMR) on http://localhost.
dev:
	$(COMPOSE_DEV) up --build

## Tear down the whole stack (containers + network) whether it was started by
## `make up` or `make dev` — same project, so the dev file set is a safe superset.
## Named volumes (pgdata) are kept; use `make db-down` semantics or add -v to wipe.
down:
	$(COMPOSE_DEV) down

## Start ONLY the dockerized Postgres (exposed on localhost:5432) for migrate/tests.
db:
	$(COMPOSE_DEV) up -d postgres

db-down:
	$(COMPOSE_DEV) down

## Apply Alembic migrations against the dockerized Postgres.
migrate:
	cd api && DATABASE_URL=$(TEST_DATABASE_URL) ../$(VENV)/bin/alembic upgrade head

## Regenerate the typed API client from the FastAPI OpenAPI schema. The schema
## is exported in-process (no server needed); sorted keys keep it deterministic
## so CI can diff-check for drift. web/src/api/schema.d.ts is committed; the
## intermediate openapi.json is gitignored.
generate-client:
	cd api && AUTH_MODE=none ../$(VENV)/bin/python -c "import json,sys; from app.main import app; json.dump(app.openapi(), sys.stdout, sort_keys=True)" > $(CURDIR)/web/openapi.json
	cd web && pnpm exec openapi-typescript openapi.json -o src/api/schema.d.ts
