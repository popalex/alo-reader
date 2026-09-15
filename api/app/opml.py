"""OPML build/parse — pure functions over stdlib ElementTree (DESIGN.md §5).

Export nests feeds under one level of folder outlines; import flattens each feed to
its nearest named ancestor outline. Untrusted uploads are guarded by the caller
(size cap + entity-declaration rejection); ElementTree never fetches external refs.
"""

import re
from dataclasses import dataclass
from typing import cast
from xml.etree import ElementTree
from xml.parsers import expat


@dataclass(frozen=True)
class OpmlFeed:
    title: str
    xml_url: str
    html_url: str | None = None
    folder: str | None = None


# XML 1.0 forbids the C0 controls except tab, newline and carriage return, and
# ElementTree escapes none of them: a feed title carrying \x0c produced an export no
# parser would read back, including our own import.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _xml_safe(value: str) -> str:
    return _CONTROL_CHARS.sub("", value)


def build_opml(title: str, groups: list[tuple[str | None, list[OpmlFeed]]]) -> bytes:
    """Serialize grouped feeds to OPML 2.0. ``groups`` is an ordered list of
    ``(folder_name_or_None, feeds)``; the ``None`` group holds uncategorized feeds."""
    opml = ElementTree.Element("opml", version="2.0")
    head = ElementTree.SubElement(opml, "head")
    ElementTree.SubElement(head, "title").text = _xml_safe(title)
    body = ElementTree.SubElement(opml, "body")
    for folder_name, feeds in groups:
        parent = body
        if folder_name is not None:
            safe_name = _xml_safe(folder_name)
            parent = ElementTree.SubElement(body, "outline", text=safe_name, title=safe_name)
        for f in feeds:
            safe_title = _xml_safe(f.title)
            attrs = {
                "type": "rss",
                "text": safe_title,
                "title": safe_title,
                "xmlUrl": _xml_safe(f.xml_url),
            }
            if f.html_url:
                attrs["htmlUrl"] = _xml_safe(f.html_url)
            ElementTree.SubElement(parent, "outline", attrs)
    # typeshed types this overload as Any; it is bytes for any encoding but "unicode".
    return cast(bytes, ElementTree.tostring(opml, encoding="utf-8", xml_declaration=True))


class OpmlEntityError(ValueError):
    """The document carries a DTD. Callers reject it rather than expand it."""


class _NoDoctype(Exception):
    """Internal: stop the pre-scan at the first element, the DTD is behind us."""


def reject_dtd(data: bytes) -> None:
    """Raise :class:`OpmlEntityError` if the document declares a DTD.

    Expat decides the encoding from the BOM or the XML declaration, so this runs as
    a real parse rather than a byte scan: a UTF-16 document sails straight past a
    search for b"<!ENTITY" and then expands normally, and a nested-entity bomb inside
    the 1 MiB upload cap expands to gigabytes. The scan stops at the first element,
    which is past the DTD and before any content, so it costs a few hundred bytes of
    parsing rather than a second pass over the document.

    Malformed XML is left alone here; parse_opml raises the ParseError the caller
    already handles.
    """

    def start_doctype(*_args: object) -> None:
        raise OpmlEntityError("OPML with a document type declaration is not allowed")

    def start_element(*_args: object) -> None:
        raise _NoDoctype

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = start_doctype
    parser.StartElementHandler = start_element
    try:
        parser.Parse(data, True)
    except _NoDoctype:
        return
    except expat.ExpatError:
        return  # malformed: parse_opml raises ParseError, which the route reports as 400


def parse_opml(data: bytes) -> list[OpmlFeed]:
    """Flatten an OPML document to a list of feeds, each tagged with its nearest
    named folder.

    Raises ``ElementTree.ParseError`` on malformed XML and :class:`OpmlEntityError`
    on a document carrying a DTD (see :func:`reject_dtd`).
    """
    reject_dtd(data)
    root = ElementTree.fromstring(data)
    body = root.find("body")
    feeds: list[OpmlFeed] = []
    if body is None:
        return feeds

    # Iterative, with an explicit stack: a recursive walk blows the interpreter's
    # stack at a few thousand nested outlines, which is a ~84 KB file, and the
    # RecursionError surfaces as a 500 rather than a rejected upload.
    stack: list[tuple[ElementTree.Element, str | None]] = [(body, None)]
    while stack:
        element, folder = stack.pop()
        for outline in reversed(element.findall("outline")):
            xml_url = outline.get("xmlUrl")
            text = outline.get("text") or outline.get("title") or ""
            if xml_url:
                feeds.append(
                    OpmlFeed(
                        title=text or xml_url,
                        xml_url=xml_url,
                        html_url=outline.get("htmlUrl"),
                        folder=folder,
                    )
                )
            else:
                # A category/folder outline; its descendants inherit its name.
                stack.append((outline, text or folder))
    return feeds
