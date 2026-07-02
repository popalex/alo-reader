"""Application configuration.

The database connection string is never hardcoded: it is read from the
``DATABASE_URL`` environment variable. For local (non-Docker) runs, a repo-root
``.env`` file is loaded via python-dotenv; inside Docker/compose the variable is
injected from the same ``.env`` and always takes precedence.
"""

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Populate os.environ from a repo-root .env when present. Real environment
# variables (e.g. those set by docker compose) are not overridden.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Sourced from DATABASE_URL; required, no default (no hardcoded credentials).
    database_url: str


settings = Settings()  # type: ignore[call-arg]
