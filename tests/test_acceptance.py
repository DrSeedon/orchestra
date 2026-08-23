"""#240 — приёмочную команду тикета исполняет платформа, не исполнитель.

Оракул краснеет, пока merge_operations зовёт executor, не глядя на зарегистрированную
команду. «Команда отработала» (нулевой exit без отказа мержа) оракулом не является.
Текст DONE не читаем — это вторая копия правды.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _session_row(worktree: str, task_id: str = "42") -> dict:
    return {
        "id": "merge-session",
        "name": "worker",
        "scope": "/scope",
        "cwd": "/scope",
        "model": "model",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": worktree,
        "branch": "task-42/worker",
        "base_branch": "main",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": task_id,
        "needs_switch": 0,
    }


def _accepted(worktree: str, task_id: str = "42") -> dict:
    return {
        "session_id": "merge-session",
        "name": "worker",
        "scope": "/scope",
        "base_branch": "main",
        "worker_branch": "task-42/worker",
        "worker_head": "b" * 40,
        "task_id": task_id,
        "needs_switch": False,
        "worktree_path": worktree,
    }


@pytest.fixture
def acc_db(tmp_path, monkeypatch):
    import app.db as dbmod
    import app.merge_operations as operations
    import app.tm as tm

    db_path = tmp_path / "acc.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    dbmod.save_session(_session_row(str(worktree)))
    with tm._conn() as conn:
        tm.ensure_project(conn, "proj", scope="/scope")
        tm.create_task(
            conn, "proj", "ticket",
            par_number=42,
            acceptance_command="python3 -c 'import sys; print(\"ACC240-RED\", file=sys.stderr); raise SystemExit(2)'",
        )
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    return worktree


async def _run_with_spy(monkeypatch, *, worktree: str):
    import app.merge_operations as operations

    calls = []

    async def fake_execute(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "state": "merged",
            "commit_point": "target_committed",
            "target_branch": "main",
            "target_before": "a" * 40,
            "target_after": "c" * 40,
            "worker_branch": "task-42/worker",
            "worker_head": "b" * 40,
            "conflicts": [],
            "commits_merged": 1,
            "lifecycle_status": {"ok": True},
            "rag_backfill_status": "accepted",
        }

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", fake_execute)
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(
            name="worker", scope="/scope", target="main",
        ),
        accepted=_accepted(worktree),
    )
    await operations._run_operation(operation_id)
    return operations.get_operation_result(operation_id), calls


@pytest.mark.asyncio
async def test_failing_registered_command_blocks_merge_executor(acc_db, monkeypatch):
    """Сегодня executor зовут всё равно — рассказ исполнителя подменяет приёмку."""
    result, calls = await _run_with_spy(monkeypatch, worktree=str(acc_db))
    assert calls == [], (
        "execute_merge_session вызван при красной приёмке — платформа не исполняет команду"
    )
    assert result["operation_state"] == "FAILED"
    assert result["commit_point"] == "NOT_REACHED"
    assert result["error"]["code"] == "ACCEPTANCE_FAILED"
    assert result["error"]["outcome_unknown"] is False
    output = (result.get("acceptance") or {}).get("output") or ""
    assert "ACC240-RED" in output, "красное без хвоста вывода — не копируем DEVNULL"
    assert result["acceptance"]["exit_code"] == 2


@pytest.mark.asyncio
async def test_inconclusive_is_not_passed_or_failed(acc_db, monkeypatch):
    import app.tm as tm

    with tm._conn() as conn:
        conn.execute(
            "UPDATE tm_tasks SET acceptance_command=? WHERE par_number=42",
            ("definitely-not-a-binary-240",),
        )
    result, calls = await _run_with_spy(monkeypatch, worktree=str(acc_db))
    assert calls == []
    assert result["operation_state"] == "FAILED"
    assert result["error"]["code"] == "ACCEPTANCE_INCONCLUSIVE"
    assert result["error"]["code"] != "ACCEPTANCE_FAILED"


def test_run_command_classifies_exit_and_timeout(tmp_path, monkeypatch):
    from app.acceptance import run_command, PASSED, FAILED, INCONCLUSIVE

    ok = run_command("python3 -c 'raise SystemExit(0)'", str(tmp_path))
    assert ok["status"] == PASSED
    bad = run_command("python3 -c 'raise SystemExit(3)'", str(tmp_path))
    assert bad["status"] == FAILED
    assert bad["exit_code"] == 3
    monkeypatch.setattr("app.acceptance.DEFAULT_TIMEOUT_SECONDS", 0.05)
    hung = run_command("python3 -c 'import time; time.sleep(5)'", str(tmp_path), timeout=0.05)
    assert hung["status"] == INCONCLUSIVE
    assert hung["reason"] == "timeout"
    missing = run_command("python3 -c 'pass'", str(tmp_path / "no-such-dir"))
    assert missing["status"] == INCONCLUSIVE
    assert missing["reason"] == "cwd_missing"


@pytest.mark.asyncio
async def test_passing_command_reaches_executor(acc_db, monkeypatch):
    import app.tm as tm

    with tm._conn() as conn:
        conn.execute(
            "UPDATE tm_tasks SET acceptance_command=? WHERE par_number=42",
            ("python3 -c 'raise SystemExit(0)'",),
        )
    result, calls = await _run_with_spy(monkeypatch, worktree=str(acc_db))
    assert len(calls) == 1
    assert result["operation_state"] == "SUCCEEDED"
    assert result["acceptance"]["status"] == "passed"


def test_done_narrative_is_not_consulted(tmp_path):
    """Вторая копия правды: текст отчёта не делает приёмку зелёной."""
    from app.acceptance import run_command, FAILED

    result = run_command(
        "python3 -c 'raise SystemExit(1)'",
        str(tmp_path),
    )
    assert result["status"] == FAILED
    # даже если рядом лежит «Tests: 7 passed» — раннер его не читает
    (tmp_path / "DONE.txt").write_text("DONE #240: Tests: 7 passed\n", encoding="utf-8")
    again = run_command("python3 -c 'raise SystemExit(1)'", str(tmp_path))
    assert again["status"] == FAILED


def test_description_is_never_used_as_acceptance_command(acc_db):
    """Исполняем только объявленное поле. description не читаем никогда."""
    import app.tm as tm
    from app.acceptance import SKIPPED, evaluate_for_merge

    with tm._conn() as conn:
        conn.execute(
            "UPDATE tm_tasks SET acceptance_command='', "
            "description=? WHERE par_number=42",
            ("python3 -c 'raise SystemExit(0)'",),
        )
    result = evaluate_for_merge(session_id="merge-session", worktree_path=str(acc_db))
    assert result["status"] == SKIPPED
    assert result["command"] == ""


async def _task_create_to_db(monkeypatch, *, role: str, command: str, title: str):
    import app.mcp_stdio as m
    import app.tm as tm

    monkeypatch.setattr(m, "ROLE", role)
    monkeypatch.setattr(m, "SCOPE", "/scope")

    async def write(method, path, json=None, **kwargs):
        body = json if json is not None else kwargs.get("json") or {}
        return tm.api_create_task(
            body.get("project") or "",
            body["title"],
            scope=body.get("scope") or "",
            acceptance_command=body.get("acceptance_command") or "",
        )

    monkeypatch.setattr(m, "_api", write)
    return await m.task_create(title=title, acceptance_command=command)


@pytest.mark.asyncio
async def test_worker_task_create_does_not_store_acceptance_command(acc_db, monkeypatch):
    import app.tm as tm

    await _task_create_to_db(
        monkeypatch, role="worker", command="true", title="from-worker",
    )
    with tm._conn() as conn:
        stored = conn.execute(
            "SELECT acceptance_command FROM tm_tasks WHERE title='from-worker'"
        ).fetchone()
    assert stored is not None
    assert stored["acceptance_command"] == "", (
        "воркер записал acceptance_command — самообъявление через тул"
    )


@pytest.mark.asyncio
async def test_orchestrator_task_create_stores_acceptance_command(acc_db, monkeypatch):
    import app.tm as tm

    await _task_create_to_db(
        monkeypatch, role="orchestrator", command="uv run python -m pytest -q tests/x.py",
        title="from-orch",
    )
    with tm._conn() as conn:
        stored = conn.execute(
            "SELECT acceptance_command FROM tm_tasks WHERE title='from-orch'"
        ).fetchone()
    assert stored is not None
    assert stored["acceptance_command"] == "uv run python -m pytest -q tests/x.py"


@pytest.mark.asyncio
async def test_public_update_corrects_command_used_by_merge_resolver(acc_db, monkeypatch):
    from starlette.requests import Request

    import app.tm as tm
    from app.acceptance import FAILED, PASSED, SKIPPED, evaluate_for_merge
    from app.routes.tm import TmTaskUpdate, tm_update_task

    request = Request({"type": "http", "headers": []})
    before_result = evaluate_for_merge(
        session_id="merge-session", worktree_path=str(acc_db),
    )
    assert before_result["status"] == FAILED
    with tm._conn() as conn:
        before = tm.get_task_by_par(conn, 42, "proj")

    def unexpected_privilege_check(_request):
        raise AssertionError("legacy empty acceptance_command must remain an omission")

    monkeypatch.setattr(
        "app.mcp_proof.caller_may_use_orchestrator_privilege",
        unexpected_privilege_check,
    )
    omitted = await tm_update_task(
        "42", TmTaskUpdate(acceptance_command=""), request, scope="/scope",
    )
    assert omitted["updated"] == []
    with tm._conn() as conn:
        after_omission = tm.get_task_by_par(conn, 42, "proj")
    assert after_omission["acceptance_command"] == before["acceptance_command"]
    assert after_omission["sync_revision"] == before["sync_revision"]
    assert after_omission["updated_at"] == before["updated_at"]

    monkeypatch.setattr(
        "app.mcp_proof.caller_may_use_orchestrator_privilege", lambda _request: True,
    )
    updated = await tm_update_task(
        "42",
        TmTaskUpdate(acceptance_command="python3 -c 'raise SystemExit(0)'"),
        request,
        scope="/scope",
    )
    assert updated["updated"] == ["acceptance_command"]
    assert set(updated) == {"par", "project", "updated"}
    with tm._conn() as conn:
        corrected = tm.get_task_by_par(conn, 42, "proj")
    assert corrected["sync_revision"] == before["sync_revision"] + 1
    assert corrected["updated_at"] != before["updated_at"]

    resolved = evaluate_for_merge(
        session_id="merge-session", worktree_path=str(acc_db),
    )
    assert resolved["status"] == PASSED
    assert resolved["command"] == "python3 -c 'raise SystemExit(0)'"

    cleared = await tm_update_task(
        "42", TmTaskUpdate(clear_acceptance_command=True), request, scope="/scope",
    )
    assert cleared["updated"] == ["acceptance_command"]
    assert evaluate_for_merge(
        session_id="merge-session", worktree_path=str(acc_db),
    )["status"] == SKIPPED


@pytest.mark.asyncio
async def test_public_acceptance_update_rejects_wrong_scope_and_task(acc_db, monkeypatch):
    import json

    from starlette.requests import Request

    import app.tm as tm
    from app.routes.tm import TmTaskUpdate, tm_update_task

    monkeypatch.setattr(
        "app.mcp_proof.caller_may_use_orchestrator_privilege", lambda _request: True,
    )
    request = Request({"type": "http", "headers": []})
    update = TmTaskUpdate(acceptance_command="python3 -c 'raise SystemExit(0)'")

    wrong_scope = await tm_update_task("42", update, request, scope="/wrong")
    assert wrong_scope.status_code == 400
    assert "no task project" in json.loads(wrong_scope.body)["error"]

    wrong_task = await tm_update_task("999", update, request, scope="/scope")
    assert wrong_task.status_code == 404
    assert "not found" in json.loads(wrong_task.body)["error"]

    with tm._conn() as conn:
        unchanged = tm.get_task_by_par(conn, 42, "proj")
    assert unchanged["acceptance_command"].startswith("python3 -c 'import sys")
    assert unchanged["sync_revision"] == 0
