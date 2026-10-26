import pytest

from linkcheck.scanner import check_document, check_tree, find_documents


@pytest.fixture
def site(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "index.md").write_text(
        "[guide](docs/guide.md)\n[gone](docs/gone.md)\n[top](#top)\n[web](https://intranet/wiki)\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "guide.md").write_text("[back](../index.md)\n", encoding="utf-8")
    (tmp_path / "docs" / "page.html").write_text('<a href="/missing.html">x</a>', encoding="utf-8")
    (tmp_path / "docs" / "notes.txt").write_text("[x](y.md)", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg.md").write_text("[x](nope.md)", encoding="utf-8")
    return tmp_path


def test_find_documents_skips_other_files(site):
    names = [path.relative_to(site).as_posix() for path in find_documents(site)]
    assert names == ["docs/guide.md", "docs/page.html", "index.md"]


def test_find_documents_needs_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        find_documents(tmp_path / "missing")


def test_check_document(site):
    problems = check_document(site / "index.md", site)
    assert [(p.link.line, p.message) for p in problems] == [
        (2, "missing file: docs/gone.md"),
        (4, "host is not a domain name: intranet"),
    ]


def test_check_tree(site):
    problems, count = check_tree(site)
    assert count == 3
    assert sorted(p.link.target for p in problems) == ["/missing.html", "docs/gone.md", "https://intranet/wiki"]
