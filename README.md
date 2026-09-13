# alo-reader

A chronological RSS reader — an inbox for the web: no algorithms, no
recommendations, no engagement mechanics. Fast, calm, keyboard-driven.

See [`DESIGN.md`](DESIGN.md) for design decisions and [`MILESTONES.md`](MILESTONES.md)
for the implementation plan.

## Layout

- `api/` — FastAPI app + worker (one image, two commands). Python 3.14, managed
  with pip. The gates run in a toolchain container (`scripts/py.sh`), so no host
  interpreter has to match.
- `web/` — React 18 + TypeScript + Vite SPA (pnpm).
- `deploy/` — Dockerfiles, Caddy, docker-compose (dev = prod).

## Quick start

```sh
cp .env.example .env      # required: AUTH_MODE has no default and the API won't boot
make up                   # build + start the stack (SPA + API via Caddy on :80)
curl -s localhost/api/v1/healthz   # -> {"status":"ok","version":"0.0.0+dev"}
```

Local development (hot-reload both sides on http://localhost:3000):

```sh
make dev
```

Observability — OpenTelemetry → Grafana LGTM (traces, metrics, logs). Off by
default; these overlays turn it on and add the collector + Grafana stack:

```sh
make otel-up      # prod-topology stack + telemetry; Grafana on http://localhost:3001
make dev-otel     # hot-reload dev stack + telemetry (app :3000, Grafana :3001)
make otel-down    # stop the OTel stack
```

See [`deploy/observability/README.md`](deploy/observability/README.md) for the
topology, what's exported, and the dashboards.

Gates (each runs in the toolchain container; `make venv` exists only to give an
editor something to point at):

```sh
make lint typecheck test-api test-web
```

## Running it in production

The same compose file, plus an `.env` and a domain. There is no separate
production stack.

**1. Fill in `.env`.** The top of `.env.example` lists the variables that ship
with values wrong for production. Every other line in it is a commented-out copy
of the code's default, and a test keeps it that way, so whatever you leave alone
is what you get.

```sh
POSTGRES_PASSWORD=...                 # "alo" is in this public repo
AUTH_MODE=clerk                       # or none; see below
ALO_SITE_ADDRESS=reader.example.com   # a hostname here is what turns TLS on
APP_VERSION=1.0.0                     # reported by /healthz; otherwise 0.0.0+dev
```

**2. Point DNS at the host** and open ports 80 and 443. The ACME challenge uses
both. Then `make up`. Caddy obtains a Let's Encrypt certificate on first request
and renews it from then on: no certificate to install, no renewal cron.

Certificates and the ACME account key live in the `caddy_data` volume. Keep it.
Let's Encrypt caps duplicate certificates at five per week, so an empty store
means re-issuing on every container recreate and eventually no certificate at
all for a few days.

**3. Confirm what is running:** `curl -s https://your-domain/api/v1/healthz`
returns the status and the `APP_VERSION` the image was built with.

### Auth mode

`AUTH_MODE` has no default and the API exits at startup without it. That is
deliberate: `none` must never be what you get by accident.

- `clerk` — hosted auth, for an instance other people sign into. Also set
  `CLERK_ISSUER`, `CLERK_PUBLISHABLE_KEY` and `CLERK_WEBHOOK_SECRET`.
- `none` — no authentication at all; every request is the same single user.
  Only behind a private network, a VPN, or reverse-proxy auth.

### Upgrading

`git pull && make up` rebuilds and restarts. Migrations run as a one-shot
`migrate` service that `api` and `worker` wait on, so the schema is current
before anything serves, and it runs once regardless of replica count.

### Backups

Postgres runs in compose against the `pgdata` volume, so backups and disk are
your problem rather than a managed service's. The `backup` sidecar handles the
first part: a nightly `pg_dump` to the `backups` volume, zstd-compressed, 14 days
kept. Every dump is verified before it counts as one, so a failed dump does not
leave a file that merely looks restorable.

Backups on the same host are not backups if the host is what you lose. Set
`BACKUP_RCLONE_REMOTE` and each dump is also copied off-box and pruned on the
same retention; rclone reads its configuration from `RCLONE_CONFIG_*` variables
in `.env`.

To restore:

```sh
scripts/restore.sh              # newest backup, after you confirm
scripts/restore.sh --latest -y  # no prompt, for a drill
```

It stops the app, restores, and starts it again. It replaces everything in the
database, so it asks you to type the database name first.

**Drill it before you need it.** A backup nobody has restored is a guess. Restore
into a scratch stack and check the row counts, not just that the command exited
zero.

Moving to managed Postgres later is a `DATABASE_URL` change.

## Configuration

Entirely environment-based; nothing is hardcoded. `DATABASE_URL` is the single DB
connection knob. `.env.example` documents every setting the app reads, with its
default. The compose stack reads the repo-root `.env`, and so do non-Docker runs
via python-dotenv; real environment variables win over both.
