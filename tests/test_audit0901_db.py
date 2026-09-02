"""Audit 01.09: восстановление после рестарта и одноразовость денежной миграции."""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "audit0901.db")
    from app.db import init_db
    init_db()


def test_triggering_job_claimed_seconds_before_restart_is_recovered(db):
    """Джоб, чей триггер убит рестартом, обязан вернуться в 'active' независимо от возраста."""
    from app.db import bg_claim_trigger, bg_get_job, bg_reset_stale_triggering, bg_save_job

    now = datetime.now(timezone.utc)
    bg_save_job({
        "id": "run-killed-by-restart", "type": "run", "config": "{}",
        "message": "codex review", "target_session_id": "s-1",
        "target_name": "w1", "target_scope": "/s", "created_by_name": "orch",
        "status": "active", "expires_at": (now + timedelta(hours=1)).isoformat(),
        "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
    })
    assert bg_claim_trigger("run-killed-by-restart") is True

    reset = bg_reset_stale_triggering()

    assert reset == ["run-killed-by-restart"]
    assert bg_get_job("run-killed-by-restart")["status"] == "active"


def test_legal_small_price_is_not_multiplied_on_restart(db):
    """Цена 1..999 — законный ввод: рестарт не имеет права умножать деньги на 1000."""
    from app import db as dbm

    now = datetime.now(timezone.utc).isoformat()
    with dbm._conn() as c:
        c.execute(
            "INSERT INTO tm_projects (id, name, created_at) VALUES ('p1', 'Proj', ?)",
            (now,),
        )
        c.execute(
            "INSERT INTO tm_tasks (par_number, project_id, title, price_rub, paid_rub,"
            " created_at, updated_at) VALUES (1, 'p1', 'task', 500, 300, ?, ?)",
            (now, now),
        )

    dbm.init_db()  # рестарт сервиса

    with dbm._conn() as c:
        row = c.execute("SELECT price_rub, paid_rub FROM tm_tasks").fetchone()
    assert (row["price_rub"], row["paid_rub"]) == (500, 300)


def test_mid_delivery_run_job_stays_distinguishable_after_reset(db):
    """Сброс обязан оставить caller'у, чем отличить 'доставлял' от 'исполнял'.

    restore_from_db шлёт run-джобу '[Background job INTERRUPTED] … повторный запуск не
    выполнялся' — для джоба, чья команда УЖЕ отработала и который умер на доставке, это
    ложь, а его результат при этом выбрасывается. Разделить может только сам сброс:
    вернуть id тех, кто был в 'triggering', и сохранить их last_output.
    """
    from app.db import bg_claim_trigger, bg_get_job, bg_reset_stale_triggering, bg_save_job

    now = datetime.now(timezone.utc)
    for job_id, output in (("run-delivering", "codex verdict tail"), ("run-executing", "")):
        bg_save_job({
            "id": job_id, "type": "run", "config": "{}",
            "message": "codex review", "target_session_id": "s-1",
            "target_name": "w1", "target_scope": "/s", "created_by_name": "orch",
            "status": "active", "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": output,
        })
    assert bg_claim_trigger("run-delivering") is True

    reset = bg_reset_stale_triggering()

    assert reset == ["run-delivering"], "id доставлявшего джоба обязан вернуться caller'у"
    assert bg_get_job("run-delivering")["last_output"] == "codex verdict tail"


def test_money_migration_writes_a_journal_line_when_it_fires(db, caplog):
    """Умножение живых денег на 1000 обязано оставить след: маркер после ветки одинаков."""
    import logging

    from app import db as dbm

    now = datetime.now(timezone.utc).isoformat()
    with dbm._conn() as c:
        c.execute("DELETE FROM kv WHERE key='money_units_v1'")  # БД, созданная до фикса
        c.execute(
            "INSERT INTO tm_projects (id, name, created_at) VALUES ('p1', 'Proj', ?)",
            (now,),
        )
        c.execute(
            "INSERT INTO tm_tasks (par_number, project_id, title, price_rub, paid_rub,"
            " created_at, updated_at) VALUES (1, 'p1', 'task', 500, 300, ?, ?)",
            (now, now),
        )

    with caplog.at_level(logging.WARNING, logger="db"):
        dbm.init_db()

    with dbm._conn() as c:
        row = c.execute("SELECT price_rub, paid_rub FROM tm_tasks").fetchone()
    assert (row["price_rub"], row["paid_rub"]) == (500000, 300000)
    fired = [r.getMessage() for r in caplog.records if "money units v1 migration fired" in r.getMessage()]
    assert fired == ["money units v1 migration fired: max_price=500"]


@pytest.mark.asyncio
async def test_restart_mid_delivery_sends_run_result_instead_of_interruption(db):
    """Рестарт на доставке результата: досылаем результат, а не 'запуск не выполнялся'.

    Команда run-джоба в 'triggering' УЖЕ вышла (в этот статус его переводит только
    _trigger после успешного прогона), её хвост лежит в last_output. Прежний
    restore_from_db слал такому джобу '[Background job INTERRUPTED] … повторный запуск
    не выполнялся' и выбрасывал результат. Джоб, убитый ВО ВРЕМЯ команды ('active'),
    по-прежнему обязан получить INTERRUPTED.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.bg_jobs import BgJobManager
    from app.db import bg_claim_trigger, bg_get_job, bg_save_job

    now = datetime.now(timezone.utc)
    for job_id, output in (("run-delivering", "codex verdict tail"), ("run-executing", "")):
        bg_save_job({
            "id": job_id, "type": "run", "config": '{"command": "codex exec"}',
            "message": "codex review", "target_session_id": "s-1",
            "target_name": "w1", "target_scope": "/s", "created_by_name": "orch",
            "status": "active", "expires_at": (now + timedelta(hours=1)).isoformat(),
            "trigger_at": None, "created_at": now.isoformat(), "last_output": output,
        })
    assert bg_claim_trigger("run-delivering") is True  # рестарт застал доставку

    session = MagicMock()
    session.id = "s-1"
    session.send = AsyncMock()
    manager = MagicMock()
    manager.ensure_loaded_by_id = AsyncMock(return_value=session)

    async def deliver(_session_id, message, *, provenance):
        await session.send(message, provenance=provenance)

    manager.send = AsyncMock(side_effect=deliver)
    mgr = BgJobManager()
    mgr.set_session_manager(manager)

    await mgr.restore_from_db()

    delivered = {}
    for call in session.send.await_args_list:
        message = call.args[0]
        assert message.provenance.origin == "background_task"
        delivered[message.provenance.ref] = message.text
    assert "[Background job completed] codex review" in delivered["run-delivering"]
    assert "codex verdict tail" in delivered["run-delivering"]
    assert "повторный запуск не выполнялся" not in delivered["run-delivering"]
    assert bg_get_job("run-delivering")["status"] == "triggered"

    assert "[Background job INTERRUPTED]" in delivered["run-executing"]
    assert bg_get_job("run-executing")["status"] == "failed"
