"""#15 T3 — TG-мост не держит старт HTTP.

Замер (docs/tasks/15/research.md): импорт app.tg_bridge стоит 4.05 с, из них 3.72 с
aiogram, и всё это время uvicorn не принимает запросы. Проверяем без часов: старт обязан
завершиться, пока мост ещё не поднялся.
"""

import asyncio

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
    from app.db import init_db
    init_db()


def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    return c


class TestBridgeOffCriticalPath:
    def test_startup_completes_while_bridge_still_starting(self, db, monkeypatch):
        """Ключевое утверждение, и оно проверяется без замера времени.

        Мост «зависает» навсегда; если бы старт его ждал, TestClient не вернул бы
        управление вовсе, а тест упал бы по таймауту — то есть провал виден, а не тих.
        """
        state = {"started": False, "finished": False}

        async def fake_start(_manager):
            state["started"] = True
            await asyncio.sleep(3600)
            state["finished"] = True

        import app.tg_bridge as tb
        monkeypatch.setattr(tb, "start_bridge", fake_start)

        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            monkeypatch.delenv("DASHBOARD_USER", raising=False)
            monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
            r = client.get("/api/models")
        assert r.status_code == 200, "HTTP обслуживается, пока мост ещё поднимается"
        assert state["started"], "задача моста так и не стартовала"
        assert not state["finished"], "старт дождался моста — критический путь не разгружен"

    def test_bridge_failure_is_loud_and_does_not_break_startup(self, db, monkeypatch, caplog):
        async def boom(_manager):
            raise RuntimeError("аиограм не завёлся")

        import app.tg_bridge as tb
        monkeypatch.setattr(tb, "start_bridge", boom)

        from fastapi.testclient import TestClient
        from app.main import app
        with caplog.at_level("ERROR"):
            with TestClient(app) as client:
                monkeypatch.delenv("DASHBOARD_USER", raising=False)
                monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
                r = client.get("/api/models")
        assert r.status_code == 200
        text = caplog.text
        assert "TG bridge FAILED" in text, "отказ моста обязан быть громким"
        assert "RuntimeError" in text and "аиограм не завёлся" in text, \
            "в логе должен быть класс исключения и его текст"

    def test_shutdown_survives_bridge_that_never_came_up(self, db, monkeypatch):
        """Выключение при неподнявшемся мосте не должно ни висеть, ни бросать."""
        async def never(_manager):
            await asyncio.sleep(3600)

        import app.tg_bridge as tb
        monkeypatch.setattr(tb, "start_bridge", never)

        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app):
            pass          # выход из контекста = shutdown; исключение здесь провалит тест
