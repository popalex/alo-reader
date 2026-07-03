# alo-reader — Design Document (v2)

A chronological RSS reader, hosted as a public multi-tenant web app. An inbox for the web: no algorithms, no recommendations, no engagement mechanics. Fast, calm, keyboard-driven.

> **v2 changes:** Python/FastAPI instead of Go; Postgres instead of SQLite; Clerk for auth; **public multi-tenant hosting is now the primary target** (self-hosting demoted to a secondary, documented mode). Frontend is a separate React SPA — Flask was considered and rejected (§0.2).
>
> **The development plan lives in `MILESTONES.md`** (work packages + milestones). This document holds the design decisions those packages implement.

---

## 0. Requirements deltas, assumptions, and challenged choices

### 0.1 The big one: "public for any user" contradicts "self-hosted first"

The original brief said self-hosted first; the new direction is a public instance for anyone. These pull in opposite directions:

- **Clerk** is a proprietary SaaS — excellent for a public app, unacceptable as a hard dependency for self-hosters.
- Public hosting makes **abuse, per-user limits, SSRF, and cost control** first-class requirements instead of non-issues.
- Multi-tenancy makes **global feed dedup** an economic necessity, not a nicety (1,000 users following the same blog = one poll, not 1,000).

**Decision: design public-first, keep self-hosting alive with one seam and one flag.** Auth is isolated behind a small `AuthProvider` interface and selected by `AUTH_MODE`:

- `AUTH_MODE=clerk` (default, the public instance): Clerk JWT verification. A self-hoster *can* run this too — the compose stack runs anywhere; they just supply their own Clerk keys via env. The cost is a third-party SaaS dependency for login (internet required, identities live with Clerk), which some self-hosters will reject on principle.
- `AUTH_MODE=none` (single-user self-host): auth is disabled; every request maps to one auto-created local user, and the SPA skips Clerk entirely (it reads the mode from `GET /api/v1/config` at boot). **Never the default, refuses to start unless explicitly set, and the docs say in bold: only behind a private network, VPN/Tailscale, or reverse-proxy auth (Caddy basic-auth is two lines).** This is the standard pattern in good self-hosted software, and it's far cheaper than building a parallel password/session subsystem.

Everything else (FastAPI + Postgres + worker) is deployment-agnostic already. Nothing outside the auth module may import Clerk directly.

### 0.2 Frontend: separate SPA vs. Flask full app — resolved

**Separate React SPA + FastAPI API. No Flask.** Reasons, in order of weight:

1. **Two backend frameworks is an anti-decision.** Flask alongside FastAPI means two routing systems, two auth integrations, two deployment stories. If server-rendered were the goal, it would be FastAPI + Jinja — Flask adds nothing but confusion.
2. **Clerk decides this anyway.** Clerk's first-class SDK is React (`@clerk/clerk-react`): prebuilt sign-in/up components, session management, token refresh. Wiring Clerk into server-rendered Jinja templates is the worst-supported path through their product.
3. **The product goals require an SPA regardless.** Instant `j/k` navigation, optimistic read-state updates, virtualized lists, offline PWA queue — a server-rendered app can't deliver Reader-grade snappiness without accreting its own ad-hoc JS layer, i.e., becoming a worse SPA.
4. **Independent deploys:** static frontend on a CDN (free, globally fast), API scaled separately.

*(Next.js was also considered and rejected: its strengths — SSR, SEO, server-route middleware — don't apply to an app that lives entirely behind a login, and it adds a Node runtime plus the standing temptation to grow a second backend in Next API routes. Vite + React + TypeScript is the toolchain.)*

### 0.3 Standing assumptions (carried or updated from v1)

| Topic | Decision |
|---|---|
| **Scale envelope** | Design for ~5k users, ~50k unique feeds, ~50M entries. Postgres clears this on a small managed instance; the architecture (stateless API + lock-free work claiming) scales horizontally past it. |
| **Ordering** | **Time of first receipt** (insertion order), not publish date — feeds lie about dates and would reshuffle the inbox. Publish date is displayed, never sorted on. Position of an item never changes; cursors are stable. (Unchanged from v1; still the most important product decision.) |
| **Retention** | Public instance: read+unstarred entries purged after a configurable horizon (default 90 days) *only when every subscriber has read them*; starred kept forever. Unread is never purged. |
| **Offline/PWA** | App shell + already-loaded entries offline; read/star mutations queued and replayed (LWW, biased to "read"). No full offline archive in v1. |
| **Live updates** | None, by design. Refresh on focus + manual refresh. Calm > real-time. |
| **Unread counts** | Computed from indexes, never counter columns. Exact by construction. |
| **Search** | v1, via Postgres full-text search (tsvector + GIN), **English-first** (`english` config: stemming + stopwords). Non-English content is still indexed, just without stemming quality. Multilingual configs and fuzzy matching are post-1.0. Full design: §4.1. |
| **Full-content extraction, Fever/GReader API compat** | Post-1.0, but designed-for (stable entry IDs, stream abstraction, bounded mark-read). |
| **Billing** | Out of v1. Free public beta with hard per-user quotas. Quota enforcement built in v1 so a paid tier is a config change, not a rewrite. |

---

## 1. Architecture

### 1.1 Shape: one codebase, two processes, three deployables

```
                    ┌────────────────────────┐
   users ──HTTPS──► │  Caddy (docker)        │  auto-TLS; serves the built
                    │  static React SPA      │  SPA; proxies /api → api
                    │  (Clerk React SDK)     │
                    └───────────┬────────────┘
                                │ JSON + Bearer (Clerk JWT)
                                ▼
                    ┌────────────────────────┐     ┌──────────────────┐
                    │  API (FastAPI/uvicorn) │     │  Clerk (SaaS)    │
                    │  - verifies Clerk JWT  │◄───►│  JWKS, webhooks  │
                    │    via cached JWKS     │     └──────────────────┘
                    │  - stateless, scale N  │
                    └───────────┬────────────┘
                                │ SQLAlchemy async / asyncpg
                                ▼
                    ┌────────────────────────┐
                    │  Postgres (docker)     │  ← the only stateful thing
                    └───────────▲────────────┘
                                │ FOR UPDATE SKIP LOCKED
                    ┌───────────┴────────────┐
                    │  Worker (poller)       │  same codebase, separate
                    │  asyncio + httpx       │  process; scale 1..N with
                    │  fetch→parse→sanitize  │  no extra infrastructure
                    └────────────────────────┘
```

**No Redis, no Celery, no message queue.** The poller's work queue *is* Postgres: workers claim due feeds with `SELECT … FOR UPDATE SKIP LOCKED`, which gives horizontally scalable, crash-safe job claiming for free. Every piece of infra you don't run is a piece that can't page you. Redis earns its place later only if/when hot-path caching demands it — it gets no architectural role now.

### 1.2 Stack

| Layer | Choice | Notes |
|---|---|---|
| API | **FastAPI** + uvicorn, Pydantic v2 for all request/response schemas | OpenAPI docs for free; async end-to-end. |
| ORM/migrations | **SQLAlchemy 2.0 (async) + asyncpg + Alembic** | Core-style queries on hot paths; no lazy-loading in request handlers (async makes implicit IO a bug, not a surprise). |
| Feed parsing | **feedparser** | 20 years of malformed-feed battle scars; it's sync and CPU-ish, so parsing runs in a thread-pool executor inside the worker. |
| Sanitization | **nh3** (Rust `ammonia` bindings) | Bleach is deprecated/unmaintained — do not use it. nh3 is fast and allowlist-based. |
| HTTP fetching | **httpx** (async) | Conditional GET, redirect audit, per-host politeness. |
| Auth | **Clerk** behind an `AuthProvider` seam, selected by `AUTH_MODE=clerk\|none` (§0.1): SPA uses `@clerk/clerk-react`; API verifies session JWTs against Clerk's JWKS (cached in-process, ~zero latency). Clerk **webhooks** (`user.created` / `user.deleted`, svix-signature-verified) sync a local `users` row. `AUTH_MODE=none` = single-user self-host mode, no Clerk anywhere. | Local `users` table is mandatory: entries/subscriptions must FK to something you own, and account deletion must cascade locally. |
| Frontend | **React 18 + TypeScript + Vite**, TanStack Query for server state, `vite-plugin-pwa` | Bundle budget ≤ 180 KB gz (React + Clerk cost more than Svelte; budget acknowledges reality but still gates growth). |
| Search | Postgres `tsvector` generated column + GIN | |
| Hosting | **Everything in one `docker compose up`** — dev and production alike (§1.5). The only thing outside Docker is Clerk itself (it's SaaS; there is nothing to containerize). | |

### 1.3 The worker (poller) — multi-tenant edition

- **Claim loop:** every few seconds, `UPDATE feeds SET claimed_until = now()+'2 min' WHERE id IN (SELECT id FROM feeds WHERE next_check_at <= now() AND claimed_until < now() ORDER BY next_check_at LIMIT 50 FOR UPDATE SKIP LOCKED) RETURNING *` — N workers, no coordinator, crash-safe (claims expire).
- **Global dedup is the economics:** one `feeds` row per unique URL regardless of subscriber count. 10k users cost roughly the same to poll as 100.
- **Polite HTTP:** conditional GET (ETag/If-Modified-Since → most polls are 304s), honest User-Agent with contact URL, honor 429/Retry-After and permanent redirects, per-host concurrency 1, adaptive interval per feed (15 min floor for active feeds → 24 h ceiling for dormant ones). At multi-tenant scale politeness is existential: an impolite public poller gets its egress IPs blocked ecosystem-wide.
- **SSRF guard (now critical):** users make *your server* fetch arbitrary URLs. Resolve DNS first, reject private/loopback/link-local/metadata ranges (including on every redirect hop), cap response size (5 MB) and time, allow only http/https.
- **Pipeline:** fetch → parse (thread pool) → sanitize (nh3, strict allowlist; titles treated as plain text everywhere) → dedup on `(feed_id, guid_hash)` with GUID fallback chain (guid → link → hash(title+published)) → batch insert one transaction → tsvector maintained by generated column.
- **Failure handling:** exponential backoff, `last_error` stored on the feed and surfaced in every subscriber's UI; feeds never auto-deleted; orphaned feeds (zero subscribers) garbage-collected after a grace period.

### 1.4 Multi-tenant guardrails (new, required by public hosting)

- **Quotas:** max subscriptions/user (default 300), max OPML import size, per-user API rate limits (in-process token bucket keyed by user id; note: limits are per-API-replica, so with `api` scaled to N the effective limit is ~N× — acceptable for coarse abuse control; move to Redis only if precise global limits ever matter).
- **Isolation:** every query on user-scoped tables filters by `user_id` from the verified JWT — enforced structurally (repository layer takes `user_id` as a required argument; no query helper exists without it).
- **Cost ceilings:** response-size caps, entry-content cap (store first ~500 KB), global concurrent-fetch cap.
- **Legal/ops floor:** terms + privacy page, account deletion (Clerk webhook → local cascade), contact address in the crawler User-Agent.

### 1.5 Deployment: docker compose, dev = prod

The whole stack is one compose file; production is the same file plus an env file on a VPS.

```yaml
services:
  caddy:      # TLS (automatic Let's Encrypt) + serves the built SPA
              # + reverse-proxies /api → api
  api:        # image: alo-reader, command: api      (uvicorn, scale: N)
  worker:     # image: alo-reader, command: worker   (poller, scale: 1..N)
  postgres:   # postgres:18, named volume
  backup:     # nightly pg_dump to a mounted/off-site target (see below)
```

- **One image, two commands:** `api` and `worker` are entrypoints of the same Docker image — one build, no drift between the processes.
- **Frontend:** built to static assets in CI and baked into the Caddy image (multi-stage build). No Node at runtime, no separate frontend deploy. Caddy gives automatic TLS on the VPS with two lines of config.
- **Dev = prod:** `docker-compose.yml` is the base; `docker-compose.dev.yml` overlays hot-reload (uvicorn `--reload`, Vite dev server) and a disposable Postgres. What runs on your laptop is structurally what runs in production.
- **The honest cost — you own the database.** Running Postgres in compose instead of using a managed service means backups, upgrades, and disk are your problem. This is priced in: a `backup` sidecar does nightly `pg_dump` (plus WAL archiving via WAL-G if wanted) to off-box storage, and the **restore drill is a release gate** (WP-16 in `MILESTONES.md`), not a doc footnote. Migrating later to managed Postgres is a `DATABASE_URL` change.
- **Config via environment, nothing hardcoded:** every secret and connection string comes from env vars, never source. `DATABASE_URL` is the single DB knob; compose injects it (with local-dev defaults) and, for non-Docker runs, python-dotenv loads a repo-root `.env` (`.env.example` is the checked-in template). Real env vars always win over `.env`.
- **Clerk exception:** auth is an external SaaS call; compose can't containerize it. Local dev uses a Clerk dev instance (free tier) — or simply `AUTH_MODE=none`, which is also the zero-dependency self-host path (§0.1).

### 1.6 Security posture

Sanitize once at ingest (allowlist, nh3), strict CSP on the SPA, Clerk JWT verification with issuer/audience/expiry checks, svix signature verification on webhooks, SSRF guard as above, secrets only via environment. All feed content is hostile input, always.

### 1.7 Web UI — "early Gmail, for RSS"

The look-and-feel target is **early Gmail (circa 2004–2010): dense, fast, information-first, no chrome, no cards, no social styling.** It reads as a mail client whose "messages" are articles. This is the guiding aesthetic for the M2/M3 frontend WPs (WP-09/10/11/12); it refines, and does not replace, the layout notes in those briefs.

**Three-pane layout** (desktop; collapses to a single pane with back-navigation ≤768px):

```
┌───────────────┬───────────────────────────┬───────────────────────────┐
│  SIDEBAR      │  ARTICLE LIST             │  READING / PREVIEW PANE   │
│  (labels)     │  (the "inbox")            │                           │
│               │                           │                           │
│  All (12)     │  ● BBC   Title of item    │  Title                    │
│  Starred      │    hello world snippet…3h │  Source · author · date   │
│  ─ Folders ─  │  ● Verge  Another title   │                           │
│  ▸ Tech (5)   │    summary line here …·5h │  <sanitized article       │
│  ▾ News (7)   │    Older read item    ·1d │   body renders here,      │
│     BBC (3)   │  …virtualized, infinite…  │   images lazy, links new  │
│     Verge(4)  │                           │   tab>                    │
└───────────────┴───────────────────────────┴───────────────────────────┘
```

- **Sidebar = Gmail's label rail.** Categories (folders) are collapsible groups, each listing its feeds; **unread shows as bold text + a right-aligned count** exactly like Gmail's unread labels. Fixed views on top: `All`, `Starred`. A feed with `last_error` shows a small error dot.
- **Article list = the inbox.** Dense, single-line-ish rows (virtualized, infinite scroll), **newest-received first** (never re-sorted — §0.3). Each row: unread dot, source/feed name, article title, a dim snippet, right-aligned relative time (`created_at`; tooltip = `published_at`). **Unread rows are bold; read rows dim** — the core Gmail read/unread affordance. A list/expanded density toggle is persisted.
- **Reading/preview pane = Gmail's preview pane.** Selecting a row renders the sanitized `content_html` on the right (or full-width on mobile); open-in-place, mark-read-on-open, star, and "open original in new tab".
- **Calm and keyboard-first:** muted palette, generous but tight spacing, no infinite-scroll "engagement" tricks; full `j/k/o/s/m/…` keyboard model (WP-12). The vibe is a **tool that gets out of the way**, not a magazine.

Concrete visual design (typography, exact palette, spacing scale) is decided during WP-09 using the `frontend-design` guidance; this section fixes the *shape and behavior*, not the pixels.

---

## 2. Risks

1. **Feed heterogeneity** (unchanged #1): the RSS ecosystem is malformed XML all the way down. *Mitigation:* feedparser + an append-only **fixture corpus** of real nasty feeds as golden tests; every production parsing bug becomes a fixture before it's fixed.
2. **XSS via feed content:** one sanitizer hole = script in every subscriber's session — multi-tenancy multiplies the blast radius vs. self-hosted. *Mitigation:* nh3 allowlist at ingest, CSP second wall, adversarial test corpus, titles never rendered as HTML.
3. **SSRF / abuse of the fetcher:** now a top-tier risk (public users direct your server at arbitrary URLs, including your cloud metadata endpoint). *Mitigation:* §1.3 guard + tests for every bypass class (redirect hop, DNS rebind via re-resolution, IPv6 mapped addresses).
4. **Clerk as a hard dependency:** outage = nobody logs in; pricing changes; and it blocks the self-host story. *Mitigation:* the `AuthProvider` seam (§0.1) + `AUTH_MODE=none` are the escape hatches — swapping auth is one module, not a rewrite. Accept the tradeoff consciously: Clerk buys you an entire identity subsystem (MFA, OAuth providers, session security) for one integration point.
5. **Crawler reputation:** shared egress IPs may already be soiled, and your own politeness failures poison them further. *Mitigation:* strict politeness (§1.3), monitoring of 403/429 rates per host, documented remediation (dedicated egress IP if needed).
6. **Postgres cost/ops drift:** 50M entries with full HTML is tens of GB. *Mitigation:* content cap, retention purge, `content_raw` compressed, monitor table bloat; backup sidecar + restore drills (§1.5).
7. **Async Python foot-guns:** blocking calls (feedparser, DNS) stalling the event loop. *Mitigation:* thread-pool for sync work, `asyncio` debug mode + blocked-loop watchdog in CI/staging.
8. **Scope creep vs. philosophy** (unchanged): features that rank, recommend, or interrupt are rejected regardless of demand.

---

## 3. Tradeoffs

| Decision | We gain | We give up | Verdict |
|---|---|---|---|
| **Python/FastAPI over Go** | Developer velocity and preference (decisive — you'll actually enjoy maintaining it), rich ecosystem, Pydantic contracts | Single-binary deploys; raw poller throughput; must actively police event-loop blocking | Right call given the maintainer. The performance goal is *UI-perceived* speed, which lives in query shape and frontend discipline, not backend language. |
| **Postgres over SQLite** | Real concurrency for multi-tenant writes, managed backups/HA, horizontal API scaling | The zero-ops one-file story | Forced by public hosting; correct. |
| **Clerk over self-rolled auth** | MFA, OAuth providers, session hardening, account UX — for free on day one | Vendor lock (mitigated by seam + `AUTH_MODE=none`), per-MAU pricing later | Right for public-first; a solo maintainer should not hand-roll public-internet auth in 2026. |
| **Postgres-as-queue over Celery/Redis** | Two fewer services; crash-safe claiming via `SKIP LOCKED`; trivial local dev | At ~100k+ feeds, a dedicated queue would schedule more smoothly | Revisit at 10× target scale; not before. |
| **Postgres FTS over a search engine (Elastic/Meili/Typesense)** | Zero extra services; index updates transactional with inserts; one backup story | Weaker relevance tuning, no typo tolerance out of the box, English-only stemming in v1 | At ~50M short documents Postgres GIN is comfortably inside the latency budget (§4.1); a search service is post-10×-scale territory. |
| **Separate React SPA over server-rendered** | Reader-grade interaction speed, Clerk's happy path, static frontend, offline PWA | Two build artifacts (no CORS needed: Caddy serves SPA and API same-origin); SEO irrelevance is fine (app behind login) | Settled — see §0.2. |
| **Received-time ordering over published-time** | Stable inbox, stable cursors, no reshuffling | Slow-polled feeds surface "late" | Unchanged from v1; still the core calm-UX decision. |
| **Public-first with a self-host seam** | One product focus; self-host stays plausible (`AUTH_MODE=none`) | Self-host is no longer the polished path | Honest reflection of the new goal. |

---

## 4. Database design

Postgres 18. `BIGSERIAL` entry ids preserve the v1 trick: **insertion order ≈ chronological "received" order**, so the primary key doubles as sort key and pagination cursor. Timestamps are `timestamptz`.

```sql
-- ── Identity (Clerk-synced) ─────────────────────────────────
users (
  id             BIGSERIAL PRIMARY KEY,
  clerk_user_id  TEXT UNIQUE,               -- webhook-synced; NULL in AUTH_MODE=none
  email          TEXT NOT NULL DEFAULT '',  -- empty in AUTH_MODE=none
  quota_subs     INT  NOT NULL DEFAULT 300,
  created_at     timestamptz NOT NULL DEFAULT now()
)
-- No sessions/password tables: Clerk owns credentials & sessions.
-- api_tokens retained for programmatic access (PATs), hashed at rest:
api_tokens (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash BYTEA NOT NULL UNIQUE,
  label TEXT NOT NULL,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
)

-- ── Feeds (global, deduped across ALL users; polled once) ───
feeds (
  id               BIGSERIAL PRIMARY KEY,
  feed_url         TEXT NOT NULL UNIQUE,
  site_url         TEXT,
  title            TEXT NOT NULL DEFAULT '',
  etag             TEXT,
  last_modified    TEXT,
  next_check_at    timestamptz NOT NULL DEFAULT 'epoch',
  claimed_until    timestamptz NOT NULL DEFAULT 'epoch',  -- worker lease
  check_interval_s INT NOT NULL DEFAULT 3600,
  error_count      INT NOT NULL DEFAULT 0,
  last_error       TEXT,
  last_fetched_at  timestamptz,
  icon_id          BIGINT REFERENCES icons(id),
  created_at       timestamptz NOT NULL DEFAULT now()
)
CREATE INDEX idx_feeds_due ON feeds (next_check_at) WHERE claimed_until < now();
icons ( id BIGSERIAL PRIMARY KEY, url TEXT UNIQUE, mime TEXT, data BYTEA )

-- ── User's view of feeds ────────────────────────────────────
folders (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  position INT NOT NULL DEFAULT 0,
  UNIQUE (user_id, name)
)
subscriptions (
  id             BIGSERIAL PRIMARY KEY,
  user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  feed_id        BIGINT NOT NULL REFERENCES feeds(id),
  folder_id      BIGINT REFERENCES folders(id) ON DELETE SET NULL,
  title_override TEXT,
  since_entry_id BIGINT NOT NULL DEFAULT 0,  -- entries ≤ this predate the
                                             -- subscription: never "unread"
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, feed_id)
)
CREATE INDEX idx_subs_feed ON subscriptions(feed_id);  -- fan-out & GC queries

-- ── Content ─────────────────────────────────────────────────
entries (
  id            BIGSERIAL PRIMARY KEY,       -- ≈ received order: sort + cursor
  feed_id       BIGINT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
  guid_hash     BYTEA NOT NULL,
  url           TEXT,
  title         TEXT NOT NULL DEFAULT '',    -- plain text, never HTML
  author        TEXT,
  content_html  TEXT NOT NULL DEFAULT '',    -- nh3-sanitized at ingest
  content_raw   BYTEA,                       -- zstd(original): re-sanitize insurance
  published_at  timestamptz,                 -- as claimed by the feed; display only
  created_at    timestamptz NOT NULL DEFAULT now(),
  search_tsv    tsvector GENERATED ALWAYS AS (
                  setweight(to_tsvector('english', coalesce(title,'')), 'A') ||
                  setweight(to_tsvector('english', left(strip_html(content_html), 20000)), 'B')
                ) STORED,                    -- strip_html = small IMMUTABLE SQL fn
  UNIQUE (feed_id, guid_hash)
)
CREATE INDEX idx_entries_feed ON entries (feed_id, id DESC);
CREATE INDEX idx_entries_fts  ON entries USING GIN (search_tsv);

-- ── Per-user state (row exists only once touched) ───────────
entry_states (
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  entry_id   BIGINT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  is_read    BOOLEAN NOT NULL DEFAULT false,
  is_starred BOOLEAN NOT NULL DEFAULT false,
  changed_at timestamptz NOT NULL,           -- LWW merge key (offline queue)
  PRIMARY KEY (user_id, entry_id)
)
CREATE INDEX idx_states_read    ON entry_states (user_id, entry_id) WHERE is_read;
CREATE INDEX idx_states_starred ON entry_states (user_id, entry_id) WHERE is_starred;

-- ── Supplementary indexes: Postgres does not auto-index foreign keys, so every
--    FK that participates in a cascade (or is filtered on directly) gets one.
--    Unindexed FKs turn a parent DELETE into a full child scan.
CREATE INDEX idx_api_tokens_user  ON api_tokens   (user_id);          -- user delete cascade + token listing
CREATE INDEX idx_subs_folder      ON subscriptions(folder_id);        -- folder SET NULL cascade + folder streams
CREATE INDEX idx_states_entry     ON entry_states (entry_id);         -- entry delete cascade (PK is user_id-first)
CREATE INDEX idx_folders_user_pos ON folders      (user_id, position);-- ordered per-user folder listing
```

> **Indexing rule (project-wide):** every foreign key involved in a cascade and
> every column a query filters/sorts on must be backed by an index. Add the index in
> the same migration as the query — don't ship a scan.

**Semantics (unchanged from v1, restated because they're the product):**

- **Unread** = entry in a subscribed feed with `entry.id > subscription.since_entry_id` and no `is_read` state row. Subscribing never dumps a feed's archive on you as unread.
- **Unread counts** computed per subscription via `idx_entries_feed` anti-joined against the partial read index — exact, index-only, no counter drift. (At 5k users the per-user count query touches only that user's ~300 subscriptions; verified against the perf budget in §7.)
- **Mark-all-read is bounded** by `max_entry_id` supplied by the client — items arriving mid-action are never silently swallowed.
- **Retention purge** deletes entries only when older than horizon *and* read-or-unsubscribed by every subscriber *and* starred by no one.
- **BIGSERIAL ordering caveat, acknowledged:** under concurrent inserts, sequence order can differ from commit order by a hair. For this product (items poll in ~minutes apart) it is irrelevant; cursors remain correct because they're exclusive-bounded on id.

### 4.1 Full-text search — the plan (English-first, entirely in Postgres)

Postgres FTS is fully sufficient here; no external search engine. The design:

1. **What's indexed:** entry title (weight A) and the first 20k chars of tag-stripped content (weight B), via the `search_tsv` STORED generated column above. Because it's a generated column, the index is maintained **transactionally with every insert/update/delete** — there is no separate indexing job to build, monitor, backfill, or repair, and the retention purge cleans the index automatically.
2. **Language — English first:** the `'english'` regconfig gives stemming ("running" → "run", "feeds" → "feed") and stopword removal. Non-English content is still indexed and searchable by exact word forms; quality is merely lower. This is the right v1 tradeoff for an English-dominant feed ecosystem.
3. **Query semantics:** `websearch_to_tsquery('english', $q)` — Google-like syntax users already know: bare words are AND'd, `"quoted phrases"`, `OR`, `-exclusion`. It never raises on malformed input (unlike `to_tsquery`), so user input needs no pre-parsing.
4. **Ordering — chronological, not relevance:** results stay strictly `id DESC`, scoped to the requested stream. `ts_rank` is deliberately unused: relevance ranking is a scored feed, which violates the product philosophy (§0). Weighting (A/B) exists only so a future ranked mode *could* be offered, not because v1 uses it.
5. **Snippets:** `ts_headline('english', …)` generates highlighted excerpts — but it re-parses documents and is the expensive step, so it runs **only on the returned page** (limit is capped at 50 when `q` is present), never during matching.
6. **Scale & cost:** capped tsvectors over ~50M entries yield a GIN index in the single-digit-GB range; the p95 < 100 ms budget is benchmark-gated in WP-13 (100k entries per-PR, 5M nightly). GIN write amplification at poller insert rates is negligible.
7. **Post-1.0 upgrade paths (API contract unchanged for all of them):**
   - *Multilingual:* detect language at ingest, store `entries.lang`, regenerate `search_tsv` via an immutable `CASE lang WHEN 'de' THEN to_tsvector('german',…) …` over a fixed config set, backfill by migration.
   - *Typo/substring tolerance:* `pg_trgm` GIN index on titles.
   - *Ranked mode:* opt-in `sort=relevance` using the existing weights — only if it can be squared with the philosophy.

---

## 5. API contracts

REST, JSON, `/api/v1`. Auth: `Authorization: Bearer <Clerk session JWT>` (SPA) or a PAT. Pydantic models generate the OpenAPI spec — the spec, not this doc, becomes the source of truth once the auth work package lands. Uniform errors:

```json
{ "error": { "code": "quota_exceeded", "message": "subscription limit (300) reached" } }
```
`400 invalid_request · 401 unauthenticated · 403 forbidden · 404 not_found · 409 conflict · 422 validation_error · 429 rate_limited · 500 internal`

### Auth & account
```
GET    /config              → { auth_mode, clerk_publishable_key? }   # public
GET    /me                  → { id, email, quotas, counts_summary }
GET    /tokens              → [{id, label, created_at, last_used_at}]
POST   /tokens              { label } → { token }        # shown once
DELETE /tokens/{id}         → 204
POST   /webhooks/clerk      # svix-verified; user.created/updated/deleted sync
```
(No login/logout endpoints — Clerk owns those flows in the SPA; `AUTH_MODE=none` needs none.)

### Subscriptions & folders
```
POST   /discover            { url } → [{ feed_url, title }]
GET    /subscriptions       → [{ id, feed_id, title, site_url, folder_id,
                                 icon_url, last_error, last_fetched_at }]
POST   /subscriptions       { feed_url, folder_id? } → 201   # 409 if dup,
                            # 422 if quota; reuses global feed; fetch queued
PATCH  /subscriptions/{id}  { title_override?, folder_id? }
DELETE /subscriptions/{id}  → 204
POST   /subscriptions/{id}/refresh → 202                     # rate-limited

GET/POST/PATCH/DELETE /folders …                             # as v1
```

### Streams & entries
Stream = `all` | `feed/{id}` | `folder/{id}` | `starred` — the one query abstraction (and the future Fever/GReader-compat seam).
```
GET /streams/{stream}/entries
      ?status=unread|all &cursor={entry_id} &limit=50 &q=terms
  → { "entries": [ { id, feed_id, feed_title, url, title, author,
                     summary, published_at, created_at,
                     is_read, is_starred } ],
      "next_cursor": "18832" | null }
GET /entries/{id}            → full entry incl. content_html
```
Newest-first by `id`, exclusive cursor — stable under concurrent inserts.

### State (idempotent; the PWA replay target)
```
POST /entries/state              { ids: [..≤1000], read?: bool, starred?: bool,
                                   changed_at?: ts }   # LWW, ties bias read=true
                                 → { updated: n }
POST /streams/{stream}/mark-read { max_entry_id } → { updated: n }
```

### Counts, OPML, ops
```
GET  /counts     → { total_unread, subscriptions: [{id, unread}] }
GET  /opml       → OPML export          POST /opml → import (per-feed report)
GET  /healthz    → 200                  GET /metrics → Prometheus (internal only)
```

---

## 6. Implementation plan → `MILESTONES.md`

The full development plan lives in **`MILESTONES.md`**: 17 work packages (WP-00…WP-16) across four milestones — **M1** headless reader (API-complete, curl-usable), **M2** daily driver (web reading flow), **M3** power user (keyboard, search, PWA/offline), **M4** public 1.0 (hardening, deploy, docs). Each package is a standalone, delegation-ready brief: pinned dependencies, exact deliverables and file locations, runnable acceptance commands, and explicit out-of-scope lists — written so a coding model can implement it without making a single design decision.

Principles that govern the plan: small strictly-ordered packages; every design decision made *here*, none by implementers; riskiest subsystems first (ingest, worker, tenant isolation); every merge leaves `main` deployable; acceptance criteria are encoded as tests, not judgment calls.

**Post-1.0 backlog:** Fever + GReader compat adapter, full-content extraction, image proxy (privacy), proxy-header auth provider (`AUTH_MODE=proxy` for Authelia/Authentik multi-user self-hosting), multilingual search + `pg_trgm` fuzzy matching (§4.1 upgrade paths), per-feed publish-date sort toggle, billing/paid tier, WebSub.

---

## 7. Test strategy

**Principle unchanged: test weight goes where risk lives** — ingest (hostile input), tenant isolation (new #1), and read-state semantics (trust-critical).

**Test infrastructure rule: always use Testcontainers when a test needs a real service.** Anything requiring Postgres (or any other backing service) spins up an **ephemeral throwaway container** via `testcontainers[postgres]`, provisioned by the test session and discarded after — never the developer's real/dev database, never a shared instance, never mocks. This keeps tests hermetic and parallel-safe and guarantees a test run can never touch real data. (`make migrate` still runs against the real dockerized Postgres — that is an ops command, not a test.)

| Layer | What | How |
|---|---|---|
| **Unit — ingest** | Parser normalization, GUID chain, dates, summaries | Golden files over the append-only fixture corpus; every prod parsing bug becomes a fixture first. |
| **Unit — sanitizer** | XSS resistance | Adversarial corpus (scripts, handlers, `javascript:`/data URIs, SVG, encoding tricks) → exact allowlist output. |
| **Integration — API** | Every endpoint, auth matrix, **cross-tenant isolation probes**, pagination stability, count exactness | Testcontainers Postgres per test session (transactional rollback per test), no DB mocks ever; counts property-tested vs brute force on randomized data. |
| **Integration — worker** | 304/429/301/timeout/oversize, SSRF bypass classes, claim-loop exclusivity, lease expiry | httpx MockTransport / local test server; two concurrent workers in the claim test. |
| **Contract** | SPA ↔ API drift | OpenAPI schema exported from FastAPI; frontend client types generated from it in CI — drift fails the build. |
| **E2E — web** | Sign-up→subscribe→read→keyboard-only→offline queue→account deletion | Playwright vs real stack (Clerk dev instance + `AUTH_MODE=none` profile), ~12 journeys, zero flake tolerance. |
| **Performance** | API p95 < 100 ms & search < 100 ms on 5M-entry seed; 60fps scroll; bundle ≤ 180 KB gz; Lighthouse ≥ 90 | Seeded benchmark job, regression-gated; Playwright trace assertions; size-limit per PR. |
| **Async hygiene** | Event-loop blocking | Blocked-loop watchdog in tests/staging; feedparser confined to executor verified by test. |
| **Migrations** | Forward-apply from every released version | CI applies Alembic chain to prior-release schema snapshots. |
| **Security** | SSRF, webhook forgery, deleted-user token reuse, quota bypass | Dedicated abuse-scenario suite (WP-15 in `MILESTONES.md`); pip-audit in CI. |

CI gates every PR: ruff + mypy, unit, integration, contract, E2E, bundle size, benchmark regression. A work package is done when its acceptance criteria are encoded as tests.
