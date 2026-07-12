"""Security response headers for the API (WP-15, DESIGN.md §1.6).

The API only ever returns JSON (or, for /icons, an image) — it never sources
scripts, styles, or frames — so its CSP is the tightest possible: ``default-src
'none'``. The SPA's own (looser) CSP that has to accommodate Clerk + feed images is
set at the edge in the Caddyfile; this module is the API half and the single source
of truth the header-audit test asserts against.

Added as an outer ASGI middleware so the headers land on *every* response, including
the auth middleware's 401/429 and framework error envelopes.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The exact, audited header set. The test in test_security_headers.py asserts an API
# response carries precisely these — add/rename here and the test moves with it.
SECURITY_HEADERS: dict[str, str] = {
    # API responses reference no resources at all.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), browsing-topics=()",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers[key] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
