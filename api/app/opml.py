"""OPML build/parse — pure functions over stdlib ElementTree (DESIGN.md §5).

Export nests feeds under one level of folder outlines; import flattens each feed to
its nearest named ancestor outline. Untrusted uploads are guarded by the caller
(size cap + entity-declaration rejection); ElementTree never fetches external refs.
"""

from dataclasses import dataclass
from xml.etree import ElementTree


@dataclass(frozen=True)
class OpmlFeed:
    title: str
    xml_url: str
    html_url: str | None = None
    folder: str | None = None


def build_opml(title: str, groups: list[tuple[str | None, list[OpmlFeed]]]) -> bytes:
    """Serialize grouped feeds to OPML 2.0. ``groups`` is an ordered list of
    ``(folder_name_or_None, feeds)``; the ``None`` group holds uncategorized feeds."""
    opml = ElementTree.Element("opml", version="2.0")
    head = ElementTree.SubElement(opml, "head")
    ElementTree.SubElement(head, "title").text = title
    body = ElementTree.SubElement(opml, "body")
    for folder_name, feeds in groups:
        parent = body
        if folder_name is not None:
            parent = ElementTree.SubElement(body, "outline", text=folder_name, title=folder_name)
        for f in feeds:
            attrs = {"type": "rss", "text": f.title, "title": f.title, "xmlUrl": f.xml_url}
            if f.html_url:
                attrs["htmlUrl"] = f.html_url
            ElementTree.SubElement(parent, "outline", attrs)
    return ElementTree.tostring(opml, encoding="utf-8", xml_declaration=True)


def parse_opml(data: bytes) -> list[OpmlFeed]:
    """Flatten an OPML document to a list of feeds, each tagged with its nearest
    named folder. Raises ``ElementTree.ParseError`` on malformed XML."""
    root = ElementTree.fromstring(data)
    body = root.find("body")
    feeds: list[OpmlFeed] = []
    if body is None:
        return feeds

    def walk(element: ElementTree.Element, folder: str | None) -> None:
        for outline in element.findall("outline"):
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
                walk(outline, text or folder)

    walk(body, None)
    return feeds
