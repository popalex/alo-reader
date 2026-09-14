"""Boot validation: the server refuses to start without an explicit AUTH_MODE."""

from collections.abc import Iterator

import pytest

from app.config import get_settings, validate_boot_config
from app.main import app


@pytest.fixture
def boot_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost:1/x")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_boot_refuses_without_auth_mode(boot_env: pytest.MonkeyPatch) -> None:
    boot_env.delenv("AUTH_MODE", raising=False)
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match="AUTH_MODE must be set"):
        validate_boot_config()


def test_boot_refuses_invalid_auth_mode(boot_env: pytest.MonkeyPatch) -> None:
    boot_env.setenv("AUTH_MODE", "password")
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match="AUTH_MODE must be set"):
        validate_boot_config()


def test_boot_refuses_empty_auth_mode(boot_env: pytest.MonkeyPatch) -> None:
    boot_env.setenv("AUTH_MODE", "")
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match="AUTH_MODE must be set"):
        validate_boot_config()


@pytest.mark.parametrize("mode", ["clerk", "none"])
def test_boot_accepts_valid_modes(boot_env: pytest.MonkeyPatch, mode: str) -> None:
    boot_env.setenv("AUTH_MODE", mode)
    boot_env.setenv("CLERK_ISSUER", "https://app.clerk.accounts.dev")
    boot_env.setenv("CLERK_WEBHOOK_SECRET", "whsec_x")
    get_settings.cache_clear()
    validate_boot_config()  # must not raise


@pytest.mark.parametrize(
    ("issuer", "secret"),
    [("", "whsec_x"), ("app.clerk.accounts.dev", "whsec_x"), ("https://app.clerk.dev", "")],
)
def test_clerk_mode_refuses_incomplete_config(
    boot_env: pytest.MonkeyPatch, issuer: str, secret: str
) -> None:
    # Both settings fail silently at runtime: an empty issuer makes the JWKS URL
    # relative, so every sign-in is a 401 with nothing in the log, and an empty
    # webhook secret 500s every delivery until Clerk stops retrying, leaving local
    # rows with no email and no deletions.
    boot_env.setenv("AUTH_MODE", "clerk")
    boot_env.setenv("CLERK_ISSUER", issuer)
    boot_env.setenv("CLERK_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match="AUTH_MODE=clerk is missing"):
        validate_boot_config()


def test_none_mode_ignores_clerk_config(boot_env: pytest.MonkeyPatch) -> None:
    boot_env.setenv("AUTH_MODE", "none")
    boot_env.setenv("CLERK_ISSUER", "")
    boot_env.setenv("CLERK_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    validate_boot_config()  # must not raise


async def test_lifespan_exits_without_auth_mode(boot_env: pytest.MonkeyPatch) -> None:
    """The check is wired into the app's lifespan, i.e. it actually gates boot."""
    boot_env.delenv("AUTH_MODE", raising=False)
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match="AUTH_MODE must be set"):
        async with app.router.lifespan_context(app):
            pass
