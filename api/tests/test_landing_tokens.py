"""The landing page copies its colours; this is what stops the copy rotting.

`deploy/landing/landing.html` is static HTML served by Caddy, outside the Vite
build, so it cannot link `tokens.css` — that file is content-hashed, and a <link>
would tie a marketing page to a build artefact's filename. It therefore restates
the token values, and a restatement that nobody checks drifts.

Same bargain as test_env_template.py: the duplicate is allowed to exist, it is not
allowed to disagree. Lives with the Python tests because they already read files
from the repo root (ALO_REPO_ROOT), where the web suite is fenced to web/.
"""

import os
import re
from pathlib import Path

import pytest

TOKENS_PATH = "web/src/styles/tokens.css"
LANDING_PATH = "deploy/landing/landing.html"

# The landing page renames two tokens for its own readability; every other name
# matches. Mapped rather than tolerated, so a genuine mismatch still fails.
ALIASES = {"--line": "--border", "--line-2": "--border-2"}


def _repo_file(relative: str) -> Path:
    root = os.getenv("ALO_REPO_ROOT")
    candidates = [Path(root) / relative] if root else []
    candidates.append(Path(__file__).resolve().parents[2] / relative)
    for path in candidates:
        if path.is_file():
            return path
    pytest.fail(f"{relative} not found; looked in {[str(c) for c in candidates]}")


def _block(text: str, selector: str) -> str:
    """The body of the first block opened by ``selector``, brace-matched.

    Brace matching rather than a search for a closing line: the landing page's CSS
    is indented inside <style>, so anything simpler runs past the block's end,
    swallows the ones after it, and compares the wrong theme's values.
    """
    start = text.index(selector)
    open_brace = text.index("{", start)
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace : i + 1]
    pytest.fail(f"unbalanced braces after {selector!r}")


def _vars(block: str) -> dict[str, str]:
    return {m[1]: m[2].strip() for m in re.finditer(r"(--[a-z0-9-]+):\s*([^;]+);", block)}


def _drift(landing_block: str, app_block: str) -> list[str]:
    app = _vars(app_block)
    out = []
    for name, value in _vars(landing_block).items():
        app_value = app.get(ALIASES.get(name, name))
        # Tokens the page declares for itself (its own font stack, say) have no
        # counterpart and are not drift.
        if app_value is not None and app_value != value:
            out.append(f"{name}: landing {value} != tokens.css {app_value}")
    return out


@pytest.fixture(scope="module")
def sources() -> tuple[str, str]:
    return (
        _repo_file(TOKENS_PATH).read_text(encoding="utf-8"),
        _repo_file(LANDING_PATH).read_text(encoding="utf-8"),
    )


def test_light_tokens_match(sources: tuple[str, str]) -> None:
    tokens, landing = sources
    assert _drift(_block(landing, ":root {"), _block(tokens, ":root {")) == []


def test_dark_tokens_match(sources: tuple[str, str]) -> None:
    tokens, landing = sources
    assert (
        _drift(
            _block(landing, "@media (prefers-color-scheme: dark)"),
            _block(tokens, ':root[data-theme="dark"] {'),
        )
        == []
    )


def test_the_landing_page_declares_the_tokens_it_uses(sources: tuple[str, str]) -> None:
    """A var() with no declaration renders as nothing, which is invisible in review."""
    _, landing = sources
    declared = set(_vars(_block(landing, ":root {")))
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", landing))
    assert used - declared == set()
