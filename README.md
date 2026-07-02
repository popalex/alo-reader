# alo-reader

A chronological RSS reader — an inbox for the web: no algorithms, no
recommendations, no engagement mechanics. Fast, calm, keyboard-driven.

See [`DESIGN.md`](DESIGN.md) for design decisions and [`MILESTONES.md`](MILESTONES.md)
for the implementation plan.

## Layout

- `api/` — FastAPI app + worker (one image, two commands). Python 3.12, managed
  with a local `.venv` + pip.
- `web/` — React 18 + TypeScript + Vite SPA (pnpm).
- `deploy/` — Dockerfiles, Caddy, docker-compose (dev = prod).

## Quick start

```sh
cp .env.example .env      # optional: compose has matching defaults built in
make up                   # build + start the stack (SPA + API via Caddy on :80)
curl -s localhost/api/v1/healthz   # -> {"status":"ok"}
```

Local development (hot-reload both sides on http://localhost):

```sh
make dev
```

Backend tooling (creates `.venv`):

```sh
make venv
make lint typecheck test-api test-web
```

Configuration is entirely environment-based — `DATABASE_URL` is the single DB
connection knob; nothing is hardcoded. See `.env.example`.
