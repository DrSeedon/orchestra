"""Find links in markdown and HTML documents."""
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

MARKDOWN_LINK = re.compile(r'!?\[[^\]]*\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)')
REFERENCE_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)")
AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
FENCE = "```"
LINK_ATTRIBUTES = {"a": "href", "link": "href", "img": "src", "script": "src"}


@dataclass(frozen=True)
class Link:
    """A link target found in a document.

    :param source: the document that contains the link.
    :param line: 1-based line number of the link.
    :param target: the link target exactly as written.
    """

    source: Path
    line: int
    target: str


def extract_markdown_links(text: str, source: Path) -> list[Link]:
    """Return the inline, reference and autolink targets of a markdown text.

    Links inside fenced code blocks are ignored.

    :param text: markdown source.
    :param source: path of the document, stored on each link.
    :returns: links in document order.
    """
    links = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(FENCE):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        targets = MARKDOWN_LINK.findall(line) + AUTOLINK.findall(line)
        definition = REFERENCE_DEF.match(line)
        if definition:
            targets.append(definition.group(1))
        links.extend(Link(source, number, target) for target in targets)
    return links


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        wanted = LINK_ATTRIBUTES.get(tag)
        for name, value in attrs:
            if name == wanted and value:
                self.found.append((self.getpos()[0], value.strip()))


def extract_html_links(text: str, source: Path) -> list[Link]:
    """Return the href and src targets of an HTML text.

    :param text: HTML source.
    :param source: path of the document, stored on each link.
    :returns: links in document order.
    """
    collector = _LinkCollector()
    collector.feed(text)
    collector.close()
    return [Link(source, line, target) for line, target in collector.found]


def extract_links(path: Path) -> list[Link]:
    """Read a document and return its links.

    :param path: a ``.md``/``.markdown`` or ``.html``/``.htm`` file.
    :returns: links in document order.
    :raises ValueError: if the file type is not supported.
    """
    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown"):
        return extract_markdown_links(path.read_text(encoding="utf-8"), path)
    if suffix in (".html", ".htm"):
        return extract_html_links(path.read_text(encoding="utf-8"), path)
    raise ValueError(f"unsupported document type: {path.name}")
