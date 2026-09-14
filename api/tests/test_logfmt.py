"""logfmt encoding: the emitted line must survive a logfmt parser.

The regression these guard is not cosmetic. Values were interpolated raw, so
``error=repr(exc)`` parsed as one truncated value plus three dangling tokens, and a
value containing a newline split the record in two. Exception reprs are the values most
likely to hold a space, and exception lines are the ones an operator greps first.
"""

import logging

import pytest

from app.logfmt import line, pairs, quote
from app.worker.log import emit


def parse_logfmt(text: str) -> dict[str, str]:
    """A minimal logfmt reader, standing in for Loki's ``| logfmt``.

    Bare keys, such as the leading event name, map to ``""``. Loki's parser does the
    same with them.
    """
    out: dict[str, str] = {}
    i = 0
    while i < len(text):
        if text[i] == " ":
            i += 1
            continue
        end = text.find(" ", i)
        eq = text.find("=", i)
        if eq < 0 or (end >= 0 and end < eq):  # a bare token, no value
            stop = len(text) if end < 0 else end
            out[text[i:stop]] = ""
            i = stop
            continue
        key = text[i:eq]
        i = eq + 1
        if i < len(text) and text[i] == '"':
            i += 1
            buf: list[str] = []
            while text[i] != '"':
                if text[i] == "\\":
                    i += 1
                    buf.append({"n": "\n", "r": "\r", "t": "\t"}.get(text[i], text[i]))
                else:
                    buf.append(text[i])
                i += 1
            out[key] = "".join(buf)
            i += 1
        else:
            stop = text.find(" ", i)
            stop = len(text) if stop < 0 else stop
            out[key] = text[i:stop]
            i = stop
    return out


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        "",
        "has space",
        'has "quotes"',
        "has=equals",
        "back\\slash",
        "multi\nline",
        "tab\tbed",
        "ValueError('connection reset by peer')",
        "café",  # printable non-ASCII stays bare
    ],
)
def test_value_round_trips(value: str) -> None:
    parsed = parse_logfmt(line("some_event", key=value))
    assert parsed["key"] == value
    assert "some_event" in parsed


def test_unambiguous_values_stay_unquoted() -> None:
    # Quoting everything would be correct but unreadable in `docker compose logs`,
    # which is the default interface for a self-hoster running with OTel off.
    assert quote("plain") == "plain"
    assert quote(42) == "42"
    assert quote("café") == "café"
    assert quote("") == '""'


def test_pairs_and_line_shapes() -> None:
    assert pairs({"a": 1, "b": "two"}) == "a=1 b=two"
    assert line("event_only") == "event_only"
    assert line("event", n=1) == "event n=1"


def test_exception_repr_keeps_its_neighbours(caplog: pytest.LogCaptureFixture) -> None:
    """The real shape: an event, an id, and an exception whose message has spaces."""
    with caplog.at_level(logging.INFO, logger="worker"):
        emit("feed_failed", feed_id=7, error=repr(ValueError("connection reset by peer")))
    parsed = parse_logfmt(caplog.records[-1].getMessage())
    assert parsed["feed_id"] == "7"
    assert parsed["error"] == "ValueError('connection reset by peer')"
    assert "feed_failed" in parsed


def test_newline_in_a_value_stays_on_one_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="worker"):
        emit("orphan_gc_failed", error="first line\nsecond line")
    message = caplog.records[-1].getMessage()
    assert "\n" not in message
    assert parse_logfmt(message)["error"] == "first line\nsecond line"
