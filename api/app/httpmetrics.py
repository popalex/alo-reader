"""In-process HTTP request metrics (RED), rendered by /metrics.

Per-replica, in-memory counters — like the rate limiter, this is coarse per-instance
telemetry, not global accounting, and it avoids a DB write per request. The middleware
times each request and records its method + final status; /metrics exposes the totals
so request rate, error ratio, and average latency are visible alongside the worker and
DB gauges.
"""

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# (method, status) -> count, plus a running duration sum/count (avg = sum/count).
_requests: dict[tuple[str, int], int] = {}
_duration_sum_s: float = 0.0
_duration_count: int = 0

# The scrape itself shouldn't inflate the numbers it reports.
_SKIP_PATHS = frozenset({"/api/v1/metrics"})


def record(method: str, status: int, duration_s: float) -> None:
    global _duration_sum_s, _duration_count
    key = (method, status)
    _requests[key] = _requests.get(key, 0) + 1
    _duration_sum_s += duration_s
    _duration_count += 1


def snapshot_requests() -> list[tuple[str, int, int]]:
    """(method, status, count) triples, sorted for stable exposition."""
    return sorted((m, s, n) for (m, s), n in _requests.items())


def duration_totals() -> tuple[float, int]:
    return _duration_sum_s, _duration_count


def reset() -> None:
    """Clear all counters (test isolation only)."""
    global _duration_sum_s, _duration_count
    _requests.clear()
    _duration_sum_s = 0.0
    _duration_count = 0


class HttpMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500  # if the app never sends a start, it errored

        async def send_wrap(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrap)
        finally:
            record(scope["method"], status, time.perf_counter() - start)
