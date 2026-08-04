"""#80 — сквозной сценарий залипания на НАСТОЯЩЕМ git-репозитории.

Воспроизводит инциденты 6c226777 и b876ac54: git прошёл целиком, часть привязок
применилась, одна ссылка указывает на несуществующий номер. До #80 такая операция
оставалась PARTIAL и держала воркера: следующий вызов с НОВЫМ operation_id возвращал
результат ПЕРВОЙ операции, и новые коммиты в main не попадали никогда.
"""

import asyncio
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _git(*args, cwd) -> str:
    done = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
    )
    return done.stdout.strip()


def _commit(worktree, message: str, filename: str) -> None:
    (Path(worktree) / filename).write_text(message)
    _git("add", ".", cwd=worktree)
    _git("commit", "-m", message, cwd=worktree)


@pytest.fixture
def live_merge(tmp_path, monkeypatch):
    """Настоящий репозиторий + worktree + БД сессий и задач. Мокается только обвязка
    сессий: сам мерж делает git, привязку — tm."""
    import app.db as dbmod
    import app.merge_operations as operations
    import app.tm as tm
    import app.workspace as workspace

    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", cwd=repo)
    # Свежий init даёт master: без переименования ветка target не совпадёт с base_branch.
    _git("branch", "-M", "main", cwd=repo)
    _git("config", "user.email", "test@test.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("# test")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)

    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    monkeypatch.setattr(workspace, "WORKTREE_ROOT", worktree_root)
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "orchestra.db")
    dbmod.init_db()
    operations._runner_tasks.clear()

    worktree = workspace.create_worktree(str(repo), "worker", base_branch="main")
    _git("config", "user.email", "test@test.com", cwd=worktree.path)
    _git("config", "user.name", "Test", cwd=worktree.path)

    dbmod.save_session({
        "id": "stuck-session",
        "name": "worker",
        "scope": str(repo),
        "cwd": str(repo),
        "model": "model",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": worktree.path,
        "branch": worktree.branch,
        "base_branch": "main",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": "24",
        "needs_switch": 0,
    })

    # Существует только задача 24. Номер 25 не существует — ровно как в инцидентах.
    with dbmod._conn() as connection:
        project = tm.ensure_project(connection, "proj", "proj", scope=str(repo))
        tm.create_task(connection, project["id"], "живая задача", par_number=24)

    async def fake_execute(*, session_id, expected_name, expected_scope,
                           expected_branch, expected_head, req):
        """Тонкая обвязка вокруг тех же двух НАСТОЯЩИХ функций, что зовёт прод:
        `merge_worktree_to_main` и `tm.link_commits_to_task` (app/routes/sessions.py)."""
        outcome = dict(workspace.merge_worktree_to_main(
            worktree.path,
            str(repo),
            target_branch=req.get("target") or "main",
            expected_worker_branch=expected_branch,
            expected_worker_head=expected_head,
        ))
        if not outcome.get("ok"):
            return outcome
        links = {}
        for task_ref, commits in outcome.pop("merged_commits", {}).items():
            links[task_ref] = await asyncio.to_thread(
                tm.link_commits_to_task, task_ref, commits, project["id"],
            )
        if links:
            outcome["linked_tasks"] = links
        outcome["lifecycle_status"] = {"ok": True}
        outcome["rag_backfill_status"] = "accepted"
        return outcome

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", fake_execute)
    return {"repo": repo, "worktree": worktree, "operations": operations}


async def _merge(operations, operation_id: str, scope: str):
    result, status = await operations.accept_merge_operation(
        operation_id=operation_id, name="worker", scope=scope, target="main",
    )
    if operations._runner_tasks:
        await asyncio.gather(*list(operations._runner_tasks.values()))
        result = operations.get_operation_result(
            result["operation_id"]
        ) or result
    return result, status


@pytest.mark.asyncio
async def test_missing_task_ref_does_not_freeze_the_branch_forever(live_merge):
    repo = live_merge["repo"]
    worktree = live_merge["worktree"]
    operations = live_merge["operations"]

    _commit(worktree.path, "#24: applied link", "a.txt")
    _commit(worktree.path, "#25: link to a number that does not exist", "b.txt")

    first_id = str(uuid.uuid4())
    first, _status = await _merge(operations, first_id, str(repo))

    # Смешанный исход: применённая привязка остаётся, ненайденная — предупреждение.
    assert first["operation_state"] == "SUCCEEDED", first["error"]
    assert first["commit_point"] == "REACHED"
    assert first["task_links"]["status"] == "WARNED"
    assert first["task_links"]["items"]["24"]["ok"] is True
    assert first["task_links"]["items"]["25"]["ok"] is False
    warnings = " ".join(warning["message"] for warning in first["warnings"])
    assert "25" in warnings and "24:" not in warnings
    assert "applied link" in _git("log", "--oneline", "main", cwd=repo)

    # Воркер уходит на новую задачу и делает новые коммиты.
    _git("checkout", "-b", "task-80/worker", cwd=worktree.path)
    _commit(worktree.path, "#24: work after the stuck merge", "c.txt")
    _commit(worktree.path, "#24: more work", "d.txt")

    second_id = str(uuid.uuid4())
    second, _second_status = await _merge(operations, second_id, str(repo))

    # Новый operation_id обязан создать НОВУЮ операцию и слить НОВУЮ ветку.
    assert second["operation_id"] == second_id
    assert second["operation_id"] != first["operation_id"]
    assert second["operation_state"] == "SUCCEEDED", second["error"]
    assert second["git"]["worker_branch"] == "task-80/worker"
    # Squash кладёт первое сообщение в заголовок, остальные — в тело (%B).
    main_log = _git("log", "--format=%B", "main", cwd=repo)
    assert "work after the stuck merge" in main_log
    assert "more work" in main_log
    assert second["git"]["commits_merged"] == 2


@pytest.mark.asyncio
async def test_primary_failure_blocks_until_it_is_explicitly_resolved(live_merge, monkeypatch):
    """Инвариант 1 на живом репозитории: настоящий PARTIAL блокирует до закрытия."""
    repo = live_merge["repo"]
    worktree = live_merge["worktree"]
    operations = live_merge["operations"]

    import app.routes.sessions as sessions

    original = sessions.execute_merge_session

    async def failing_lifecycle(**kwargs):
        outcome = await original(**kwargs)
        if outcome.get("ok"):
            outcome["lifecycle_status"] = {"ok": False, "error": "sqlite unavailable"}
        return outcome

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", failing_lifecycle)

    _commit(worktree.path, "#24: first", "a.txt")
    first_id = str(uuid.uuid4())
    first, _status = await _merge(operations, first_id, str(repo))
    assert first["operation_state"] == "PARTIAL"
    assert "resolve_merge_operation" in first["next_action"]["message"]

    _git("checkout", "-b", "task-80/worker", cwd=worktree.path)
    _commit(worktree.path, "#24: blocked work", "b.txt")
    blocked_id = str(uuid.uuid4())
    blocked, _blocked_status = await _merge(operations, blocked_id, str(repo))
    assert blocked["operation_id"] == first_id
    assert "resolve_merge_operation" in blocked["next_action"]["message"]
    assert "blocked work" not in _git("log", "--oneline", "main", cwd=repo)

    operations.resolve_operation(first_id, reason="session row repaired by hand")
    monkeypatch.setattr("app.routes.sessions.execute_merge_session", original)
    after_id = str(uuid.uuid4())
    after, _after_status = await _merge(operations, after_id, str(repo))
    assert after["operation_id"] == after_id
    assert after["operation_state"] == "SUCCEEDED", after["error"]
    assert "blocked work" in _git("log", "--oneline", "main", cwd=repo)
