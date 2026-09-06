"""Ссылка-приглашение MTProto-прокси не должна маскироваться: `secret=` там публичный."""

from app.secret_mask import mask_secrets

PROXY = "https://t.me/proxy?server=proxy.example.net&port=4443&secret=ee0000000000000000000000000000NvbQ"


def test_telegram_proxy_link_survives_masking():
    assert mask_secrets(PROXY) == PROXY


def test_tg_scheme_proxy_link_survives_masking():
    link = "tg://proxy?server=example.org&port=443&secret=7g0000000000000000000000000000Y29t"
    assert mask_secrets(link) == link


def test_real_secret_next_to_a_proxy_link_is_still_masked():
    text = f"{PROXY} API_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    masked = mask_secrets(text)
    assert PROXY in masked, "публичная ссылка не должна страдать от соседства"
    assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in masked
    assert "[secret len=32 tail=aaaa]" in masked


def test_secret_parameter_outside_a_proxy_link_is_still_masked():
    value = "client_secret=abcdefghijklmnopqrstuvwx"
    assert "[secret len=24 tail=uvwx]" in mask_secrets(value)
