"""Build version, stamped into the image at build time.

Read straight from the environment rather than through Settings. /healthz has to
answer without a database or an identity (see auth.middleware.PUBLIC_PATHS), and
Settings requires DATABASE_URL, so importing the app for a test or for the openapi
dump must not depend on one. Same reasoning as the OTEL_ENABLED gate in main.

Set by deploy/Dockerfile.api via --build-arg APP_VERSION. Unset means a local build,
which is what the default says.
"""

import os

APP_VERSION: str = os.getenv("APP_VERSION", "").strip() or "0.0.0+dev"
