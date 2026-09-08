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
            "INSERT INTO tm_tasks (par_number, project_id, title, price_rub,"
            " created_at, updated_at) VALUES (1, 'p1', 'task', 500, ?, ?)",
            (now, now),
        )

    dbm.init_db()  # рестарт сервиса

    with dbm._conn() as c:
        row = c.execute("SELECT price_rub FROM tm_tasks").fetchone()
    assert row["price_rub"] == 500


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
