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


REPORTED_LITERAL_SHELL_COMMAND = (
    'test "$(find . -type f | wc -l)" -eq 7 && python3 check.py'
)


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
    empty_executable = run_command("''", str(tmp_path))
    assert empty_executable["status"] == INCONCLUSIVE
    assert empty_executable["reason"] == "invalid_acceptance_command"
    assert empty_executable["validation_error"] == "empty_executable"
    assert empty_executable["guidance"] == "FIX_ACCEPTANCE_THEN_RETRY"


def test_parser_preserves_safe_argv_and_requires_structural_shell():
    from app.acceptance import AcceptanceCommandError, parse_acceptance_command

    assert parse_acceptance_command(
        "python3 -c 'print(\"ordinary argument with spaces\")'"
    ) == ["python3", "-c", 'print("ordinary argument with spaces")']
    assert parse_acceptance_command(
        "printf '%s\\n' 'quoted | ordinary > argument'"
    ) == ["printf", "%s\\n", "quoted | ordinary > argument"]
    assert parse_acceptance_command(
        "printf '%s\\n' '$HOME && literal > text'"
    ) == ["printf", "%s\\n", "$HOME && literal > text"]
    assert parse_acceptance_command("./bash --check") == ["./bash", "--check"]

    script = 'test "$(find . -type f | wc -l)" -eq 7 && python3 check.py'
    assert parse_acceptance_command(f"bash -lc '{script}'") == [
        "bash", "-lc", script,
    ]
    assert parse_acceptance_command("/bin/sh -c 'exit 0'") == [
        "/bin/sh", "-c", "exit 0",
    ]

    with pytest.raises(AcceptanceCommandError) as reported:
        parse_acceptance_command(REPORTED_LITERAL_SHELL_COMMAND)
    assert reported.value.reason == "shell_syntax_requires_explicit_shell"
    assert "literal-argv" in str(reported.value)
    assert "bash -lc" in str(reported.value)

    for apparent_shell in (
        "python3 check.py && python3 other.py",
        "python3 check.py || true",
        "printf x | wc -c",
        "python3 check.py; true",
        "python3 check.py > result.txt",
        "python3 check.py 2>> result.txt",
        "echo $HOME",
        'echo "${HOME}"',
        "echo `pwd`",
    ):
        with pytest.raises(AcceptanceCommandError) as rejected:
            parse_acceptance_command(apparent_shell)
        assert rejected.value.reason == "shell_syntax_requires_explicit_shell"

    with pytest.raises(AcceptanceCommandError) as malformed:
        parse_acceptance_command("python3 -c 'unterminated")
    assert malformed.value.reason == "malformed_quoting"

    with pytest.raises(AcceptanceCommandError) as empty_executable:
        parse_acceptance_command("''")
    assert empty_executable.value.reason == "empty_executable"

    for command in (
        "bash -c",
        "sh -lc ''",
        "bash script.sh",
        "bash -lc 'true' extra",
        "/bin/bash script.sh",
    ):
        with pytest.raises(AcceptanceCommandError) as invalid_shell:
            parse_acceptance_command(command)
        assert invalid_shell.value.reason == "invalid_shell_wrapper"


@pytest.mark.parametrize(
    "invalid_command",
    [REPORTED_LITERAL_SHELL_COMMAND, "python3 -c 'unterminated"],
)
def test_create_and_update_reject_invalid_command_before_db_write(
    acc_db, invalid_command,
):
    import app.tm as tm
    from app.acceptance import AcceptanceCommandError

    with tm._conn() as conn:
        before = tm.get_task_by_par(conn, 42, "proj")

        with pytest.raises(AcceptanceCommandError):
            tm.create_task(
                conn,
                "proj",
                "invalid-create",
                par_number=384,
                acceptance_command=invalid_command,
            )
        assert conn.execute(
            "SELECT 1 FROM tm_tasks WHERE title='invalid-create'"
        ).fetchone() is None

        with pytest.raises(AcceptanceCommandError):
            tm.update_task(
                conn,
                before["id"],
                title="must-not-change",
                acceptance_command=invalid_command,
            )
        after = tm.get_task_by_id(conn, before["id"])

    assert after["title"] == before["title"]
    assert after["acceptance_command"] == before["acceptance_command"]
    assert after["sync_revision"] == before["sync_revision"]


def _install_rejecting_parser(monkeypatch):
    from app import acceptance

    def reject(_command):
        raise acceptance.AcceptanceCommandError(
            "sentinel_validator", "sentinel validator rejection",
        )

    monkeypatch.setattr(acceptance, "parse_acceptance_command", reject)
    return acceptance


def test_create_is_wired_to_canonical_validator(acc_db, monkeypatch):
    import app.tm as tm

    acceptance = _install_rejecting_parser(monkeypatch)
    with tm._conn() as conn:
        with pytest.raises(acceptance.AcceptanceCommandError, match="sentinel"):
            tm.create_task(
                conn, "proj", "sentinel-create", par_number=384,
                acceptance_command="true",
            )
        assert conn.execute(
            "SELECT 1 FROM tm_tasks WHERE title='sentinel-create'"
        ).fetchone() is None


def test_update_is_wired_to_canonical_validator(acc_db, monkeypatch):
    import app.tm as tm

    acceptance = _install_rejecting_parser(monkeypatch)
    with tm._conn() as conn:
        before = tm.get_task_by_par(conn, 42, "proj")
        with pytest.raises(acceptance.AcceptanceCommandError, match="sentinel"):
            tm.update_task(conn, before["id"], acceptance_command="true")
        after = tm.get_task_by_id(conn, before["id"])

    assert after["acceptance_command"] == before["acceptance_command"]
    assert after["sync_revision"] == before["sync_revision"]


def test_runner_is_wired_to_canonical_validator(acc_db, monkeypatch):
    acceptance = _install_rejecting_parser(monkeypatch)

    def must_not_execute(*_args, **_kwargs):
        raise AssertionError("runner bypassed canonical acceptance parser")

    monkeypatch.setattr(acceptance.subprocess, "run", must_not_execute)
    result = acceptance.run_command("true", str(acc_db))
    assert result["status"] == acceptance.INCONCLUSIVE
    assert result["reason"] == "invalid_acceptance_command"
    assert result["validation_error"] == "sentinel_validator"
    assert result["guidance"] == "FIX_ACCEPTANCE_THEN_RETRY"


@pytest.mark.asyncio
async def test_existing_invalid_command_blocks_merge_with_repair_guidance(
    acc_db, monkeypatch,
):
    import app.tm as tm

    with tm._conn() as conn:
        conn.execute(
            "UPDATE tm_tasks SET acceptance_command=? WHERE par_number=42",
            (REPORTED_LITERAL_SHELL_COMMAND,),
        )

    result, calls = await _run_with_spy(monkeypatch, worktree=str(acc_db))

    assert calls == []
    assert result["operation_state"] == "FAILED"
    assert result["error"]["code"] == "ACCEPTANCE_INCONCLUSIVE"
    assert result["next_action"]["code"] == "FIX_ACCEPTANCE_THEN_RETRY"
    assert result["acceptance"]["reason"] == "invalid_acceptance_command"
    assert (
        result["acceptance"]["validation_error"]
        == "shell_syntax_requires_explicit_shell"
    )
    assert result["acceptance"]["guidance"] == "FIX_ACCEPTANCE_THEN_RETRY"
    assert "literal-argv" in result["acceptance"]["output"]
    assert "bash -lc" in result["acceptance"]["output"]


@pytest.mark.asyncio
async def test_public_create_and_update_reject_before_persistence(
    acc_db, monkeypatch,
):
    import json

    from starlette.requests import Request

    import app.tm as tm
    from app.routes.tm import (
        TmTaskCreate,
        TmTaskUpdate,
        tm_create_task,
        tm_update_task,
    )

    monkeypatch.setattr(
        "app.mcp_proof.caller_may_use_orchestrator_privilege", lambda _request: True,
    )
    request = Request({"type": "http", "headers": []})

    created = await tm_create_task(
        TmTaskCreate(
            title="invalid-public-create",
            scope="/scope",
            acceptance_command=REPORTED_LITERAL_SHELL_COMMAND,
        ),
        request,
    )
    assert created.status_code == 400
    create_error = json.loads(created.body)
    assert create_error["reason"] == "shell_syntax_requires_explicit_shell"
    assert "bash -lc" in create_error["error"]

    with tm._conn() as conn:
        before = tm.get_task_by_par(conn, 42, "proj")
        assert conn.execute(
            "SELECT 1 FROM tm_tasks WHERE title='invalid-public-create'"
        ).fetchone() is None

    updated = await tm_update_task(
        "42",
        TmTaskUpdate(
            title="must-not-change",
            acceptance_command=REPORTED_LITERAL_SHELL_COMMAND,
        ),
        request,
        scope="/scope",
    )
    assert updated.status_code == 400
    update_error = json.loads(updated.body)
    assert update_error["reason"] == "shell_syntax_requires_explicit_shell"

    with tm._conn() as conn:
        after = tm.get_task_by_par(conn, 42, "proj")
    assert after["title"] == before["title"]
    assert after["acceptance_command"] == before["acceptance_command"]
    assert after["sync_revision"] == before["sync_revision"]


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
