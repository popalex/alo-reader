"""HTML sanitization and text extraction for ingested feed content.

All feed content is hostile input. Sanitization happens once, here, at ingest
(DESIGN.md §1.6): an nh3 (Rust ``ammonia``) allowlist is the first wall; the SPA's
CSP is the second. Titles are never HTML — they are reduced to plain text.

Pure functions, no I/O. The policy is intentionally explicit (not nh3's defaults)
so the allowlist is auditable and adversarial tests can assert exact output.
"""

import html
import re

import nh3

# ── Allowlist policy ─────────────────────────────────────────────────────────
# Structural + inline article markup only. No script/style/iframe/object/embed/
# form/svg/math/link/meta/base — none of these appear here, so they (and their
# content, for the raw-text-bearing ones) are stripped.
ALLOWED_TAGS: set[str] = {
    "a",
    "abbr",
    "acronym",
    "address",
    "article",
    "aside",
    "b",
    "bdi",
    "bdo",
    "blockquote",
    "br",
    "caption",
    "cite",
    "code",
    "col",
    "colgroup",
    "data",
    "dd",
    "del",
    "details",
    "dfn",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "i",
    "img",
    "ins",
    "kbd",
    "li",
    "main",
    "mark",
    "nav",
    "ol",
    "p",
    "pre",
    "q",
    "rp",
    "rt",
    "ruby",
    "s",
    "samp",
    "section",
    "small",
    "span",
    "strike",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "time",
    "tr",
    "u",
    "ul",
    "var",
    "wbr",
}

ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"dir", "lang", "title"},
    "a": {"href", "hreflang"},
    "img": {"src", "alt", "width", "height"},
    "col": {"span"},
    "colgroup": {"span"},
    "ol": {"start", "reversed", "type"},
    "td": {"colspan", "rowspan", "headers"},
    "th": {"colspan", "rowspan", "scope", "headers", "abbr"},
    "time": {"datetime"},
    "data": {"value"},
}

# Only real web schemes; strips javascript:/data:/vbscript:/file: etc.
ALLOWED_SCHEMES: set[str] = {"http", "https"}

# Content of these is discarded entirely (not just the tag), so scripted text
# never leaks into stored HTML even if a browser were to re-parse it.
_CLEAN_CONTENT_TAGS: set[str] = {"script", "style", "template", "noscript"}

# Force safe link behavior: no referrer/opener leak, open off-site.
_LINK_REL = "noopener noreferrer"
_LINK_ATTR_VALUES = {"a": {"target": "_blank"}}

# Tracking pixels: 1×1 (or 0×0) images. nh3 normalizes attrs to double quotes and
# lowercases tag names, so this runs over trusted, well-formed output.
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_WIDTH_RE = re.compile(r'\bwidth="(\d+)"', re.IGNORECASE)
_HEIGHT_RE = re.compile(r'\bheight="(\d+)"', re.IGNORECASE)

# Any run of whitespace collapses to a single space in extracted text.
_WS_RE = re.compile(r"\s+")

# Entry-content cost ceiling (DESIGN.md §1.4): store roughly the first 500 KB.
MAX_CONTENT_CHARS = 500_000
# Summaries are a short lead-in for the list view.
SUMMARY_CHARS = 300


def _drop_tracking_pixels(safe_html: str) -> str:
    def repl(m: re.Match[str]) -> str:
        tag = m.group(0)
        w = _WIDTH_RE.search(tag)
        h = _HEIGHT_RE.search(tag)
        if w and h and int(w.group(1)) <= 1 and int(h.group(1)) <= 1:
            return ""
        return tag

    return _IMG_TAG_RE.sub(repl, safe_html)


def sanitize_html(raw_html: str) -> str:
    """Return an allowlist-sanitized copy of ``raw_html`` safe to render.

    Enforces: tag/attribute allowlist, http/https-only URLs, forced
    ``rel="noopener noreferrer" target="_blank"`` on links, script/style content
    removal, and tracking-pixel stripping. Output is capped at
    :data:`MAX_CONTENT_CHARS`.
    """
    if not raw_html:
        return ""
    cleaned = nh3.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        clean_content_tags=_CLEAN_CONTENT_TAGS,
        url_schemes=ALLOWED_SCHEMES,
        link_rel=_LINK_REL,
        set_tag_attribute_values=_LINK_ATTR_VALUES,
    )
    cleaned = _drop_tracking_pixels(cleaned)
    if len(cleaned) > MAX_CONTENT_CHARS:
        cleaned = cleaned[:MAX_CONTENT_CHARS]
    return cleaned


def _strip_to_text(raw_html: str) -> str:
    """Strip all markup and collapse whitespace, yielding plain text."""
    if not raw_html:
        return ""
    # tags=set() removes every tag but keeps text; drop scripted content wholesale.
    stripped = nh3.clean(raw_html, tags=set(), clean_content_tags=_CLEAN_CONTENT_TAGS)
    # nh3 re-escapes entities; decode so callers get real text, then normalize WS.
    text = html.unescape(stripped)
    return _WS_RE.sub(" ", text).strip()


def title_to_text(raw_title: str) -> str:
    """Reduce a (possibly HTML-bearing) title to plain text. Titles are never HTML."""
    return _strip_to_text(raw_title)


def summarize(raw_html: str, *, limit: int = SUMMARY_CHARS) -> str:
    """First ``~limit`` characters of the stripped text, trimmed at a word boundary."""
    text = _strip_to_text(raw_html)
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    # Avoid cutting mid-word when a boundary is reasonably close to the end.
    cut = clipped.rfind(" ")
    if cut >= limit // 2:
        clipped = clipped[:cut]
    return clipped.rstrip() + "…"
