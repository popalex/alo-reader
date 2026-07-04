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

    # Fetcher / poller (DESIGN.md §1.3). The contact URL goes into an honest
    # crawler User-Agent so hosts can reach us; the caps bound cost and abuse.
    fetch_contact_url: str = "https://github.com/popalex/alo-reader"
    fetch_timeout_s: float = 30.0
    fetch_max_bytes: int = 5 * 1024 * 1024
    fetch_max_redirects: int = 5

    @property
    def user_agent(self) -> str:
        """Honest, contactable crawler UA (DESIGN.md §1.3)."""
        return f"alo-reader/1.0 (+{self.fetch_contact_url})"


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
