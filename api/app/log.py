"""API-process logging + per-request context.

The worker has its own structured logger; this is the API half: a module logger and
a request-id helper the error handler uses. ``RequestContextMiddleware`` assigns each
request an id (honoring an inbound ``X-Request-ID``) and echoes it on the response, so
a client error can be correlated with the server log line.
"""

import logging
import re
import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("alo.api")

_HEADER = "x-request-id"


# An inbound id is echoed on the response and written into logs, so it is bounded
# and restricted to the shape ids actually come in: a hex uuid, a ULID, a trace id.
_MAX_REQUEST_ID = 128
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def _clean_request_id(value: str | None) -> str | None:
    """An acceptable inbound request id, or None to generate a fresh one.

    A whitespace-only header used to strip to "", which is falsy only *after* the
    truthiness check that guarded it, so the response carried an empty
    X-Request-ID and the logs said request_id="".
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > _MAX_REQUEST_ID:
        return None
    return candidate if _REQUEST_ID_RE.match(candidate) else None


def request_id(request: Request) -> str:
    """The current request's id, or ``"-"`` if the middleware didn't run."""
    return getattr(request.state, "request_id", "-")


class RequestContextMiddleware:
    """Assign/propagate an ``X-Request-ID`` for every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = _clean_request_id(Request(scope).headers.get(_HEADER)) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[_HEADER] = rid
            await send(message)

        await self.app(scope, receive, send_with_id)
