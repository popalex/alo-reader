# alo-reader standard commands. Python is managed with a local .venv + pip
# (no uv); the frontend uses pnpm.

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
COMPOSE := docker compose -f deploy/docker-compose.yml
COMPOSE_DEV := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml

.PHONY: venv lint typecheck test-api test-web e2e up dev down migrate

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

down:
	$(COMPOSE) down

## Placeholder until WP-01 adds Alembic migrations.
migrate:
	@echo "migrate: no migrations yet (added in WP-01)"
