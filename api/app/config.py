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

    # AUTH_MODE has deliberately no default: the server refuses to boot without
    # an explicit choice (DESIGN.md §0.1 — "none" must never be implicit).
    auth_mode: str | None = None

    # Per-user token-bucket rate limit (DESIGN.md §1.4): refill rate and burst
    # capacity, per API replica.
    rate_limit_rps: float = 10.0
    rate_limit_burst: int = 30

    # Minimum spacing between manual /subscriptions/{id}/refresh calls per feed
    # (per API replica), so a user can't hammer the poller.
    subscription_refresh_window_s: float = 300.0

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
    favicon_max_bytes: int = 100 * 1024  # stored favicon cap

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
    worker_lease_s: int = 120
    worker_max_concurrency: int = 20

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
