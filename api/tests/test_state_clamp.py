"""The changed_at clamp (routes/entries): a client-supplied LWW timestamp is bounded
to now + a small skew so a far-future value can't pin a state against later writes."""

from datetime import UTC, datetime, timedelta

from app.routes.entries import _clamp_changed_at

NOW = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_none_becomes_now() -> None:
    assert _clamp_changed_at(None, now=NOW) == NOW


def test_past_and_near_future_pass_through() -> None:
    past = NOW - timedelta(days=1)
    near = NOW + timedelta(minutes=1)
    assert _clamp_changed_at(past, now=NOW) == past
    assert _clamp_changed_at(near, now=NOW) == near


def test_far_future_is_clamped() -> None:
    far = NOW + timedelta(days=3650)
    assert _clamp_changed_at(far, now=NOW) == NOW + timedelta(minutes=5)


def test_naive_is_treated_as_utc() -> None:
    naive = datetime(2024, 1, 1, 11, 0)  # noqa: DTZ001 — intentionally naive input
    assert _clamp_changed_at(naive, now=NOW) == NOW - timedelta(hours=1)
