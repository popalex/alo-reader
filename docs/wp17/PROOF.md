# Proof inventory — WP-17

Every claim the launch pages are allowed to make, the number attached to it, and the
thing in this repo that makes it true. The WP-17 acceptance criterion is that each
claim checks out against the code that implements it, so this is the source both
briefs write from.

**Rule for anyone writing copy: no number appears on a page unless it appears here.**
Nothing on this list is aspirational. Where a number came from a benchmark, the
benchmark's conditions are part of the claim.

Measured or read on 2026-09-16, against `main` at `ccd08f1`.

## What the product does

| Claim | Proof | Caveat |
| --- | --- | --- |
| Chronological, no algorithm | Listing is ordered by publish date on a composite cursor (`api/app/store/entries.py`, migration 0007). There is no ranking, scoring or recommendation code anywhere in the repo — that absence *is* the feature. | — |
| Search across your whole archive | Postgres full-text search on a RUM index (`deploy/Dockerfile.postgres`, migration 0003), index-ordered so a chronological `LIMIT 50` needs no sort. | — |
| **p95 ~35 ms at 5 million entries** | `scripts/bench_search.py`, run nightly (`.github/workflows/nightly.yml`), 5 cold runs. | CI hardware, seeded corpus. Say "in our benchmark", never "on your instance". |
| Lists stay fast under load | WP-15 load test (`scripts/loadtest.py`): stream p95 ~14 ms, counts ~6 ms at 1k users / 20k feeds / 1M entries. | Same caveat. Older profile than the search number. |
| Keyboard-driven | `web/src/keyboard/bindings.ts`: `j`/`k` next/previous, `o` or `Enter` open, `s` star, `m` read/unread, `v` original, `A` mark all read, `r` refresh, `g a` / `g s` go to All / Starred, `/` search, `?` help. | The list on the page must match this file exactly. |
| Works offline | WP-14 PWA. Articles opened while online stay readable offline; read and star changes queue in an IndexedDB outbox (`web/src/app/offline/queue.ts`) and replay on reconnect. | It is **not** a full offline archive — unopened articles are not there. Do not imply otherwise. |
| OPML import in one step | `POST /api/v1/opml/import`, synchronous, reports per-URL failures instead of failing the batch; export too. 1 MiB upload cap (`OPML_MAX_BYTES`). | A 300-feed OPML is ~60 kB, so the cap is not a practical limit. |
| The app is small | **142.54 kB gzipped** initial JS + CSS, measured 2026-09-16 with `pnpm size`; the 180 kB budget is enforced on every PR (`bundle-size` job). | Re-measure before publishing; it moves. |

## What happens to your data

| Claim | Proof | Caveat |
| --- | --- | --- |
| Starred articles kept forever | Purge touches read **and** unstarred rows only (`entries.purge_retained`). | — |
| Unread is never purged | Same. | — |
| Read + unstarred purged after 90 days, and only once **every** subscriber has read them | `retention_horizon_days = 90` (`api/app/config.py:190`), and the purge predicate requires no subscriber still has it unread. | The horizon is configurable per instance; on the public instance state the number you actually run. |
| Deleting your account deletes your data | Clerk `user.deleted` webhook → local cascade, proven by an e2e that populates all four user-owned tables and asserts them empty afterwards, with the table list read from `information_schema` so a new table cannot escape. | Shared feed/entry rows survive by design (other subscribers have them); the feed is marked orphaned and GC'd after `ORPHAN_GRACE_DAYS` (7) if nobody else subscribes. Say it plainly. |
| Backed up nightly, and the backups are verified | `deploy/backup.sh`: `pg_dump | zstd`, then `zstd -t` **and** `pg_restore -l` before the file is allowed to count; 14 days retained; freshness alerts if a day is missed (`docs/ALERTS.md#backup-freshness`). | Restores are drilled, not assumed — the WP-16 drill restored 5001 entries with sequences and the generated search column intact. |
| Per-account limits | 300 subscriptions (`api/app/store/users.py`), 20 API tokens (`api/app/config.py:98`). | — |

## Who else touches your data

Be exact here. This is the section a skeptical reader checks.

| Party | What they get | Proof |
| --- | --- | --- |
| **Clerk** | Identity: email, auth, sessions. Named SaaS, not optional in `AUTH_MODE=clerk`. | DESIGN.md §0.1, `api/app/auth/clerk.py` |
| **Sentry** | Nothing unless a DSN is set. When it is: errors only, `send_default_pii=False`, `traces_sample_rate=0`, logging integration bounded to breadcrumbs at INFO / events at ERROR. | `api/app/sentry.py` |
| **Telemetry (OTel/Grafana)** | Self-hosted on the same box. Off by default; the browser half only turns on when `/api/v1/config` says so. | `deploy/docker-compose.otel.yml` |
| **Third-party analytics** | None. No analytics dependency exists in `web/package.json`. | verifiable by anyone |

## Why feeds you subscribe to will not hate us

| Claim | Proof |
| --- | --- |
| Conditional GET — most polls are a `304` | `If-None-Match` / `If-Modified-Since` sent and `304` handled (`api/app/worker/fetch.py`) |
| Adaptive interval, 15 min floor → 24 h ceiling | `worker_interval_floor_s = 900`, `worker_interval_ceil_s = 86400` (`api/app/config.py:170-171`) |
| Backs off on errors | exponential, base 900 s, cap 24 h (`api/app/config.py:175-176`) |
| Honest User-Agent with a contact URL | `alo-reader/1.0 (+<FETCH_CONTACT_URL>)` (`api/app/config.py:131`) — **set that variable before launch or the UA has no contact** |
| Feeds are fetched once and shared | Feeds are globally deduped; the tenth subscriber to a popular feed costs no extra fetches. |

## Safety of feed content

Sanitized at ingest with an nh3 allowlist, sanitized again in the browser with
DOMPurify, and a CSP as the third wall (`deploy/Caddyfile`). `javascript:` URLs are
rejected on the way in and refused at every render site. Titles are never rendered as
HTML. Five security findings were closed during the pre-1.0 review, including a
cross-tenant read and an XXE bypass — evidence the claim is maintained, not decorative.

## Claims that are NOT available

Do not write these, in any phrasing:

- **"Open source."** There is **no LICENSE file in the repo.** "Self-hostable" is true and provable (`make up`, `AUTH_MODE=none`); "open source" is not a thing you can say until a license is chosen and committed.
- **"Free forever."** Billing is in DESIGN.md's post-1.0 backlog. The available claim is **"free while in beta"**, and saying it that way is more trustworthy than the alternative.
- **"Your data never leaves our server."** Clerk holds identity by design.
- **"No tracking"**, unqualified. True of third-party analytics; the honest version names Sentry-if-enabled and self-hosted telemetry.
- **Uptime, SLA, or "always available."** One box, one Postgres, no HA. Beta.
- **"Unlimited" anything.** There are quotas, deliberately.
- **Any user count, growth number, or testimonial.** There are none yet.
- **Comparisons to named competitors.** Ages badly, invites argument, and nobody has to lose for this to be good.
