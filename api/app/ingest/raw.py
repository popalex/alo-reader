"""Zstandard compression for ``entries.content_raw`` (re-sanitize insurance).

Pure, no I/O. We store ``zstd(original_html)`` so a future sanitizer bug can be
remediated by re-sanitizing the archived source instead of re-fetching every feed.
"""

import io

import zstandard

# Modest level: feed HTML is small and highly compressible; decompression cost and
# a bounded window matter more than squeezing the last few percent.
_LEVEL = 10
# Refuse to inflate without bound (zip-bomb guard on read-back).
_MAX_DECOMPRESS_BYTES = 64 * 1024 * 1024


def compress(data: bytes, *, level: int = _LEVEL) -> bytes:
    """Compress raw bytes."""
    return zstandard.ZstdCompressor(level=level).compress(data)


def decompress(data: bytes, *, max_output_size: int = _MAX_DECOMPRESS_BYTES) -> bytes:
    """Decompress bytes produced by :func:`compress`, capped to guard against bombs.

    The cap is enforced by streaming (not ``max_output_size=``, which zstd ignores
    when the frame declares its content size) so a crafted archive can't force an
    unbounded allocation.
    """
    reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data))
    out = reader.read(max_output_size + 1)
    if len(out) > max_output_size:
        raise zstandard.ZstdError(f"decompressed output exceeds {max_output_size} bytes")
    return out


def compress_text(text: str, *, level: int = _LEVEL) -> bytes:
    """Compress a UTF-8 string (convenience for HTML content)."""
    return compress(text.encode("utf-8"), level=level)


def decompress_text(data: bytes, *, max_output_size: int = _MAX_DECOMPRESS_BYTES) -> str:
    """Round-trip of :func:`compress_text`."""
    return decompress(data, max_output_size=max_output_size).decode("utf-8")
