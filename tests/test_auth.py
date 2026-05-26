"""Тесты авторизации дашборда — чистые функции, без TestClient/SDK."""
from app.auth import requires_auth


def test_send_endpoint_requires_auth():
    """POST /send требует auth: легитимные вызовы проходят по Bearer-токену
    (MCP-агенты) или по куке (браузер), поэтому анонимное исключение лишнее
    и опасно при публичном выставлении."""
    assert requires_auth("/api/sessions/coder/send", "POST") is True


def test_github_webhook_stays_exempt():
    """Вебхук защищён собственной HMAC-подписью → остаётся вне cookie-auth."""
    assert requires_auth("/api/webhook/github", "POST") is False


def test_login_logout_and_static_exempt():
    assert requires_auth("/login", "GET") is False
    assert requires_auth("/logout", "GET") is False
    assert requires_auth("/static/js/app.js", "GET") is False


def test_api_and_root_require_auth():
    assert requires_auth("/api/sessions", "GET") is True
    assert requires_auth("/", "GET") is True
