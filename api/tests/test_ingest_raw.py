"""zstd compress/decompress round-trips for entries.content_raw."""

import pytest
import zstandard

from app.ingest import compress, compress_text, decompress, decompress_text


def test_bytes_roundtrip() -> None:
    data = b"\x00\x01\x02 hello \xff\xfe" * 100
    assert decompress(compress(data)) == data


def test_text_roundtrip_unicode() -> None:
    html = "<p>Café — smart “quotes” & <b>bold</b> 你好</p>" * 50
    assert decompress_text(compress_text(html)) == html


def test_empty() -> None:
    assert decompress(compress(b"")) == b""


def test_compression_actually_shrinks_repetitive_content() -> None:
    data = b"<p>Lorem ipsum dolor sit amet</p>" * 1000
    assert len(compress(data)) < len(data)


def test_decompress_rejects_oversize_bomb() -> None:
    # A tiny archive that inflates past the read cap must be refused, not OOM.
    bomb = zstandard.ZstdCompressor().compress(b"\x00" * (2 * 1024 * 1024))
    with pytest.raises(zstandard.ZstdError):
        decompress(bomb, max_output_size=1024)
