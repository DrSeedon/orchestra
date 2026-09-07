"""#167 дефект 2: потерянная запись лога не должна уходить в никуда.

Воспроизведение из журнала 06.08 14:52:49 — add_log для сессии, которой уже нет
в sessions: FK падает, Future никем не ожидается, asyncio печатает своё
«Future exception was never retrieved» без имени агента и без содержимого.
"""

import asyncio
import datetime
import sqlite3

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import app.db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    return db_module


def test_add_log_for_missing_session_raises(db):
    """Предпосылка дефекта: запись лога мёртвой сессии — это IntegrityError."""
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        db.add_log("ghost", datetime.datetime.now(datetime.timezone.utc), "error", "hi")


@pytest.mark.asyncio
async def test_lost_log_write_is_reported(db, caplog):
    """Потеря записи обязана назвать агента, тип записи, класс ошибки и содержимое."""
    from app.session import AgentSession

    session = AgentSession.__new__(AgentSession)
    session.id = "ghost"  # строки в sessions нет — FK упадёт
    session.name = "Orchestra-orchestrator"
    session._log_futures = set()
    # `__new__` минует `__init__`, поэтому дефолты dataclass-полей НЕ создаются, и
    # обработчик потери падал `AttributeError: 'AgentSession' object has no attribute
    # '_failed_log_writes'` ещё до своего сообщения. В проде поля есть
    # (`app/session.py:560-564`), их создаёт `__init__` — то есть тест ломал сам себя,
    # а не ловил дефект. Ставим ровно те поля, которые читает проверяемый путь.
    session._failed_log_writes = {}
    session._log_write_generation = 0
    session._log_write_failure_generation = 0
    session._log_write_failure = ""

    with caplog.at_level("ERROR", logger="app.session"):
        session._log("error", "connect failed: TimeoutError")
        await asyncio.gather(*session._log_futures, return_exceptions=True)
        await asyncio.sleep(0)  # дать done-callback отработать

    assert "log write lost" in caplog.text
    assert "Orchestra-orchestrator" in caplog.text, "непонятно, чей лог потерян"
    assert "IntegrityError" in caplog.text, "непонятна причина потери"
    assert "connect failed: TimeoutError" in caplog.text, "потеряно содержимое записи"


@pytest.mark.asyncio
async def test_successful_log_write_is_silent(db, caplog):
    """Проверка, одинаковая при успехе и провале, — не проверка."""
    from app.session import AgentSession

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with db._conn() as c:
        c.execute(
            "INSERT INTO sessions (id, name, scope, cwd, model, system_prompt, status, created_at)"
            " VALUES ('live','w','/tmp','/tmp','m','p','idle',?)",
            (now,),
        )

    session = AgentSession.__new__(AgentSession)
    session.id = "live"
    session.name = "w"
    session._log_futures = set()

    with caplog.at_level("ERROR", logger="app.session"):
        session._log("status", "all good")
        await asyncio.gather(*session._log_futures, return_exceptions=True)
        await asyncio.sleep(0)

    assert "log write lost" not in caplog.text
    with db._conn() as c:
        rows = c.execute("SELECT content FROM logs WHERE session_id='live'").fetchall()
    assert [r["content"] for r in rows] == ["all good"]
