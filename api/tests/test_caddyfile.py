"""The Caddyfiles, read as text: placeholders Caddy does not know pass through as literal
strings, silently.

From 2026-07-14 until this test, the edge sent ``X-Real-IP: {http.request.client_ip}``,
which is not a Caddy placeholder, so every request carried that same literal string and
the API's per-IP rate limit keyed every client to one bucket. Nothing failed, and no
log looked wrong. Caddy's resolved client address is ``{client_ip}`` (shorthand for
``{http.vars.client_ip}``).

Lives in the API suite because the per-IP limiter it protects is the API's, and the repo
root is mounted for exactly this kind of cross-tree check (ALO_REPO_ROOT).
"""

import os
import re
from pathlib import Path

import pytest

CADDYFILES = ("deploy/Caddyfile", "deploy/Caddyfile.dev")

# Every placeholder the Caddyfiles use today, checked against Caddy's documentation.
# A new one goes here only after confirming Caddy expands it (a quick reverse_proxy to
# an echo server will show the literal string if it does not).
KNOWN_PLACEHOLDERS = {"{client_ip}", "{host}", "{path}", "{uri}"}


def _repo_file(relative: str) -> Path:
    root = os.getenv("ALO_REPO_ROOT")
    candidates = [Path(root) / relative] if root else []
    candidates.append(Path(__file__).resolve().parents[2] / relative)
    for path in candidates:
        if path.is_file():
            return path
    pytest.fail(f"{relative} not found; looked in {[str(c) for c in candidates]}")


def _placeholders(text: str) -> set[str]:
    # {$ENV:default} is environment substitution at parse time, not a placeholder.
    without_comments = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return {m for m in re.findall(r"\{[^{}\s$]+\}", without_comments)}


@pytest.mark.parametrize("relative", CADDYFILES)
def test_only_known_placeholders(relative: str) -> None:
    unknown = _placeholders(_repo_file(relative).read_text()) - KNOWN_PLACEHOLDERS
    assert not unknown, (
        f"{relative} uses placeholders not in KNOWN_PLACEHOLDERS: {sorted(unknown)}. "
        "Caddy leaves an unknown placeholder as literal text; confirm it expands first."
    )


def test_api_gets_the_resolved_client_address() -> None:
    """The per-IP rate limit reads X-Real-IP (auth/middleware.py). It must carry the
    client Caddy resolved, which honours trusted_proxies, and not a literal string."""
    text = _repo_file("deploy/Caddyfile").read_text()
    assert re.search(r"^\s*header_up X-Real-IP \{client_ip\}\s*$", text, re.M)
