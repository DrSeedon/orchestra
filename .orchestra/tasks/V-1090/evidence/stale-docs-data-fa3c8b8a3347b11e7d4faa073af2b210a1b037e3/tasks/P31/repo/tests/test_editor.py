import pytest

from hostsfile.editor import add_entry, find_name, remove_name
from hostsfile.model import HostsFileError
from hostsfile.parser import parse_text

HOSTS = "# lab\n127.0.0.1 localhost\n::1 localhost\n10.0.0.5 build build.lan\n"


def test_find_name_ignores_case():
    lines = parse_text(HOSTS)
    assert [line.number for line in find_name(lines, "LOCALHOST")] == [2, 3]
    assert find_name(lines, "web") == []


def test_add_entry_appends_with_next_number():
    lines = parse_text(HOSTS)
    result = add_entry(lines, "10.0.0.6", ["web"], "web box")
    assert len(lines) == 4
    assert result[-1].number == 5
    assert result[-1].names == ["web"]
    assert result[-1].comment == "web box"


def test_add_entry_allows_same_name_for_other_family():
    lines = parse_text(HOSTS)
    result = add_entry(lines, "fd00::5", ["build"])
    assert result[-1].address == "fd00::5"


def test_add_entry_rejects_name_mapped_in_same_family():
    with pytest.raises(HostsFileError, match="line 4"):
        add_entry(parse_text(HOSTS), "10.0.0.9", ["Build"])


@pytest.mark.parametrize("address, names", [("10.0.0.300", ["web"]), ("10.0.0.6", ["bad_name"]),
                                            ("10.0.0.6", [])])
def test_add_entry_rejects_bad_input(address, names):
    with pytest.raises(HostsFileError):
        add_entry(parse_text(HOSTS), address, names)


def test_remove_name_keeps_other_names():
    result = remove_name(parse_text(HOSTS), "build")
    assert result[-1].names == ["build.lan"]


def test_remove_name_drops_empty_entries():
    result = remove_name(parse_text(HOSTS), "localhost")
    assert [line.number for line in result] == [1, 4]


def test_remove_unknown_name():
    with pytest.raises(HostsFileError, match="web"):
        remove_name(parse_text(HOSTS), "web")
