"""#54 — строка-призрак: сессия с пустым id существует, но ни один UPDATE до неё не доходит.

Замер на копии живой БД (Phase 1): `id TEXT PRIMARY KEY` пустил ДВЕ строки с `id=NULL`,
а `UPDATE … WHERE id=NULL` изменил ноль строк. Здесь это закрыто на трёх уровнях: схема,
триггер (для уже существующих БД) и гард в коде.
"""
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()
    return dbmod


def _row(sid="", name="worker"):
    return {
        "id": sid, "name": name, "scope": "/s", "cwd": "/s", "model": "claude-sonnet-5[1m]",
        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "", "branch": "", "base_branch": "main",
        "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 0,
    }


class TestGuardInCode:
    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_save_session_refuses_empty_id_loudly(self, db, bad):
        with pytest.raises(ValueError) as e:
            db.save_session(_row(bad))
        assert "session id is required" in str(e.value)
        assert "worker" in str(e.value), "в тексте должно быть видно, о какой сессии речь"

    def test_valid_id_still_saves(self, db):
        sid = str(uuid.uuid4())
        db.save_session(_row(sid))
        assert db.get_session(sid)["name"] == "worker"


class TestGuardInDatabase:
    """Гард в коде обходится любым прямым INSERT — база обязана защищаться сама."""

    @pytest.mark.parametrize("bad", [None, "", "   "])
    def test_direct_insert_is_rejected_by_trigger(self, db, bad):
        with pytest.raises(sqlite3.IntegrityError) as e:
            with db._conn() as c:
                c.execute(
                    "INSERT INTO sessions (id, name, scope, cwd, model, created_at) "
                    "VALUES (?, 'ghost', '/s', '/s', 'm', '2026-08-04')", (bad,),
                )
        assert "sessions.id must be non-empty" in str(e.value)

    def test_update_cannot_blank_an_existing_id(self, db):
        sid = str(uuid.uuid4())
        db.save_session(_row(sid))
        with pytest.raises(sqlite3.IntegrityError):
            with db._conn() as c:
                c.execute("UPDATE sessions SET id='' WHERE id=?", (sid,))
        assert db.get_session(sid) is not None

    def test_existing_database_gets_the_trigger_on_migration(self, tmp_path, monkeypatch):
        """БД, созданная ДО фикса, чинится миграцией: та же схема, триггеров ещё нет."""
        import app.db as dbmod

        old = tmp_path / "old.db"
        monkeypatch.setattr(dbmod, "DB_PATH", old)
        dbmod.init_db()
        # Откатываем схему к дофиксовой: тот же набор колонок, но без NOT NULL и без
        # триггеров — ровно та БД, что лежит у нас в проде с мая.
        with dbmod._conn() as c:
            ddl = c.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'"
            ).fetchone()[0]
            c.executescript(f"""
                PRAGMA foreign_keys=OFF;
                DROP TRIGGER sessions_id_required_insert;
                DROP TRIGGER sessions_id_required_update;
                ALTER TABLE sessions RENAME TO sessions_pre_fix;
                {ddl.replace("id TEXT PRIMARY KEY NOT NULL", "id TEXT PRIMARY KEY")};
                INSERT INTO sessions SELECT * FROM sessions_pre_fix;
                DROP TABLE sessions_pre_fix;
            """)
            c.execute("INSERT INTO sessions (id, name, scope, cwd, model, created_at) "
                      "VALUES (NULL, 'ghost', '/s', '/s', 'm', '2026-08-03')")
            ghosts = c.execute(
                "SELECT COUNT(*) FROM sessions WHERE id IS NULL").fetchone()[0]
        assert ghosts == 1, "предпосылка теста: до фикса строка-призрак вставляется"

        dbmod.init_db()  # повторный запуск сервиса = миграция
        with pytest.raises(sqlite3.IntegrityError):
            with dbmod._conn() as c:
                c.execute("INSERT INTO sessions (id, name, scope, cwd, model, created_at) "
                          "VALUES (NULL, 'ghost2', '/s2', '/s', 'm', '2026-08-04')")
        # уже лежащую строку триггер не трогает — это данные, их чинит человек
        with dbmod._conn() as c:
            assert c.execute(
                "SELECT COUNT(*) FROM sessions WHERE id IS NULL").fetchone()[0] == 1


class TestSilentZeroRowUpdateIsLoud:
    def test_lifecycle_update_warns_when_nothing_changed(self, db, caplog):
        with caplog.at_level(logging.WARNING):
            ok = db.update_session_lifecycle(
                "нет-такой-сессии", branch="b", base_branch="main",
                task_id="", needs_switch=False,
            )
        assert ok is False
        assert any("changed 0 rows" in r.getMessage() for r in caplog.records)

    def test_archive_warns_when_nothing_changed(self, db, caplog):
        with caplog.at_level(logging.WARNING):
            db.archive_session("нет-такой-сессии")
        assert any("changed 0 rows" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_bg_create_answers_400_not_500_for_a_session_without_id(db, monkeypatch):
    import json

    import app.routes.bg as bgmod

    class Ghost:
        id = ""
        name = "ghost"

    monkeypatch.setattr(bgmod.manager, "get_by_name", lambda *_a: Ghost())
    resp = await bgmod.bg_job_create(bgmod.BgJobCreateRequest(
        type="timer", config={"delay_seconds": 5}, message="проверка",
        target_name="ghost", target_scope="/s", created_by="test",
    ))
    body = json.loads(resp.body)
    print("\nbg_create →", resp.status_code, body["error"])
    assert resp.status_code == 400
    assert "has no id" in body["error"]
