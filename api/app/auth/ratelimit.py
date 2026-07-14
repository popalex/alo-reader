"""Naive in-process per-user token bucket (DESIGN.md §1.4).

Limits are per API replica by design — coarse abuse control, not precise global
accounting (move to shared state only if that ever matters).
"""

import time
from collections.abc import Hashable

# How often (seconds) either gate sweeps out idle keys. The maps are keyed by user
# id / feed id / client IP, so without eviction a long-lived replica accumulates one
# entry per distinct key ever seen. Pruning is behavior-preserving: a swept key is
# recreated on its next use in exactly the state it would have decayed to (see below).
_PRUNE_INTERVAL_S = 300.0


class TokenBucket:
    """Classic token bucket keyed by any hashable (user id or client IP): `burst`
    capacity, `rate`/s refill."""

    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate
        self._burst = float(burst)
        self._buckets: dict[Hashable, tuple[float, float]] = {}  # key -> (tokens, last)
        self._last_prune = time.monotonic()
        # A bucket untouched for this long has fully refilled to `burst`, so dropping
        # it is identical to keeping it (its next use recreates a full bucket).
        self._idle_ttl = burst / rate if rate > 0 else _PRUNE_INTERVAL_S

    def allow(self, key: Hashable) -> bool:
        now = time.monotonic()
        self._maybe_prune(now)
        tokens, last = self._buckets.get(key, (self._burst, now))
        tokens = min(self._burst, tokens + (now - last) * self._rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[key] = (tokens, now)
        return allowed

    def _maybe_prune(self, now: float) -> None:
        if now - self._last_prune < _PRUNE_INTERVAL_S:
            return
        self._last_prune = now
        ttl = self._idle_ttl
        self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < ttl}


class Cooldown:
    """Per-key minimum-spacing gate (in-process, per replica).

    ``allow(key, window_s)`` returns True at most once per ``window_s`` for a key —
    the abuse control behind manual feed refresh and feed discovery, where the cost
    is a server-side fetch rather than a cheap read.
    """

    def __init__(self) -> None:
        self._last: dict[int, float] = {}
        self._last_prune = time.monotonic()

    def allow(self, key: int, window_s: float) -> bool:
        now = time.monotonic()
        self._maybe_prune(now, window_s)
        last = self._last.get(key)
        if last is not None and now - last < window_s:
            return False
        self._last[key] = now
        return True

    def _maybe_prune(self, now: float, window_s: float) -> None:
        if now - self._last_prune < _PRUNE_INTERVAL_S:
            return
        self._last_prune = now
        # A key last seen more than `window_s` ago would be allowed anyway, so its
        # entry carries no state — forgetting it changes nothing.
        self._last = {k: t for k, t in self._last.items() if now - t < window_s}

    def reset(self) -> None:
        self._last.clear()
