"""Adaptive-interval and backoff math (DESIGN.md §1.3) — pure, no DB."""

from app.worker.schedule import adaptive_interval, backoff_interval, error_delay

FLOOR, CEIL = 900, 86_400


def test_new_items_halve_toward_floor() -> None:
    assert adaptive_interval(3600, True, floor_s=FLOOR, ceil_s=CEIL) == 1800
    assert adaptive_interval(1800, True, floor_s=FLOOR, ceil_s=CEIL) == 900
    # Never below the floor.
    assert adaptive_interval(1000, True, floor_s=FLOOR, ceil_s=CEIL) == 900


def test_no_items_grow_toward_ceiling() -> None:
    assert adaptive_interval(3600, False, floor_s=FLOOR, ceil_s=CEIL) == 5400
    assert adaptive_interval(60_000, False, floor_s=FLOOR, ceil_s=CEIL) == 86_400  # capped
    assert adaptive_interval(86_400, False, floor_s=FLOOR, ceil_s=CEIL) == 86_400


def test_backoff_doubles_and_caps() -> None:
    assert backoff_interval(1, base_s=900, cap_s=86_400) == 900
    assert backoff_interval(2, base_s=900, cap_s=86_400) == 1800
    assert backoff_interval(3, base_s=900, cap_s=86_400) == 3600
    assert backoff_interval(10, base_s=900, cap_s=86_400) == 86_400  # capped at 24h
    assert backoff_interval(0, base_s=900, cap_s=86_400) == 900


def test_backoff_configurable_base_cap() -> None:
    assert backoff_interval(1, base_s=60, cap_s=600) == 60
    assert backoff_interval(4, base_s=60, cap_s=600) == 480
    assert backoff_interval(5, base_s=60, cap_s=600) == 600  # cap wins


def test_error_delay_honors_retry_after() -> None:
    # Server Retry-After longer than computed backoff wins...
    assert error_delay(1, 3000.0, base_s=900, cap_s=86_400) == 3000
    # ...but backoff wins when it is the larger of the two.
    assert error_delay(3, 10.0, base_s=900, cap_s=86_400) == 3600
    # No Retry-After → plain backoff.
    assert error_delay(2, None, base_s=900, cap_s=86_400) == 1800
    # Still clamped to the cap even if Retry-After is absurd.
    assert error_delay(1, 999_999.0, base_s=900, cap_s=86_400) == 86_400
