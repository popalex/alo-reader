# alo-reader standard commands. Python is managed with a local .venv + pip
# (no uv); the frontend uses pnpm.

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
COMPOSE := docker compose -f deploy/docker-compose.yml
COMPOSE_DEV := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml
COMPOSE_OTEL := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.otel.yml
COMPOSE_DEV_OTEL := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml -f deploy/docker-compose.otel.yml

# Host-run alembic/pytest talk to the dockerized Postgres over its localhost port
# (see `make db`). Postgres itself is never installed on the host.
TEST_DATABASE_URL ?= postgresql+asyncpg://alo:alo@localhost:5432/alo

.PHONY: venv lint typecheck test-api test-web e2e lighthouse size up seed dev down db db-down migrate generate-client bench-search loadtest pg-image

## Create the virtualenv and install the api project (editable, with dev tools).
venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "./api[dev]"

lint:
	$(VENV)/bin/ruff check api
	$(VENV)/bin/ruff format --check api

typecheck:
	$(VENV)/bin/mypy api
	pnpm -C web tsc
	pnpm -C web lint

## Build the project Postgres image (postgres:18 + rum). Cheap when layers cache.
pg-image:
	docker build -f deploy/Dockerfile.postgres -t alo-reader-postgres:local deploy

## Tests provision their own throwaway Postgres via Testcontainers — no `make db`
## needed, and the real/dev DB is never touched. Needs the rum image (migration 0003).
test-api: pg-image
	$(VENV)/bin/pytest api

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
