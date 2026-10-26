import pytest

from hostsfile.address import address_family, check_names, is_valid_name, name_key
from hostsfile.model import Family, HostsFileError


@pytest.mark.parametrize("text, family", [
    ("127.0.0.1", Family.IPV4),
    ("10.20.30.40", Family.IPV4),
    ("::1", Family.IPV6),
    ("fe80::1", Family.IPV6),
])
def test_address_family(text, family):
    assert address_family(text) is family


@pytest.mark.parametrize("text", ["10.0.0.300", "localhost", "", "1.2.3", "::g"])
def test_address_family_rejects_bad_address(text):
    with pytest.raises(HostsFileError):
        address_family(text)


@pytest.mark.parametrize("name", ["localhost", "build.lan", "ip6-localhost", "a1.b2.c3", "x" * 63])
def test_valid_names(name):
    assert is_valid_name(name)


@pytest.mark.parametrize("name", ["", "-bad", "bad-", "web_server", "a..b", "host.", "x" * 64,
                                  ".".join(["abcdefghij"] * 24)])
def test_invalid_names(name):
    assert not is_valid_name(name)


def test_check_names_accepts_valid_names():
    check_names(["build", "build.lan"])


def test_check_names_rejects_empty_list():
    with pytest.raises(HostsFileError, match="at least one"):
        check_names([])


def test_check_names_rejects_bad_name():
    with pytest.raises(HostsFileError, match="web_server"):
        check_names(["web", "web_server"])


def test_name_key_ignores_case():
    assert name_key("Build.LAN") == name_key("build.lan") == "build.lan"
