"""#47 — недоставленный автоотчёт оставляет след, не зависящий от сломанного канала.

Стенд живой: настоящий репозиторий, настоящий отказ авто-switch у ОРКЕСТРАТОРА (то есть
принять он не может), воркер уходит в idle и отчитывается.
"""
import asyncio
import logging
import subprocess
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.db import init_db, save_session

    init_db()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)

    from app.workspace import create_worktree

    def row(sid, name, worktree, branch, *, orch=False, needs_switch=0, parent=""):
        return {
            "id": sid, "name": name, "scope": str(repo), "cwd": str(repo),
            "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
            "session_id": None, "cost_usd": 0.0, "worktree_path": worktree,
            "branch": branch, "base_branch": "main", "is_orchestrator": orch, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "task_id": "", "needs_switch": needs_switch, "parent_name": parent,
        }

    boss_wt = create_worktree(str(repo), "boss", "47", base_branch="main")
    stolen = "adhoc-1785700000-1/boss"
    subprocess.run(["git", "branch", stolen, "main"], cwd=repo, capture_output=True, check=True)
    save_session(row("boss-1", "boss", boss_wt.path, boss_wt.branch, orch=True, needs_switch=1))

    worker_wt = create_worktree(str(repo), "worker", "48", base_branch="main")
    worker_id = str(uuid.uuid4())
    save_session(row(worker_id, "worker", worker_wt.path, worker_wt.branch, parent="boss"))

    import app.manager as mgr

    monkeypatch.setattr(mgr, "next_adhoc_branch", lambda _n: stolen)
    return {"repo": str(repo), "worker_id": worker_id, "boss_id": "boss-1"}


async def _report(env):
    from app.main import manager

    manager.sessions.clear()
    await manager.ensure_loaded_any("boss")
    await manager.ensure_loaded_any("worker")
    callback = manager._make_idle_callback(env["repo"])
    await callback("worker", env["repo"], ["последний вывод воркера"], "", True)
    return manager


def _delivery_rows(session_id):
    from app.db import get_logs

    return [r for r in get_logs(session_id, limit=50)
            if "[доставка]" in (r["content"] or "")]


@pytest.mark.asyncio
async def test_both_histories_get_the_record_and_no_exception_escapes(env, caplog):
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        with caplog.at_level(logging.WARNING):
            await _report(env)  # исключение наружу не всплывает — иначе тест упадёт здесь

    worker_rows = _delivery_rows(env["worker_id"])
    boss_rows = _delivery_rows(env["boss_id"])
    print("\nВ ИСТОРИИ ОРКЕСТРАТОРА:\n   ", boss_rows[0]["content"] if boss_rows else "НЕТ")
    assert worker_rows and boss_rows, "след обязан быть в обеих историях"
    assert worker_rows[0]["content"] == boss_rows[0]["content"]
    assert worker_rows[0]["type"] == "system"


@pytest.mark.asyncio
async def test_record_names_both_sides_reason_and_outcome_of_the_attempt(env):
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        await _report(env)

    text = _delivery_rows(env["boss_id"])[0]["content"]
    assert "автоотчёт воркера «worker»" in text and "«boss»" in text
    # исход попытки уведомить обязан быть виден: тихая попытка — тот же дефект
    assert "Попытка уведомить отдельным сообщением:" in text
    assert "уведомить boss не удалось" in text
    assert "Автоматического повтора нет" in text
    assert "RuntimeError" in text


@pytest.mark.asyncio
async def test_successful_auto_report_leaves_no_record(env, monkeypatch):
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import manager

        manager.sessions.clear()
        await manager.ensure_loaded_any("boss")
        await manager.ensure_loaded_any("worker")

        async def ok(*_a, **_k):
            return None

        monkeypatch.setattr(manager, "send", ok)
        callback = manager._make_idle_callback(env["repo"])
        await callback("worker", env["repo"], ["вывод"], "", True)

    assert not _delivery_rows(env["boss_id"]), "удачная доставка не должна оставлять след"


@pytest.mark.asyncio
async def test_silent_marker_auto_report_leaves_no_record(env):
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import manager

        manager.sessions.clear()
        await manager.ensure_loaded_any("boss")
        worker = await manager.ensure_loaded_any("worker")
        worker.on_idle = manager._make_idle_callback(env["repo"])
        worker.parent_name = "boss"
        worker.last_task_sender = "boss"
        worker._turn_logs = ["[tool] inspect", "[[ORCHESTRA:SILENT_TURN]]"]
        worker._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"
        worker._last_turn_ok = True
        worker._turns.fire_auto_report()
        if worker._auto_report_task is not None:
            await worker._auto_report_task

    assert not _delivery_rows(env["boss_id"]), (
        "семантически тихий ход не должен создавать запись недоставленного автоотчёта"
    )


@pytest.mark.asyncio
async def test_attempt_does_not_recurse(env, caplog):
    """Уведомление о недоставке не порождает уведомления о недоставке уведомления."""
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        with caplog.at_level(logging.WARNING):
            await _report(env)

    attempts = [r.getMessage() for r in caplog.records
                if "undelivered автоотчёт" in r.getMessage()]
    print("\nПОПЫТОК УВЕДОМИТЬ:", len(attempts))
    assert len(attempts) == 1, f"ожидалась одна попытка, было {len(attempts)}"
    assert len(_delivery_rows(env["boss_id"])) == 1
