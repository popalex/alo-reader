"""API-process logging + per-request context.

The worker has its own structured logger; this is the API half: a module logger and
a request-id helper the error handler uses. ``RequestContextMiddleware`` assigns each
request an id (honoring an inbound ``X-Request-ID``) and echoes it on the response, so
a client error can be correlated with the server log line.
"""

import logging
import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("alo.api")

_HEADER = "x-request-id"


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
        inbound = Request(scope).headers.get(_HEADER)
        rid = inbound.strip() if inbound else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[_HEADER] = rid
            await send(message)

        await self.app(scope, receive, send_with_id)
