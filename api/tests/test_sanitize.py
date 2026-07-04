"""Adversarial sanitizer tests (DESIGN.md §2 risk 2).

These call the sanitizer directly with raw hostile payloads (bypassing feedparser's
own scrubbing) and assert *exact* output — no script tag, event handler, or
non-http(s) scheme may survive, and links are forced safe.
"""

import pytest

from app.ingest import sanitize_html, summarize, title_to_text

# Tokens that must never appear in sanitized output, whatever the input.
_FORBIDDEN = [
    "<script",
    "javascript:",
    "vbscript:",
    "data:",
    "onerror",
    "onload",
    "onclick",
    "onmouseover",
    "<svg",
    "<iframe",
    "<style",
    "<object",
    "<embed",
]


def _assert_clean(out: str) -> None:
    low = out.lower()
    for token in _FORBIDDEN:
        assert token not in low, f"{token!r} survived in {out!r}"


def test_script_tag_and_content_removed() -> None:
    out = sanitize_html("<p>Before</p><script>alert(document.cookie)</script><p>After</p>")
    assert out == "<p>Before</p><p>After</p>"


def test_script_src_and_style_removed() -> None:
    out = sanitize_html('<div>a<script src="https://evil/x.js"></script>b<style>x{}</style>c</div>')
    assert out == "<div>abc</div>"
    _assert_clean(out)


def test_img_onerror_handler_stripped() -> None:
    out = sanitize_html('<img src="x" onerror="alert(1)" onload="y()">')
    assert out == '<img src="x">'


def test_event_handlers_on_various_tags() -> None:
    out = sanitize_html(
        '<a href="https://ok.example" onclick="steal()">l</a><div onmouseover="x()">h</div>'
    )
    assert out == (
        '<a href="https://ok.example" target="_blank" rel="noopener noreferrer">l</a><div>h</div>'
    )


@pytest.mark.parametrize(
    "scheme_url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
        "  javascript:alert(1)",
        "java\tscript:alert(1)",
    ],
)
def test_dangerous_link_schemes_stripped(scheme_url: str) -> None:
    out = sanitize_html(f'<a href="{scheme_url}">x</a>')
    _assert_clean(out)
    assert 'href="http' not in out  # no scheme smuggled through


def test_http_and_https_links_survive_with_forced_rel_and_target() -> None:
    out = sanitize_html('<a href="https://ok.example/p">ok</a>')
    assert out == '<a href="https://ok.example/p" target="_blank" rel="noopener noreferrer">ok</a>'


def test_data_uri_image_dropped() -> None:
    out = sanitize_html('<img src="data:image/svg+xml,<svg onload=alert(1)>" alt="p">')
    _assert_clean(out)
    assert "src=" not in out  # the data: src is removed, alt may remain


def test_svg_vectors_dropped_entirely() -> None:
    raw = (
        '<p>ok</p><svg xmlns="http://www.w3.org/2000/svg">'
        '<script>alert(1)</script><animate onbegin="alert(2)"/></svg><p>done</p>'
    )
    out = sanitize_html(raw)
    assert out == "<p>ok</p><p>done</p>"


def test_tracking_pixels_stripped() -> None:
    raw = (
        '<p>x</p><img src="https://t.example/p.gif" width="1" height="1">'
        '<img src="https://t.example/q.gif" width="0" height="0">'
        '<img src="https://cdn.example/real.png" width="600" height="400" alt="r">'
    )
    out = sanitize_html(raw)
    kept = '<img src="https://cdn.example/real.png" width="600" height="400" alt="r">'
    assert out == "<p>x</p>" + kept


def test_nested_and_malformed_obfuscation() -> None:
    # Classic filter-bypass: a broken/nested script tag must not reassemble.
    out = sanitize_html("<scr<script>ipt>alert(1)</scr</script>ipt>")
    _assert_clean(out)


def test_title_is_plain_text() -> None:
    assert (
        title_to_text("Breaking: <strong>Markets</strong> up 5% &amp; rising")
        == "Breaking: Markets up 5% & rising"
    )


def test_title_strips_script() -> None:
    assert "<script" not in title_to_text("hi <script>alert(1)</script>").lower()


def test_summarize_truncates_at_word_boundary() -> None:
    text = "word " * 200  # 1000 chars of "word "
    s = summarize("<p>" + text + "</p>")
    assert len(s) <= 301  # ~300 chars + ellipsis
    assert s.endswith("…")
    assert "word" in s and "  " not in s


def test_summarize_short_content_unchanged() -> None:
    assert summarize("<p>Short & sweet.</p>") == "Short & sweet."


def test_empty_inputs() -> None:
    assert sanitize_html("") == ""
    assert title_to_text("") == ""
    assert summarize("") == ""
