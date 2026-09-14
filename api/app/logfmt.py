"""logfmt encoding for the structured lines the api and the worker log.

Loki parses these with ``| logfmt``, which needs a value quoted once it contains a
space, an ``=`` or a quote. Exception reprs contain all three. ``repr(exc)`` renders as
``ValueError('connection reset by peer')``, so an unquoted emitter corrupts exactly the
lines an operator greps during an incident, splitting one value into four tokens.
"""

from collections.abc import Mapping

# Only what a logfmt reader has to un-escape inside a quoted value. Newlines matter
# most, because an un-escaped one splits a single log record into two lines.
_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"})

# A bare value ends at the next space, so anything that could be read as structure,
# or is unprintable, or is empty, has to be quoted.
_NEEDS_QUOTING = ' "=\\'


def quote(value: object) -> str:
    """Render one value: bare when it is unambiguous, quoted and escaped when it is not."""
    text = str(value)
    if text and text.isprintable() and not any(ch in text for ch in _NEEDS_QUOTING):
        return text
    return f'"{text.translate(_ESCAPES)}"'


def pairs(fields: Mapping[str, object]) -> str:
    """Render ``key=value`` pairs, space-separated."""
    return " ".join(f"{k}={quote(v)}" for k, v in fields.items())


def line(event: str, **fields: object) -> str:
    """Render a full ``event key=value …`` line, or just ``event`` when there are no fields."""
    tail = pairs(fields)
    return f"{event} {tail}" if tail else event
