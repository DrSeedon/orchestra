from hostsfile.model import LineKind
from hostsfile.parser import parse_line, parse_text, read_hosts


def test_parse_entry_with_comment():
    line = parse_line("10.0.0.5   build build.lan   # build box", 4)
    assert line.number == 4
    assert line.kind is LineKind.ENTRY
    assert line.address == "10.0.0.5"
    assert line.names == ["build", "build.lan"]
    assert line.comment == "build box"
    assert line.is_entry


def test_parse_blank_and_comment_lines():
    assert parse_line("   ", 1).kind is LineKind.BLANK
    comment = parse_line("# lab hosts", 2)
    assert comment.kind is LineKind.COMMENT
    assert comment.comment == "lab hosts"
    assert not comment.is_entry


def test_parse_keeps_bad_address_and_missing_names():
    bad = parse_line("10.0.0.300 printer", 1)
    assert bad.address == "10.0.0.300"
    assert bad.names == ["printer"]
    alone = parse_line("10.0.0.7", 2)
    assert alone.kind is LineKind.ENTRY
    assert alone.names == []


def test_parse_text_numbers_every_line():
    lines = parse_text("# top\n\n127.0.0.1 localhost\n::1 localhost\n")
    assert [line.number for line in lines] == [1, 2, 3, 4]
    assert [line.kind for line in lines] == [LineKind.COMMENT, LineKind.BLANK,
                                             LineKind.ENTRY, LineKind.ENTRY]


def test_read_hosts(tmp_path):
    path = tmp_path / "hosts"
    path.write_text("127.0.0.1 localhost\n10.0.0.5 build\n", encoding="utf-8")
    lines = read_hosts(path)
    assert [line.names for line in lines] == [["localhost"], ["build"]]
