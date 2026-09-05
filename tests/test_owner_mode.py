"""OWNER_MODE — «это наша машина» отвязано от «требуй логин».

Клиентская инсталляция (логин настроен, OWNER_MODE не задан) не должна видеть
наши квоты, прокси и профили Claude. Наш VPS — логин настроен И OWNER_MODE=1.
"""
import pytest

from app.auth import is_owner_mode
from app.routes import system as system_routes


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("OWNER_MODE", "DASHBOARD_USER", "DASHBOARD_PASSWORD"):
        monkeypatch.delenv(key, raising=False)


def _set_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")


def test_dev_laptop_without_login_is_owner(monkeypatch):
    """Дефолт = старое поведение: без логина машина наша."""
    assert is_owner_mode() is True


def test_client_install_with_login_is_not_owner(monkeypatch):
    _set_auth(monkeypatch)
    assert is_owner_mode() is False


def test_owner_mode_overrides_enabled_login(monkeypatch):
    """Наш VPS: логин включён, но данные наши."""
    _set_auth(monkeypatch)
    monkeypatch.setenv("OWNER_MODE", "1")
    assert is_owner_mode() is True


@pytest.mark.parametrize("value", ["true", "YES", " 1 "])
def test_owner_mode_truthy_spellings(monkeypatch, value):
    _set_auth(monkeypatch)
    monkeypatch.setenv("OWNER_MODE", value)
    assert is_owner_mode() is True


def test_explicit_off_hides_even_without_login(monkeypatch):
    """Явный OWNER_MODE=0 перебивает отсутствие логина — иначе флаг врёт."""
    monkeypatch.setenv("OWNER_MODE", "0")
    assert is_owner_mode() is False


@pytest.mark.asyncio
async def test_usage_hidden_from_client(monkeypatch):
    """null, а не {"usage": null} — фронт прячет бар только по falsy-значению."""
    _set_auth(monkeypatch)
    assert await system_routes.get_usage() is None
    # #13 сменил форму ответа на {step_minutes, rows, oldest_ts}; проверяем не форму,
    # а то, ради чего тест написан: клиенту не уезжает ни одной точки и ни одной даты
    history = await system_routes.usage_history()
    assert history["rows"] == []
    assert history["oldest_ts"] == ""


@pytest.mark.asyncio
async def test_usage_visible_to_owner_with_login(monkeypatch):
    _set_auth(monkeypatch)
    monkeypatch.setenv("OWNER_MODE", "1")

    async def _fake_usage_data():
        return {"anthropic": {"five_hour": {"utilization": 7}}}

    monkeypatch.setattr(system_routes, "_get_usage_data", _fake_usage_data)
    usage = await system_routes.get_usage()
    # Предмет теста — ВИДИМОСТЬ данных владельцу, а не точный состав ключей. Сверка на
    # полное равенство ломалась от каждого нового поля: `quota_headroom` добавлен
    # `e2f79204` (#447, 03.09) и к правам доступа отношения не имеет.
    assert usage["anthropic"] == {"five_hour": {"utilization": 7}}
    assert "quota_headroom" in usage, usage


def test_profiles_gate_blocks_client(monkeypatch):
    from fastapi import HTTPException

    _set_auth(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        import asyncio
        asyncio.run(system_routes.get_profiles())
    assert exc.value.status_code == 403


def test_login_gate_stays_on_auth_not_owner(monkeypatch):
    """OWNER_MODE не должен открывать дашборд без пароля."""
    from app.auth import is_auth_enabled, requires_auth

    _set_auth(monkeypatch)
    monkeypatch.setenv("OWNER_MODE", "1")
    assert is_auth_enabled() is True
    assert requires_auth("/api/sessions", "GET") is True
