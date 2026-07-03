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
