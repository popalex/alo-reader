"""Application configuration.

Nothing is hardcoded: settings are read from the environment. For local
(non-Docker) runs, a repo-root ``.env`` file is loaded via python-dotenv; inside
Docker/compose the variables are injected from the same ``.env`` and always take
precedence.

Settings are constructed lazily via :func:`get_settings` so importing this module
never requires the environment to be populated (tests set ``DATABASE_URL`` only
after their throwaway Postgres container is up).

Auth-provider-specific settings (e.g. the hosted-auth SaaS keys) live inside
``app/auth/`` — this module knows only the mode switch.
"""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Populate os.environ from a repo-root .env when present. Real environment
# variables (e.g. those set by docker compose) are not overridden.
load_dotenv()

AUTH_MODES = ("clerk", "none")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Sourced from DATABASE_URL; required, no default (no hardcoded credentials).
    database_url: str

    # Connection pool (per process). pool_size must be >= worker_max_concurrency
    # (below) or the worker's concurrent per-feed transactions starve on the pool.
    # pre_ping revives connections dropped by a DB restart / idle timeout; recycle
    # bounds connection age. statement_timeout is a server-side ceiling on any single
    # statement (bounds a pathological query); it must exceed the largest expected
    # maintenance batch (the retention purge is bounded to retention_purge_batch_size).
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_recycle_s: int = 1800
    db_statement_timeout_ms: int = 30_000

    # OpenTelemetry (traces + metrics + logs), off by default. When true, the process
    # must be installed with the ``otel`` extra and OTEL_EXPORTER_OTLP_* are read from
    # the environment by the SDK. The browser SPA turns its own telemetry on from
    # /config (otel_enabled + otel_traces_url). Enabled by the OTel compose overlay.
    otel_enabled: bool = False
    otel_service_name: str = "alo-api"
    # Same-origin path the browser posts spans to (Caddy proxies /otlp → collector).
    otel_traces_url: str = "/otlp/v1/traces"

    # AUTH_MODE has deliberately no default: the server refuses to boot without
    # an explicit choice (DESIGN.md §0.1 — "none" must never be implicit).
    auth_mode: str | None = None

    # Per-user token-bucket rate limit (DESIGN.md §1.4): refill rate and burst
    # capacity, per API replica.
    rate_limit_rps: float = 10.0
    rate_limit_burst: int = 30

    # Per-IP token bucket applied BEFORE authentication (bounds the pre-auth cost of
    # the provider chain — a DB lookup for an invalid PAT, a JWT signature verify for a
    # bogus Clerk token). Deliberately looser than the per-user bucket so an
    # authenticated user still hits the per-user limit first. Keyed on the real client
    # IP that Caddy injects (X-Real-IP); see AuthMiddleware. Per API replica.
    rate_limit_ip_rps: float = 50.0
    rate_limit_ip_burst: int = 120

    # Minimum spacing between manual /subscriptions/{id}/refresh calls per feed
    # (per API replica), so a user can't hammer the poller.
    subscription_refresh_window_s: float = 300.0

    # Max personal access tokens per user (DESIGN.md §1.4 quota audit). Creating one
    # past the cap is a 422 quota_exceeded, so a script can't mint unbounded tokens.
    quota_api_tokens: int = 20

    # Minimum spacing between /discover calls per user (per API replica). Discovery
    # makes the server fetch an arbitrary page, so it's rate-limited harder than the
    # coarse global bucket to bound that SSRF/cost surface.
    discover_window_s: float = 5.0

    # Fetcher / poller (DESIGN.md §1.3). An operator may set a contact URL so hosts
    # can reach them; it's optional and empty by default (no personal URL baked in).
    # The caps bound per-fetch cost/abuse.
    fetch_contact_url: str = ""
    fetch_timeout_s: float = 30.0
    fetch_max_bytes: int = 5 * 1024 * 1024
    fetch_max_redirects: int = 5

    # Comma-separated hostnames exempt from the SSRF private-range block (they still
    # must be http/https and resolvable). Default empty. Intended for trusted
    # internal/test feed servers — e.g. a fixture host in the compose network.
    fetch_allow_hosts: str = ""

    @property
    def fetch_allow_hosts_set(self) -> frozenset[str]:
        return frozenset(h.strip() for h in self.fetch_allow_hosts.split(",") if h.strip())

    # OPML / discovery / icons (WP-08) size caps.
    opml_max_bytes: int = 1 * 1024 * 1024  # reject larger OPML uploads
    discover_max_bytes: int = 2 * 1024 * 1024  # HTML page cap for feed discovery
    favicon_max_bytes: int = 100 * 1024  # stored site-favicon cap
    # A feed's own artwork (podcast cover, channel image) is preferred over the
    # favicon and is larger (square art), so it gets a roomier cap.
    feed_image_max_bytes: int = 512 * 1024

    @property
    def user_agent(self) -> str:
        """Crawler UA (DESIGN.md §1.3); appends a ``(+contact)`` only if configured."""
        if self.fetch_contact_url:
            return f"alo-reader/1.0 (+{self.fetch_contact_url})"
        return "alo-reader/1.0"

    # Worker / poller (DESIGN.md §1.3). The claim loop wakes every
    # WORKER_POLL_INTERVAL_S, claims WORKER_CLAIM_BATCH due feeds under a
    # WORKER_LEASE_S lease, and fetches at most WORKER_MAX_CONCURRENCY at once.
    worker_poll_interval_s: float = 5.0
    worker_claim_batch: int = 50
    # Lease must outlast the worst-case time to drain one claimed batch, or a slow
    # batch loses its lease mid-flight and another replica re-claims in-flight feeds
    # (idempotent, but wasteful). Worst case ≈ ceil(batch/concurrency) × fetch_timeout
    # = ceil(50/20) × 30s = 90s, plus per-host spacing — 300s leaves comfortable margin.
    worker_lease_s: int = 300
    worker_max_concurrency: int = 20
    # Cap entries persisted from a single fetch, so a pathological feed advertising
    # thousands of items can't build one unbounded INSERT/transaction. The newest N by
    # publish date are kept (undated last). Well above any sane feed's item count.
    worker_max_entries_per_fetch: int = 2000

    # Politeness per origin host: at most this many concurrent fetches to one
    # host, and at least this long between successive fetches to it.
    worker_per_host_concurrency: int = 1
    worker_per_host_delay_s: float = 1.0

    # Fetch a feed's favicon on its first successful poll (WP-08). Best-effort.
    worker_fetch_favicons: bool = True

    # Adaptive poll interval bounds (seconds): active feeds trend toward the
    # floor, dormant ones toward the ceiling.
    worker_interval_floor_s: int = 900
    worker_interval_ceil_s: int = 86_400

    # Exponential backoff on fetch/parse errors: base doubled per consecutive
    # error, clamped to the cap.
    worker_backoff_base_s: int = 900
    worker_backoff_cap_s: int = 86_400

    # Worker-embedded maintenance (WP-15, DESIGN.md §0.3, §1.3): orphan-feed GC +
    # retention purge run periodically, jittered so N workers don't all fire at once.
    worker_maintenance_interval_s: float = 3600.0
    worker_maintenance_jitter_s: float = 300.0
    # Delete a feed with zero subscribers for longer than this (orphan GC grace).
    orphan_grace_days: int = 7
    # Purge read+unstarred entries older than this whose every subscriber has read
    # them (starred kept forever; unread never purged). DESIGN.md §0.3.
    retention_horizon_days: int = 90
    # Retention purge runs in bounded batches (per transaction) so a large backlog
    # never locks the whole entries table in one statement.
    retention_purge_batch_size: int = 5000


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def validate_boot_config() -> None:
    """Refuse to boot without an explicit, valid AUTH_MODE (DESIGN.md §0.1)."""
    mode = get_settings().auth_mode
    if mode not in AUTH_MODES:
        raise SystemExit(
            f"AUTH_MODE must be set to one of {'|'.join(AUTH_MODES)} (got {mode!r}). "
            "There is no default: 'none' disables auth entirely and must only be "
            "used behind a private network (see DESIGN.md §0.1)."
        )
