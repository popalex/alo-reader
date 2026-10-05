"""Every var() in the app's stylesheets names a custom property something declares.

An undeclared var() renders as nothing: no border, or a fallback colour meant for
the other theme. Review doesn't catch it and neither does the build. The welcome
screen shipped with --line/--line-2 (the landing page's names), so its cards had no
borders, and the crashed-pane button asked for --accent-fg and got white text on the
dark accent.

Lives with the Python tests for the reason test_landing_tokens.py does: they read
files from the repo root, and the web unit tests have no Node fs.
"""

import os
import re
from pathlib import Path

import pytest

WEB_SRC = "web/src"


def _web_src() -> Path:
    root = os.getenv("ALO_REPO_ROOT")
    candidates = [Path(root) / WEB_SRC] if root else []
    candidates.append(Path(__file__).resolve().parents[2] / WEB_SRC)
    for path in candidates:
        if path.is_dir():
            return path
    pytest.fail(f"{WEB_SRC} not found; looked in {[str(c) for c in candidates]}")


def test_every_var_is_declared() -> None:
    src = _web_src()
    sheets = {
        p.relative_to(src).as_posix(): p.read_text(encoding="utf-8") for p in src.rglob("*.css")
    }
    assert len(sheets) > 10, "found too few stylesheets to trust the check"
    declared = {m[1] for css in sheets.values() for m in re.finditer(r"(--[\w-]+)\s*:", css)}
    missing = sorted(
        f"{name}: {m[1]}"
        for name, css in sheets.items()
        for m in re.finditer(r"var\(\s*(--[\w-]+)", css)
        if m[1] not in declared
    )
    assert missing == []
