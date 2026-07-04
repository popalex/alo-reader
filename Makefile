# alo-reader standard commands. Python is managed with a local .venv + pip
# (no uv); the frontend uses pnpm.

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
COMPOSE := docker compose -f deploy/docker-compose.yml
COMPOSE_DEV := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml

# Host-run alembic/pytest talk to the dockerized Postgres over its localhost port
# (see `make db`). Postgres itself is never installed on the host.
TEST_DATABASE_URL ?= postgresql+asyncpg://alo:alo@localhost:5432/alo

.PHONY: venv lint typecheck test-api test-web e2e up dev down db db-down migrate

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

## Tests provision their own throwaway Postgres via Testcontainers — no `make db`
## needed, and the real/dev DB is never touched.
test-api:
	$(VENV)/bin/pytest api

test-web:
	pnpm -C web test

## Placeholder until WP-09 wires Playwright.
e2e:
	@echo "e2e: not implemented until WP-09"

## Build and start the full stack; SPA + API served through Caddy on :80.
up:
	$(COMPOSE) up --build -d

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
