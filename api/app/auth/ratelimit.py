"""Naive in-process per-user token bucket (DESIGN.md §1.4).

Limits are per API replica by design — coarse abuse control, not precise global
accounting (move to shared state only if that ever matters).
"""

import time


class TokenBucket:
    """Classic token bucket keyed by user id: `burst` capacity, `rate`/s refill."""

    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate
        self._burst = float(burst)
        self._buckets: dict[int, tuple[float, float]] = {}  # key -> (tokens, last)

    def allow(self, key: int) -> bool:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (self._burst, now))
        tokens = min(self._burst, tokens + (now - last) * self._rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[key] = (tokens, now)
        return allowed


class Cooldown:
    """Per-key minimum-spacing gate (in-process, per replica).

    ``allow(key, window_s)`` returns True at most once per ``window_s`` for a key —
    the abuse control behind manual feed refresh and feed discovery, where the cost
    is a server-side fetch rather than a cheap read.
    """

    def __init__(self) -> None:
        self._last: dict[int, float] = {}

    def allow(self, key: int, window_s: float) -> bool:
        now = time.monotonic()
        last = self._last.get(key)
        if last is not None and now - last < window_s:
            return False
        self._last[key] = now
        return True

    def reset(self) -> None:
        self._last.clear()
