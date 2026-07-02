"""Stream identifier parsing, shared by the store and (later) the HTTP layer.

A stream is one of: ``all`` | ``starred`` | ``feed/{id}`` | ``folder/{id}``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Stream:
    kind: str  # "all" | "starred" | "feed" | "folder"
    ref_id: int | None = None


def parse_stream(stream: str) -> Stream:
    if stream in ("all", "starred"):
        return Stream(stream)
    for prefix, kind in (("feed/", "feed"), ("folder/", "folder")):
        if stream.startswith(prefix):
            rest = stream[len(prefix) :]
            if not rest.isdigit():
                raise ValueError(f"invalid stream ref: {stream!r}")
            return Stream(kind, int(rest))
    raise ValueError(f"invalid stream: {stream!r}")
