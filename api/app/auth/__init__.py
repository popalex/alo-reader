"""Auth package — the only place allowed to know about the auth vendor.

Public surface for the rest of the app: the ``current_user`` dependency, the
``AuthedUser`` identity, the ASGI ``AuthMiddleware``, and the routes router.
"""

from .middleware import AuthMiddleware
from .provider import AuthedUser
from .routes import router
from .runtime import current_user

__all__ = ["AuthMiddleware", "AuthedUser", "current_user", "router"]
