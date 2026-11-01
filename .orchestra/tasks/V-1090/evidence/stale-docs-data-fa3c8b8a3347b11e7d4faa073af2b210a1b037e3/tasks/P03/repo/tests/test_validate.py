import pytest

from linkcheck.validate import check_local_target, check_url_syntax, classify, resolve_local


@pytest.mark.parametrize(
    "target, kind",
    [
        ("#usage", "anchor"),
        ("https://example.com/x", "external"),
        ("HTTP://example.com", "external"),
        ("mailto:team@example.com", "ignored"),
        ("guide.md#install", "local"),
        ("../img/a.png", "local"),
    ],
)
def test_classify(target, kind):
    assert classify(target) == kind


@pytest.mark.parametrize("url", ["https://example.com", "http://localhost:8000/x", "https://a.b/c?d=1"])
def test_check_url_syntax_accepts(url):
    check_url_syntax(url)


@pytest.mark.parametrize(
    "url, message",
    [
        ("https://exa mple.com", "whitespace"),
        ("https:///path", "no host"),
        ("https://intranet/page", "not a domain name"),
        ("https://example.com:99999/", "bad port"),
    ],
)
def test_check_url_syntax_rejects(url, message):
    with pytest.raises(ValueError, match=message):
        check_url_syntax(url)


def test_resolve_local_drops_fragment(tmp_path):
    source = tmp_path / "docs" / "index.md"
    assert resolve_local(source, "guide%20v2.md#top") == (tmp_path / "docs" / "guide v2.md").resolve()


def test_resolve_local_root_relative(tmp_path):
    source = tmp_path / "docs" / "index.md"
    assert resolve_local(source, "/img/a.png", tmp_path) == (tmp_path / "img" / "a.png").resolve()
    with pytest.raises(ValueError, match="needs a site root"):
        resolve_local(source, "/img/a.png")


def test_resolve_local_needs_file_part(tmp_path):
    with pytest.raises(ValueError, match="no file part"):
        resolve_local(tmp_path / "index.md", "?x=1")


def test_check_local_target(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n", encoding="utf-8")
    source = tmp_path / "index.md"
    assert check_local_target(source, "guide.md#intro") == (tmp_path / "guide.md").resolve()
    with pytest.raises(FileNotFoundError, match="missing file: gone.md"):
        check_local_target(source, "gone.md")
