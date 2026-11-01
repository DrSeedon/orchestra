from hostsfile.parser import parse_line, parse_text
from hostsfile.writer import render, render_line, write_hosts


def test_render_entry_pads_address():
    line = parse_line("10.0.0.5 build build.lan #build box", 1)
    assert render_line(line) == "10.0.0.5        build build.lan  # build box"


def test_render_long_address_keeps_a_space():
    line = parse_line("fd00:1234:5678::abcd web", 1)
    assert render_line(line) == "fd00:1234:5678::abcd web"


def test_render_blank_and_comment():
    assert render_line(parse_line("", 1)) == ""
    assert render_line(parse_line("#lab", 2)) == "# lab"
    assert render_line(parse_line("#", 3)) == "#"


def test_render_ends_every_line():
    assert render(parse_text("127.0.0.1 localhost\n\n")) == "127.0.0.1       localhost\n\n"


def test_write_hosts_makes_backup(tmp_path):
    path = tmp_path / "etc" / "hosts"
    write_hosts(path, parse_text("127.0.0.1 localhost\n"))
    assert not (path.parent / "hosts.bak").exists()
    write_hosts(path, parse_text("10.0.0.5 build\n"))
    assert (path.parent / "hosts.bak").read_text(encoding="utf-8") == "127.0.0.1       localhost\n"
    assert path.read_text(encoding="utf-8") == "10.0.0.5        build\n"
