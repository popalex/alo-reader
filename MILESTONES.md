# alo-reader — Implementation Work Packages

Companion to `DESIGN.md`. That document holds every design decision; this one turns the plan into **17 standalone work packages (WPs)** written to be handed, one at a time, to a coding model for implementation. The implementing model makes **zero design decisions** — everything it needs is pinned here or in `DESIGN.md`.

Milestone map: **M1** = WP-00…WP-08 (headless reader) · **M2** = WP-09…WP-11 (daily driver) · **M3** = WP-12…WP-14 (power user) · **M4** = WP-15…WP-16 (public 1.0).

---

## How to run this plan (operator instructions)

1. **One WP per session, strictly in order.** Give the model: the Shared Preamble below, the single WP brief, and `DESIGN.md`. Nothing else.
2. **One branch per WP** (`wp-03-ingest`). Review the diff yourself before merging; the review checklist is below.
3. **Done = every command in the WP's Acceptance block passes locally.** The model must run them and paste output, not claim success.
4. **Ambiguity rule:** if the model hits anything not specified, it must stop and report the question — never improvise a design decision. You answer, update this file if the answer is durable, and resume.
5. **Never let a WP grow.** Anything discovered mid-WP that isn't in scope becomes a note at the bottom of this file, not extra work in the branch.

### Per-WP review checklist (operator)
- [ ] Diff touches only the files/areas the WP lists.
- [ ] No dependencies added beyond the WP's list (`git diff` on lockfiles).
- [ ] Tests are real: they run against real Postgres, assert behavior (not mocks of the store), and fail if the feature is reverted.
- [ ] `rg -l clerk api/ | grep -v app/auth/` returns nothing (Clerk confined to auth module).
- [ ] Every new repository/store function on user data takes `user_id` as a required arg.
- [ ] Acceptance commands re-run clean on your machine, not just in the model's transcript.

---

## Shared Preamble (paste verbatim into every implementation session)

You are implementing one work package of alo-reader, a chronological RSS reader. `DESIGN.md` contains all design decisions; this brief contains your scope. Follow both exactly.

**Hard rules — violating any of these means the work is rejected:**
1. Implement ONLY what this work package specifies. If something is ambiguous or seems missing, STOP and ask; do not invent a solution.
2. Do not add any dependency not listed in this brief.
3. Do not modify files outside the areas this brief lists, except tiny mechanical edits it explicitly allows (e.g., registering a router in `main.py`).
4. All tests run against real Postgres (the compose service). Never mock the database or the store layer.
5. Nothing outside `api/app/auth/` may import or reference Clerk.
6. Every store/repository function touching user-scoped data takes `user_id: int` as a required argument.
7. Feed content is hostile input: sanitize at ingest with nh3; entry titles are plain text everywhere, never rendered or stored as HTML.
8. Entries are ordered by `id` (insertion order) descending. Never sort by `published_at`.
9. API errors always use the envelope `{"error": {"code": "...", "message": "..."}}`.
10. When done, run every command in the Acceptance block and include the real output.

**Pinned stack** — Python 3.12, managed with a local `.venv` + pip (a `pyproject.toml` project; **not** uv); FastAPI, uvicorn, SQLAlchemy ≥2.0 (async) + asyncpg + greenlet, Alembic, Pydantic v2 + pydantic-settings + python-dotenv, httpx, feedparser, nh3, zstandard, PyJWT[crypto], svix; pytest + pytest-asyncio; ruff (lint+format), mypy. Node 24 + pnpm; React 18, TypeScript strict, Vite; react-router, @tanstack/react-query, @tanstack/react-virtual, @clerk/clerk-react, vite-plugin-pwa; Playwright; size-limit.

**Configuration** — no secret or connection string is hardcoded. Config is read from the environment (via python-dotenv loading a repo-root `.env`; real env vars win). `DATABASE_URL` is the single source of truth for the DB connection; compose supplies it (with sensible local defaults) and `.env.example` documents it.

**Repo layout** (created in WP-00; do not restructure):
```
api/app/{main.py,config.py,errors.py}   api/app/auth/    api/app/store/
api/app/routes/   api/app/ingest/   api/app/worker/   api/app/models.py
api/migrations/   api/tests/
web/src/{main.tsx,app/,api/,features/,keyboard/}   web/tests/
deploy/{docker-compose.yml,docker-compose.dev.yml,Caddyfile,Dockerfile.api,Dockerfile.caddy}
Makefile   MILESTONES.md   DESIGN.md
```
**Standard commands** (defined in WP-00, used everywhere): `make up` `make dev` `make lint` `make typecheck` `make test-api` `make test-web` `make e2e` `make migrate`.

---

## M1 — Headless reader

### WP-00 · Scaffold, compose stack, CI — ✅ DONE (branch `wp-00-scaffold`)
**Depends:** nothing. **Read:** DESIGN.md §1.2, §1.5.
**Status:** complete. Acceptance verified locally: `make lint typecheck test-api test-web` pass; `make up` + `curl localhost/api/v1/healthz` → `{"status":"ok"}` through Caddy (prod :80); `make dev` serves on **http://localhost:3000** and hot-reloads both sides.
**Deliverables:** repo layout above; `api` as a pip/`.venv` project (`pyproject.toml`, installed with `pip install -e "./api[dev]"`) with FastAPI app serving `GET /api/v1/healthz` → `{"status":"ok"}`; `web` as Vite+React+TS scaffold showing a placeholder page; `Dockerfile.api` (one image, `api`/`worker` commands — worker may be a stub loop logging "tick"); `Dockerfile.caddy` (multi-stage: pnpm build → Caddy serving `dist/`, proxying `/api/*` to `api:8000`); base + dev compose files (dev overlay: uvicorn --reload, Vite dev server, disposable Postgres 16; the `backup` service from DESIGN.md §1.5 is deferred to WP-16); Makefile with the standard commands; GitHub Actions running lint, typecheck, test-api, test-web, and image builds; ruff/mypy/tsconfig-strict configured.
**Acceptance:** `make up` then `curl -s localhost/api/v1/healthz` returns ok through Caddy; `make dev` hot-reloads both sides; `make lint typecheck test-api test-web` all pass; CI green on the branch.
**Out of scope:** any schema, any auth, any real worker logic.

### WP-01 · Schema, migrations, store layer
**Depends:** WP-00. **Read:** DESIGN.md §4 (the schema is copied, not reinterpreted).
**Deliverables:** Alembic baseline migration containing the full §4 schema exactly (all tables, indexes, the `strip_html` SQL function, the generated `search_tsv` column); SQLAlchemy models in `api/app/models.py`; store layer in `api/app/store/` — one module per aggregate (`users.py`, `feeds.py`, `subscriptions.py`, `folders.py`, `entries.py`, `entry_states.py`) with typed async functions (create/get/list/update/delete plus: claim-due-feeds stub signature, unread-count query per DESIGN.md §4 semantics, cursor-paginated entry listing by stream); pytest harness: session-scoped engine against compose Postgres, each test inside a rolled-back transaction; factory helpers for test data.
**Acceptance:** `make migrate` applies from an empty DB and is a no-op on re-run; `make test-api` passes with store CRUD + unread-count tests (count asserted against a brute-force recomputation on ≥3 randomized seedings); grep confirms every user-scoped store function requires `user_id`.
**Out of scope:** any HTTP endpoint, auth, worker.

### WP-02 · Auth: `AuthProvider` seam, Clerk + none modes
**Depends:** WP-01. **Read:** DESIGN.md §0.1, §1.2 auth row.
**Deliverables:** `api/app/auth/` containing: `provider.py` (`AuthProvider` protocol: `authenticate(request) -> AuthedUser | None`), `clerk.py` (JWKS fetch + 1h in-process cache, JWT verification of iss/aud/exp, maps `clerk_user_id` → local user row), `none.py` (auto-provisions and returns the single local user), `pat.py` (personal access tokens: `alo_pat_<random>`, sha256 stored, constant-time compare); `AUTH_MODE` config — **server exits with a clear error if unset**; FastAPI dependency `current_user`; routes: `GET /api/v1/config` (public: `{"auth_mode": ...}` + Clerk publishable key when mode=clerk), `GET /me`, `GET/POST/DELETE /tokens`; `POST /api/v1/webhooks/clerk` with svix signature verification handling user.created/updated/deleted (delete cascades locally); naive in-process per-user token-bucket rate-limit middleware (defaults from config).
**New deps:** none beyond preamble pins.
**Acceptance:** `make test-api` covering: valid/expired/wrong-aud/garbage JWT (use test RSA keys, mock JWKS via httpx MockTransport), PAT happy+revoked+deleted-user paths, webhook with valid/invalid svix signature, `AUTH_MODE=none` auto-user, server refuses to boot without `AUTH_MODE`; entire suite green under both `AUTH_MODE=clerk` and `AUTH_MODE=none`; `rg -l clerk api/app | grep -v auth` → empty.
**Out of scope:** frontend, any subscription/entry endpoint.

### WP-03 · Ingest pipeline (pure library) + fixture corpus
**Depends:** WP-01. **Read:** DESIGN.md §1.3 pipeline, §2 risks 1–2.
**Deliverables:** `api/app/ingest/`: `parse.py` (feedparser wrapper → normalized `ParsedFeed`/`ParsedEntry` dataclasses; GUID fallback chain guid→link→sha256(title+published); date normalization to UTC, rejecting dates >48h in the future), `sanitize.py` (nh3 policy per DESIGN.md — allowlist tags/attrs, force `rel="noopener noreferrer" target="_blank"` on links, scheme check http/https only, strip 1×1 images; `title_to_text()`; `summarize()` first ~300 chars of stripped text), `raw.py` (zstd compress/decompress). All pure functions, no I/O, no DB. Fixture corpus `api/tests/fixtures/feeds/` with ≥15 real-world files covering: RSS 0.91/1.0/2.0, Atom, wrong declared encoding, missing GUIDs, HTML-in-titles, CDATA, relative URLs, XSS payloads (script/onerror/javascript:/data:/SVG), enormous entry, empty feed. Golden-file outputs checked in.
**Acceptance:** `make test-api` green: golden tests over all fixtures; adversarial sanitizer tests assert exact output (no script/handler/scheme survives); property test: GUID chain is deterministic and non-empty for every fixture entry; zero network access in tests (assert via socket-blocking fixture).
**Out of scope:** fetching, DB writes, scheduling.

### WP-04 · Fetcher + SSRF guard
**Depends:** WP-03. **Read:** DESIGN.md §1.3 (polite HTTP, SSRF), §2 risk 3.
**Deliverables:** `api/app/worker/fetch.py`: async `fetch_feed(feed) -> FetchResult` using httpx — conditional GET (send stored ETag/Last-Modified; classify 304), gzip, honest User-Agent from config (`alo-reader/+<url>`), total timeout 30s, response cap 5 MB (abort mid-stream), redirect handling capped at 5 hops **re-validating SSRF on every hop**, permanent-redirect surfaced so the caller can update `feed_url`, 429/Retry-After surfaced; `api/app/worker/ssrf.py`: resolve DNS first, reject private/loopback/link-local/metadata/IPv6-mapped ranges, allow only http/https, connect to the resolved IP (no re-resolution race); `FetchResult` covers: not_modified / new_body / http_error / network_error / blocked.
**Acceptance:** `make test-api` green with httpx MockTransport + local test server scenarios: 200-new, 304, 429+Retry-After, 301-permanent, timeout, oversize abort, each SSRF class incl. redirect-to-private-IP and DNS-rebind (mock resolver); no event-loop blocking >100 ms in the oversize test (watchdog fixture).
**Out of scope:** scheduling, DB writes, parsing (already exists).

### WP-05 · Worker: claim loop, scheduler, persistence
**Depends:** WP-02, WP-04. **Read:** DESIGN.md §1.3 claim loop, §4 feeds table.
**Deliverables:** `api/app/worker/main.py` (the `worker` command): loop every 5s claiming ≤50 due feeds via the exact `FOR UPDATE SKIP LOCKED` + `claimed_until` lease pattern in DESIGN.md §1.3; per-host semaphore (concurrency 1); pipeline per feed: fetch → (on new body) parse in `asyncio.to_thread` → sanitize → dedup on `(feed_id, guid_hash)` → batch-insert new entries in one transaction → update etag/last_modified/title/site_url; adaptive interval (new items → interval/2 floor 900s; nothing → interval×1.5 ceiling 86400s); on error: `error_count+1`, exponential backoff capped 24h, `last_error` stored; permanent redirect updates `feed_url` (unique-collision → mark error, never merge silently); graceful shutdown on SIGTERM (finish in-flight, release claims); stdout structured logs; counters kept for a later /metrics.
**Acceptance:** `make test-api` green: end-to-end worker test against a local test HTTP server (items appear in DB exactly once across two poll cycles); **two concurrent worker instances process a 50-feed backlog with zero duplicate entries** (the claim test); lease expiry recovers a crashed claim; backoff/interval math unit-tested; goroutine-equivalent hygiene: no leaked tasks (pytest-asyncio strict mode, all tasks awaited on shutdown).
**Out of scope:** any API endpoint, OPML, icons (icon fetching is WP-08).

### WP-06 · Core API 1: folders + subscriptions
**Depends:** WP-02, WP-05. **Read:** DESIGN.md §5 (subscriptions/folders), §1.4 quotas.
**Deliverables:** `api/app/routes/{folders,subscriptions}.py` implementing §5 exactly: folders CRUD; `GET /subscriptions` (joined feed metadata incl. `last_error`, `last_fetched_at`); `POST /subscriptions` — normalizes URL, reuses existing `feeds` row or creates one with `next_check_at=now` (immediate poll pickup), sets `since_entry_id` = current max entry id for that feed, 409 on duplicate, 422 on quota (`users.quota_subs`); PATCH (title_override, folder move); DELETE; `POST /subscriptions/{id}/refresh` → sets `next_check_at=now`, rate-limited to 1/feed/5min → 202/429. Error envelope everywhere; Pydantic response models (OpenAPI accurate).
**Acceptance:** `make test-api` green: per-endpoint tests incl. the quota, duplicate, and refresh-rate paths, plus **cross-tenant probes**: user B gets 404 (not 403) for every one of user A's object ids, on every endpoint in this WP.
**Out of scope:** entries/streams, OPML, discovery.

### WP-07 · Core API 2: streams, entries, state, counts
**Depends:** WP-06. **Read:** DESIGN.md §5 (streams/state/counts), §4 semantics — implement the unread/bounded-mark-read/LWW rules exactly.
**Deliverables:** `api/app/routes/{streams,entries}.py`: `GET /streams/{stream}/entries` (stream parser for `all|feed/{id}|folder/{id}|starred`; status filter default unread honoring `since_entry_id`; exclusive `cursor` on id desc; `limit` ≤200; `q=` ignored for now — 422 "not yet available"); `GET /entries/{id}` with `content_html`; `POST /entries/state` (≤1000 ids, read/starred flags, optional `changed_at` for LWW with tie-bias to read=true, upsert on `entry_states`); `POST /streams/{stream}/mark-read` bounded by `max_entry_id`; `GET /counts` per DESIGN.md §4 (exact, index-backed).
**Acceptance:** `make test-api` green: pagination is gap-free and duplicate-free while entries are inserted concurrently mid-pagination (explicit test); `since_entry_id` hides pre-subscription entries; mark-read bound leaves newer items unread; LWW replay is idempotent (same batch twice = same state); counts match brute force on randomized data; cross-tenant probes for entries and state (user B cannot read or flip user A's state — verify by direct DB assertion, not just status code). **After this WP the product is usable via curl with a PAT — demonstrate with a script `scripts/smoke.sh`** (subscribe to a live-test fixture server, poll, list, read, count) run inside compose.
**Out of scope:** search execution, OPML, frontend.

### WP-08 · OPML import/export, discovery, icons
**Depends:** WP-07. **Read:** DESIGN.md §5 (opml/discover).
**Deliverables:** `GET /opml` export (nested folder outlines); `POST /opml` multipart import — parses (stdlib ElementTree; reject >1 MB), creates folders/subscriptions respecting quota and dedup, returns per-feed `{imported, skipped, failed:[{url, reason}]}` synchronously (imports are quota-capped, so bounded); `POST /discover` `{url}` → SSRF-guarded fetch of the page, parse `<link rel="alternate" type=...rss/atom...>` plus fallbacks `/feed`, `/rss`, `/atom.xml`, `/index.xml`, return candidates with titles; worker addition: fetch favicon (link rel=icon → /favicon.ico fallback) into `icons` on first successful feed poll, SSRF-guarded, 100 KB cap; `GET /icons/{id}` serving with long cache headers.
**Acceptance:** `make test-api` green: OPML round-trip semantic equality (export→import into fresh user→same folders/subs); real Feedly + Miniflux export fixtures import with correct per-feed report; discovery finds feeds on ≥3 fixture HTML pages; icon path tested via test server. **Milestone M1 exit:** operator runs `scripts/smoke.sh` + imports their real OPML on a staging compose and reads via curl.
**Out of scope:** everything frontend.

---

## M2 — Daily driver

### WP-09 · Frontend foundation: config boot, auth, layout, data layer
**Depends:** WP-07. **Read:** DESIGN.md §1.2 frontend row, §0.1 (config boot).
**Deliverables:** `web/src/`: boot sequence — fetch `/api/v1/config`; mode `clerk` → lazy-load `@clerk/clerk-react`, ClerkProvider, sign-in/up routes, token injected into every request; mode `none` → straight to app, no Clerk code fetched (verify via dynamic import + separate chunk); typed API client generated from the FastAPI OpenAPI schema (`openapi-typescript` in `make generate-client`; **CI fails if generated output is stale**); TanStack Query setup (staleTime 30s, retry 1, error toasts); react-router routes `/`, `/feed/:id`, `/folder/:id`, `/starred`; responsive three-pane layout per DESIGN.md (CSS grid; ≤768px collapses to single-pane stack with back navigation); sidebar: folders + subscriptions + unread badges from `/counts`, error dot for feeds with `last_error`; placeholder center/right panes; size-limit config: main chunk ≤180 KB gz.
**New deps:** `openapi-typescript` (dev).
**Acceptance:** `make e2e` (Playwright, `AUTH_MODE=none` compose profile): boots to app with real sidebar data; `make test-web` component tests for boot branching (clerk vs none, mocked config); size-limit passes; Lighthouse perf ≥90 on the built app (`make lighthouse` script).
**Out of scope:** entry list, reading pane, any mutation.

### WP-10 · Entry list + reading pane
**Depends:** WP-09. **Read:** DESIGN.md §0.3 ordering.
**Deliverables:** virtualized entry list (@tanstack/react-virtual) with infinite cursor pagination via the streams endpoint; row = feed favicon, feed name, title, summary line, relative time (from `created_at`, tooltip shows `published_at`); list/expanded view toggle (persisted in localStorage); reading pane: sanitized `content_html` rendered inside a container with CSS containment, image `loading=lazy` and `max-width:100%`, external links open new tab; unread rows visually distinct; empty/error/loading states for every query; entry selection state lives in a single `useReducer` store (the keyboard WP will drive it).
**Acceptance:** `make e2e`: seed script (`scripts/seed_dev.py`, part of this WP: 20 feeds / 5k entries) → scroll through 5k entries smoothly (Playwright trace: no frame >50 ms during scripted scroll), open entry, content renders, XSS fixture entry renders inert (assert no dialog, no script node); mobile viewport E2E: list→entry→back works.
**Out of scope:** marking read, refresh, keyboard.

### WP-11 · Read-state interactions
**Depends:** WP-10. **Read:** DESIGN.md §5 state contract.
**Deliverables:** mark-read-on-open + mark-read-on-scroll-past (row fully above viewport for >600 ms — IntersectionObserver, batched flush every 2s or 50 ids via `POST /entries/state`); optimistic updates with rollback on failure (TanStack mutation + counts cache adjustment); star/unstar; mark-all-read button per stream sending observed `max_entry_id`, with optimistic count zeroing; refresh-on-focus (visibilitychange → invalidate entries+counts, respecting 30s staleTime) + manual refresh button; per-feed error banner in list header when `last_error` set.
**Acceptance:** `make e2e`: open → row turns read, sidebar count drops without refetch flash; scroll-past marks batch (network tab assertion: batched, not per-row); kill API container mid-mark → UI rolls back and toasts; mark-all-read leaves a concurrently-inserted newer entry unread (seed trick); reload → all state persisted. **M2 exit:** operator dogfoods daily.
**Out of scope:** keyboard, offline queue, search.

---

## M3 — Power user

### WP-12 · Keyboard navigation + accessibility
**Depends:** WP-11. **Read:** DESIGN.md §0.3. The keymap in this brief is exhaustive — implement exactly, add nothing.
**Deliverables:** `web/src/keyboard/`: single global handler (ignores events in inputs; supports `g`-prefix chords with 1s timeout): `j/k` next/prev + scroll-into-view, `o`/Enter open/close, `v` original in new tab, `m` toggle read, `s` star, `A` mark-all-read (with confirm dialog), `r` refresh, `g a` all, `g s` starred, `/` focus search input (input exists, disabled until WP-13), `?` help overlay listing every binding (generated from the binding table, not hand-written); focus management: selection visible ring, focus returns predictably after pane close; ARIA: list/listitem/article roles, aria-live for count changes; axe-core in E2E.
**Acceptance:** `make e2e`: a full session driven **only** by keyboard (subscribe via UI once with mouse allowed, then: navigate, open, star, mark read, mark-all, switch streams, open help — zero mouse events); axe-core no violations; `?` overlay matches the binding table exactly (single source of truth test).
**Out of scope:** search execution.

### WP-13 · Search (English FTS) + starred polish
**Depends:** WP-07, WP-12. **Read:** DESIGN.md §4.1 (the full FTS plan — implement it exactly), §5 (`q=`).
**Deliverables:** API: implement `q=` on the streams endpoint via `websearch_to_tsquery('english', q)` against `search_tsv`, still id-desc ordered (never `ts_rank`), still stream-scoped; when `q` is present cap `limit` at 50 and add a `ts_headline('english', …)` snippet field to each returned row (headline computed only on the returned page, never during matching); frontend: search input (bound to `/`), scope = current stream, results reuse the entry list, highlighted snippets rendered safely (headline output HTML-escaped except the `<b>` markers), clear-search affordance (`Esc`); starred stream verified end-to-end.
**Acceptance:** `make test-api`: stemming works ("running" finds an entry containing only "run", and vice versa); quoted phrases, `OR`, and `-exclusion` behave per websearch syntax; garbage/operator-soup queries return 200 with results-or-empty, never 500; search respects stream scope + tenant isolation + strict id-desc chronology; `limit` capping verified; seeded-scale benchmark (`scripts/bench_search.py`, 5M entries in CI-nightly profile, 100k in PR profile) p95 <100 ms; `make e2e`: `/` → type → highlighted results → `Esc` clears.
**Out of scope:** language detection / multilingual configs, `pg_trgm` fuzzy matching, relevance sort (all post-1.0, DESIGN.md §4.1.7).

### WP-14 · PWA + offline queue
**Depends:** WP-11. **Read:** DESIGN.md §0.3 offline scope, §5 sync contract.
**Deliverables:** vite-plugin-pwa: manifest (name/icons/theme, maskable icon), SW with app-shell precache + runtime NetworkFirst cache for `/streams/*` and `/entries/*` GETs (max 500 entries, 7-day expiry); offline mutation queue in IndexedDB: read/star actions enqueue when offline with client `changed_at`, replay on `online` event through the normal endpoint (idempotent by contract), badge in UI showing queued count; offline UI state (banner, disabled actions that can't queue); iOS standalone quirks pass (viewport-fit, status bar, no 300ms artifacts).
**Acceptance:** `make e2e` with Playwright offline emulation: load entries → go offline → read cached entries, mark 5 read (queued badge shows 5) → online → replays exactly once (server-side count assertion), badge clears; hard-reload offline still boots the shell; Lighthouse PWA installability checks pass. **M3 exit:** mouse unplugged + wifi off session loses nothing.
**Out of scope:** full offline archive, background sync API.

---

## M4 — Public 1.0

### WP-15 · Multi-tenant hardening + abuse suite
**Depends:** WP-08, WP-13. **Read:** DESIGN.md §1.4, §2 risks 3–7.
**Deliverables:** quota audit closing every gap (OPML size, discovery rate, refresh-now, API token count, per-user request rates — each with a test that bypass attempts fail); orphan-feed GC job (zero subscribers >7 days → delete cascade) and retention purge per DESIGN.md §0.3, both as worker-embedded periodic tasks with jitter; entry content cap (500 KB post-sanitize, truncate + flag); `/metrics` (Prometheus: worker lag = oldest due unclaimed feed age, fetch outcomes by class, per-host 403/429 counters, DB/table sizes) gated to internal network in Caddy; security headers + CSP audit (test asserting exact header set); `pip-audit` + `pnpm audit` in CI; load test `scripts/loadtest.py` (1k users, 20k feeds, 5M entries seed): assert API p95 <100 ms on streams/counts, worker drains a 1k-feed backlog, zero cross-tenant rows in a randomized probe sweep.
**Acceptance:** every new limit has a failing-then-passing test; load-test numbers printed and within budget on the CI-nightly profile; abuse suite green (SSRF probe set re-run through the full API path, deleted-user PAT reuse, quota bypass attempts).
**Out of scope:** billing, admin UI.

### WP-16 · Production deploy, ops, docs, 1.0
**Depends:** WP-15, WP-14. **Read:** DESIGN.md §1.5.
**Deliverables:** production env file template with every variable documented; backup sidecar (nightly `pg_dump | zstd` → mounted volume + optional S3 target via rclone, retention 14 days) and `scripts/restore.sh`; structured JSON logging everywhere + Sentry hooks (DSN optional); alert floor documented (worker lag, 5xx rate, disk); terms + privacy static pages served by Caddy; account-deletion E2E (Clerk webhook → local cascade verified); docs: `README.md` (what/why/screenshot), `docs/INSTALL.md` (the compose guide — doubles as self-host guide, with the `AUTH_MODE` section and the bold private-network warning for `none`), `docs/KEYBOARD.md` generated from the binding table, `CHANGELOG.md`; version stamped into image + `/healthz`; migration-snapshot test harness (CI applies the Alembic chain to a schema dump captured at each release; capture the v1.0.0 snapshot now); tag `v1.0.0`.
**Acceptance:** fresh scratch VM: follow INSTALL.md only → public instance behind TLS, sign-up→read works; `scripts/restore.sh` drill executed on the scratch VM from a real backup; docs reviewed by someone who hasn't seen the repo (operator finds a victim). **M4 exit = launch.**
**Out of scope:** Fever/GReader adapter, full-content extraction, image proxy, billing (post-1.0 backlog in DESIGN.md).

---

## Discovered-work parking lot
(Items found mid-WP that were out of scope. Operator triages into future WPs.)

- _empty_
