"""Golden-file tests over the append-only feed fixture corpus (DESIGN.md §2 risk 1).

Every fixture in ``fixtures/feeds/`` is parsed + sanitized + summarized with a fixed
reference clock and compared against a checked-in golden JSON. Regenerate after an
intentional change with::

    python -m tests.test_ingest_golden --update

Also covers: the GUID fallback chain is deterministic and non-empty for every entry,
and parsing touches the network zero times.
"""

import hashlib
import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.ingest import parse_feed, sanitize_html, summarize

FEEDS_DIR = Path(__file__).parent / "fixtures" / "feeds"
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"

# Fixed clock so future-date rejection and any date normalization are deterministic.
REFERENCE_NOW = datetime(2026, 7, 4, 0, 0, 0, tzinfo=UTC)

# Above this, the golden stores a hash instead of the full body (keeps the enormous
# fixture's golden compact while small/adversarial goldens stay fully reviewable).
_INLINE_LIMIT = 4000


def _fixture_paths() -> list[Path]:
    return sorted(FEEDS_DIR.glob("*.xml"))


def _entry_golden(content_html: str, summary: str, entry: Any) -> dict[str, Any]:
    sanitized = sanitize_html(content_html)
    g: dict[str, Any] = {
        "guid_hash": entry.guid_hash.hex(),
        "guid_source": entry.guid_source,
        "url": entry.url,
        "title": entry.title,
        "author": entry.author,
        "published_at": entry.published_at.isoformat() if entry.published_at else None,
        "content_html_len": len(sanitized),
        "summary": summary,
    }
    if len(sanitized) <= _INLINE_LIMIT:
        g["content_html"] = sanitized
    else:
        g["content_html_sha256"] = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
        g["content_html_head"] = sanitized[:200]
    return g


def build_golden(raw: bytes) -> dict[str, Any]:
    """Deterministic parse → sanitize → summarize snapshot of one feed."""
    pf = parse_feed(raw, now=REFERENCE_NOW)
    return {
        "feed": {
            "title": pf.title,
            "site_url": pf.site_url,
            "version": pf.version,
            "bozo": pf.bozo,
            "encoding": pf.encoding,
            "entry_count": len(pf.entries),
        },
        "entries": [
            _entry_golden(e.content_html, summarize(e.content_html), e) for e in pf.entries
        ],
    }


def _golden_path(fixture: Path) -> Path:
    return GOLDEN_DIR / f"{fixture.stem}.json"


@pytest.fixture
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if parsing ever opens a socket (parse must be pure/offline)."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted during ingest parsing")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


@pytest.mark.parametrize("fixture", _fixture_paths(), ids=lambda p: p.stem)
def test_golden(fixture: Path, _no_network: None) -> None:
    golden_path = _golden_path(fixture)
    assert golden_path.exists(), f"missing golden for {fixture.name}; run --update"
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    actual = build_golden(fixture.read_bytes())
    assert actual == expected


@pytest.mark.parametrize("fixture", _fixture_paths(), ids=lambda p: p.stem)
def test_guid_chain_deterministic_and_nonempty(fixture: Path) -> None:
    raw = fixture.read_bytes()
    first = parse_feed(raw, now=REFERENCE_NOW)
    second = parse_feed(raw, now=REFERENCE_NOW)
    for a, b in zip(first.entries, second.entries, strict=True):
        assert a.guid_hash == b.guid_hash  # deterministic
        assert len(a.guid_hash) == 32  # sha256 digest, always present
        assert a.guid_source in {"guid", "link", "synthetic"}


def _update_goldens() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for fixture in _fixture_paths():
        golden = build_golden(fixture.read_bytes())
        _golden_path(fixture).write_text(
            json.dumps(golden, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote golden for {fixture.name}")


if __name__ == "__main__":
    import sys

    if "--update" in sys.argv:
        _update_goldens()
    else:
        print("pass --update to regenerate golden files")
