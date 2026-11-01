from pathlib import Path

import pytest

from linkcheck.extract import Link, extract_html_links, extract_links, extract_markdown_links

SOURCE = Path("docs/index.md")


def test_markdown_inline_links_and_images():
    text = "See [setup](setup.md) and ![logo](img/logo.png \"Logo\").\n[home](https://example.com)"
    links = extract_markdown_links(text, SOURCE)
    assert links == [
        Link(SOURCE, 1, "setup.md"),
        Link(SOURCE, 1, "img/logo.png"),
        Link(SOURCE, 2, "https://example.com"),
    ]


def test_markdown_reference_definitions_and_autolinks():
    text = "Intro <https://example.org/a>\n\n[docs]: ./guide.md#install\n"
    targets = [link.target for link in extract_markdown_links(text, SOURCE)]
    assert targets == ["https://example.org/a", "./guide.md#install"]


def test_markdown_ignores_fenced_code():
    text = "```\n[not a link](nowhere.md)\n```\n[real](real.md)\n"
    links = extract_markdown_links(text, SOURCE)
    assert links == [Link(SOURCE, 4, "real.md")]


def test_html_links_with_line_numbers():
    text = '<html>\n<a href="about.html">About</a>\n<img src=" pic.png ">\n<a name="top"></a>\n</html>'
    links = extract_html_links(text, Path("site/index.html"))
    assert [(link.line, link.target) for link in links] == [(2, "about.html"), (3, "pic.png")]


def test_extract_links_reads_file(tmp_path):
    doc = tmp_path / "readme.md"
    doc.write_text("[a](a.md)\n", encoding="utf-8")
    assert extract_links(doc) == [Link(doc, 1, "a.md")]


def test_extract_links_rejects_other_types(tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("[a](a.md)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported document type"):
        extract_links(doc)
