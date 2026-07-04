"""Pure ingest library: parse → sanitize → compress. No I/O, no DB.

The worker (WP-05) composes these; nothing here touches the network or database.
"""

from app.ingest.parse import ParsedEntry, ParsedFeed, parse_feed
from app.ingest.raw import compress, compress_text, decompress, decompress_text
from app.ingest.sanitize import sanitize_html, summarize, title_to_text

__all__ = [
    "ParsedEntry",
    "ParsedFeed",
    "parse_feed",
    "sanitize_html",
    "summarize",
    "title_to_text",
    "compress",
    "decompress",
    "compress_text",
    "decompress_text",
]
