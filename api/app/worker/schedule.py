"""Adaptive poll-interval and error-backoff math (DESIGN.md §1.3).

Pure functions, no clock and no I/O, so the scheduling policy is unit-testable in
isolation. Bounds are passed in by the caller (from config) rather than hardcoded.
"""


def adaptive_interval(current_s: int, got_new_items: bool, *, floor_s: int, ceil_s: int) -> int:
    """Next poll interval for a successful fetch.

    Active feeds (new items) tighten toward ``floor_s`` by halving; quiet feeds
    relax toward ``ceil_s`` by growing 1.5×. The result is always within bounds.
    """
    if got_new_items:
        nxt = current_s // 2
    else:
        nxt = int(current_s * 3 // 2)
    return max(floor_s, min(ceil_s, nxt))


def backoff_interval(error_count: int, *, base_s: int, cap_s: int) -> int:
    """Delay before the next attempt after ``error_count`` consecutive errors.

    Exponential (``base_s`` doubled per error) clamped to ``cap_s``. ``error_count``
    is the post-increment count, so the first error waits ``base_s``.
    """
    if error_count <= 0:
        return base_s
    # Cap the shift so 2**n can't overflow into a huge int before the min().
    shift = min(error_count - 1, 32)
    return min(cap_s, base_s * (2**shift))


def error_delay(error_count: int, retry_after_s: float | None, *, base_s: int, cap_s: int) -> int:
    """Backoff for a failed poll, never shorter than a server ``Retry-After``."""
    delay = backoff_interval(error_count, base_s=base_s, cap_s=cap_s)
    if retry_after_s is not None:
        delay = max(delay, int(retry_after_s))
    return min(cap_s, delay)
