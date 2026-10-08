import pytest
from app.secret_mask import mask_secrets, mask_secrets_report

LONG = "abcdefghijklmnopqrstuvwxyz0123"


def test_two_values_counted():
    text = f"API_KEY={LONG} and PASSWORD={LONG}"
    out, n = mask_secrets_report(text)
    assert out == mask_secrets(text)
    assert n == 2


def test_no_secret_zero():
    out, n = mask_secrets_report("hello world, nothing here")
    assert out == "hello world, nothing here" and n == 0


def test_short_value_not_masked_not_counted():
    out, n = mask_secrets_report("TOKEN=abc")
    assert out == "TOKEN=abc" and n == 0


def test_input_already_containing_marker_not_counted():
    text = f"note: [secret len=5] then API_KEY={LONG}"
    out, n = mask_secrets_report(text)
    assert out.count("[secret ") == 2
    assert n == 1


def test_tg_proxy_link_kept_and_not_counted():
    link = "https://t.me/proxy?server=1.2.3.4&port=443&secret=" + "ab" * 16
    out, n = mask_secrets_report(link)
    assert out == link and n == 0


def test_empty_and_non_string():
    assert mask_secrets_report("") == ("", 0)
    assert mask_secrets_report(None) == (None, 0)
    assert mask_secrets_report(123) == (123, 0)


def test_returns_tuple():
    r = mask_secrets_report("x")
    assert isinstance(r, tuple) and len(r) == 2
