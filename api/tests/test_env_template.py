"""`.env.example` is the deployment contract; keep it honest.

The template is how an operator discovers what is configurable, and every line in
it is commented out, so a stale value looks exactly like a correct one. Two ways
it rots: a new Settings field never gets a line, or a default changes in code and
the template keeps claiming the old number. Both had happened by WP-16 — nine
fields were undocumented and WORKER_LEASE_S still advertised 120 after the code
moved to 300.

Only presence and values are checked here. Prose is on the author.
"""

import os
from pathlib import Path

import pytest

from app.config import Settings

# AUTH_MODE's pydantic default is None, a sentinel: validate_boot_config refuses to
# start unless it holds a real mode, so it is required in practice and the template
# has to show it live. None is not a value an env file can express, so it is only
# excluded from the default comparison, not from the presence checks.
SENTINEL_REQUIRED = {"AUTH_MODE"}

# Fields whose template line is deliberately an example rather than the default,
# because the default is empty and an empty line teaches nothing.
ILLUSTRATIVE = {
    "FETCH_CONTACT_URL": "shows the shape of a contact URL; the default is empty",
    "FETCH_ALLOW_HOSTS": "shows a fixture hostname; the default is empty",
    "SENTRY_DSN": "shows the shape of a DSN; the default is empty, which means off",
}


def _template() -> str:
    root = os.getenv("ALO_REPO_ROOT")
    candidates = [Path(root) / ".env.example"] if root else []
    candidates.append(Path(__file__).resolve().parents[2] / ".env.example")
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    pytest.fail(f"no .env.example found; looked in {[str(c) for c in candidates]}")


def _documented() -> dict[str, str]:
    """Every `NAME=value` in the template, commented out or not, last one wins."""
    found: dict[str, str] = {}
    for line in _template().splitlines():
        line = line.strip()
        if line.startswith("#"):
            line = line[1:].strip()
        if "=" not in line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        if name.isupper() and name.replace("_", "").isalnum():
            found[name] = value.strip()
    return found


def _normalize(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _normalize_text(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    return str(int(number)) if number.is_integer() else str(number)


def test_every_setting_is_documented() -> None:
    documented = _documented()
    missing = sorted(n.upper() for n in Settings.model_fields if n.upper() not in documented)
    assert not missing, (
        f"{len(missing)} Settings field(s) absent from .env.example: {missing}. "
        "An undocumented knob is one an operator cannot find."
    )


def test_documented_defaults_match_the_code() -> None:
    documented = _documented()
    wrong = []
    for name, field in Settings.model_fields.items():
        key = name.upper()
        if field.is_required() or key in ILLUSTRATIVE or field.default is None:
            continue
        shown = _normalize_text(documented[key])
        actual = _normalize(field.default)
        if shown != actual:
            wrong.append(f"{key}: .env.example says {shown!r}, config.py default is {actual!r}")
    assert not wrong, "\n".join(wrong)


def test_required_settings_are_uncommented() -> None:
    """A field with no default must be set, so its line cannot ship commented out."""
    live = {
        line.split("=", 1)[0]
        for line in _template().splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }
    required = {
        n.upper() for n, f in Settings.model_fields.items() if f.is_required()
    } | SENTINEL_REQUIRED
    assert required <= live, (
        f"required but only shown commented out: {sorted(required - live)}. "
        "A commented-out required variable reads as optional and the server won't boot."
    )


def test_illustrative_entries_still_have_an_empty_default() -> None:
    """If one of these gains a real default, it stops being an exception."""
    for key in ILLUSTRATIVE:
        field = Settings.model_fields[key.lower()]
        assert field.default == "", (
            f"{key} now defaults to {field.default!r}; drop it from ILLUSTRATIVE "
            "and document the real default."
        )
