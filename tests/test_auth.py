"""Тесты авторизации дашборда — чистые функции, без TestClient/SDK."""
from app.auth import requires_auth
from fastapi.testclient import TestClient


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


def test_openapi_docs_require_auth_but_authenticated_cookie_can_read_schema(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    from app.auth import create_session
    from app.main import app

    with TestClient(app) as client:
        anonymous_statuses = {}
        for path in ("/openapi.json", "/docs", "/redoc"):
            response = client.get(path, follow_redirects=False)
            if response.status_code == 200:
                anonymous_statuses[path] = response.status_code
        assert anonymous_statuses == {}, anonymous_statuses

        client.cookies.set("session", create_session("operator"))
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert response.json()["info"]["title"] == "Orchestra"


def _valid_artifact_env(monkeypatch):
    import base64

    monkeypatch.setenv("ARTIFACT_PUBLIC_LINKS_ENABLED", "1")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://artifacts.example.test")
    monkeypatch.setenv(
        "ARTIFACT_LINK_SECRET",
        base64.urlsafe_b64encode(b"s" * 32).rstrip(b"=").decode(),
    )
    monkeypatch.setenv("ARTIFACT_DEFAULT_TTL_SECONDS", "86400")
    monkeypatch.setenv("ARTIFACT_MAX_TTL_SECONDS", "604800")
    monkeypatch.setenv("ARTIFACT_MAX_BYTES", "10485760")


def test_t2_only_exact_public_artifact_shapes_bypass_dashboard_auth(monkeypatch):
    _valid_artifact_env(monkeypatch)
    locator = "A" * 22
    exempt = {
        (f"/api/artifacts/open/{locator}", "GET"),
        (f"/api/artifacts/open/{locator}", "HEAD"),
        (f"/api/artifacts/open/{locator}/redeem", "POST"),
        (f"/api/artifacts/open/{locator}/content", "GET"),
    }
    protected = {
        (f"/api/artifacts/open/{locator}/content", "HEAD"),
        (f"/api/artifacts/open/{locator}/content", "POST"),
        (f"/api/artifacts/open/{locator}/redeem", "GET"),
        (f"/api/artifacts/open/{locator}/extra", "GET"),
        (f"/api/artifacts/open/{locator}/content/extra", "GET"),
        ("/api/artifacts/open/not+a+locator", "GET"),
        (f"//api/artifacts/open/{locator}", "GET"),
        ("/api/files/raw", "GET"),
    }

    assert all(requires_auth(path, method) is False for path, method in exempt)
    assert all(requires_auth(path, method) is True for path, method in protected)


def test_t2_invalid_or_disabled_artifact_config_falls_through_auth(monkeypatch):
    locator_path = f"/api/artifacts/open/{'B' * 22}"
    variants = [
        {"ARTIFACT_PUBLIC_LINKS_ENABLED": "0"},
        {"ARTIFACT_PUBLIC_LINKS_ENABLED": "true"},
        {"PUBLIC_BASE_URL": "http://artifacts.example.test"},
        {"PUBLIC_BASE_URL": "https://user@artifacts.example.test"},
        {"PUBLIC_BASE_URL": "https://artifacts.example.test/path"},
        {"ARTIFACT_LINK_SECRET": "too-short"},
    ]
    for override in variants:
        _valid_artifact_env(monkeypatch)
        for key, value in override.items():
            monkeypatch.setenv(key, value)
        assert requires_auth(locator_path, "GET") is True, override
