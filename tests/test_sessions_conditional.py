"""`/api/sessions` отвечает 304, пока состояние агентов не изменилось.

Дашборд опрашивает этот маршрут каждые 3 секунды, и ответ весит 48.8 КБ даже когда
ничего не поменялось (замер 21.08) — почти мегабайт в минуту и один из шести браузерных
слотов, из которых один навсегда держит SSE.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import app, manager

        manager.sessions.clear()
        with TestClient(app) as c:
            yield c


def _get(client, **headers):
    return client.get("/api/sessions?scope=/scope", headers=headers)


def test_unchanged_state_costs_no_body(client):
    first = _get(client)
    assert first.status_code == 200
    tag = first.headers.get("ETag")
    assert tag, "без ETag браузер не пришлёт If-None-Match и тело поедет каждые 3 с"
    # `no-cache` = «кешируй, но всегда переспрашивай». Без него ревалидации не будет вовсе.
    assert first.headers.get("Cache-Control") == "no-cache"

    repeat = _get(client, **{"If-None-Match": tag})
    assert repeat.status_code == 304
    # 304 по спецификации не несёт полезной нагрузки; на живом стенде это 48.8 КБ -> 0.
    assert b"session" not in repeat.content


def test_stale_etag_still_returns_the_payload(client):
    """Обратное направление: несовпадение обязано отдать тело, иначе дашборд ослепнет."""
    fresh = _get(client, **{"If-None-Match": '"definitely-not-the-current-state"'})
    assert fresh.status_code == 200
    assert fresh.headers.get("ETag") != '"definitely-not-the-current-state"'


def test_etag_tracks_the_payload_not_the_clock(client):
    """Ключ считается от самого ответа — два запроса подряд дают один и тот же тег."""
    a, b = _get(client), _get(client)
    assert a.headers["ETag"] == b.headers["ETag"]
