"""#166 — сбойный merge → auto-switch на adhoc → повторный merge отдаёт SUCCEEDED впустую.

Стенд на НАСТОЯЩЕМ git: без реальных веток и коммитов «в цели ноль коммитов» не доказать.
"""

import asyncio
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _git(cwd, *args):
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def _commit(cwd, filename, text):
    Path(cwd, filename).write_text(text)
    _git(cwd, "add", filename)
    _git(cwd, "commit", "-m", f"add {filename}")
    return _git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def drift_env(tmp_path, monkeypatch):
    """Репозиторий + worktree воркера на feat/<slug>/<name>, сессия в БД, чистая merge_operations."""
    import app.db as dbmod
    import app.merge_operations as operations
    import app.workspace as workspace

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "merge.db")
    dbmod.init_db()
    operations._runner_tasks.clear()

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _commit(repo, "README.md", "base\n")

    worktree_root = tmp_path / "worktrees"
    monkeypatch.setattr(workspace, "WORKTREE_ROOT", worktree_root)

    worker = workspace.create_worktree(str(repo), "drift-worker")
    wt = Path(worker.path)
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")

    row = {
        "id": "drift-session",
        "name": "drift-worker",
        "scope": str(repo),
        "cwd": str(repo),
        "model": "model",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": str(wt),
        "branch": worker.branch,
        "base_branch": "main",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": "",
        "needs_switch": 0,
    }
    dbmod.save_session(row)
    return {
        "repo": repo,
        "wt": wt,
        "row": row,
        "feat_branch": worker.branch,
        "operations": operations,
        "db": dbmod,
    }


def _target_commit_count(repo) -> int:
    return int(_git(repo, "rev-list", "--count", "main"))


async def _merge(env, operation_id: str) -> dict:
    operations = env["operations"]
    result, _status = await operations.accept_merge_operation(
        operation_id=operation_id,
        name="drift-worker",
        scope=str(env["repo"]),
        target="main",
    )
    task = operations._runner_tasks.get(result["operation_id"])
    if task is None:
        # Отказ и дословный повтор — ЖИВОЙ ответ, в таблицу он не пишется.
        # Перечитывать запись здесь значило бы проверять не то, что увидит агент.
        return result
    await task
    stored = await asyncio.to_thread(
        operations.get_operation_result, result["operation_id"],
    )
    return stored or result


def _simulate_partial(env, operation_id: str) -> None:
    """Первая операция закончилась PARTIAL: git-мерж прошёл, пост-стадия упала.

    Пишется прямо в таблицу — воспроизводится СОСТОЯНИЕ после сбоя, а не его причина
    (причин у PARTIAL много, каскад #166 одинаков для всех).
    """
    operations, dbmod = env["operations"], env["db"]
    request = operations.normalize_request(
        name="drift-worker", scope=str(env["repo"]), target="main",
    )
    head = _git(env["wt"], "rev-parse", "HEAD")
    result = {
        "schema_version": 1,
        "operation_id": operation_id,
        "operation_state": "PARTIAL",
        "retryable": False,
        "commit_point": "REACHED",
        "git": {
            "status": "SUCCEEDED",
            "target_branch": "main",
            "target_before": "0" * 40,
            "target_after": "1" * 40,
            "worker_branch": env["feat_branch"],
            "worker_head": head,
            "conflicts": [],
            "commits_merged": 3,
            "head_drift": "SAME",
            "worker_head_pinned": head,
        },
        "task_links": {"status": "FAILED", "items": {}},
        "rag": {"status": "NOT_RUN"},
        "lifecycle": {"status": "SUCCEEDED"},
        "next_task": {"status": "NOT_REQUESTED"},
        "error": {
            "code": "POST_COMMIT_PARTIAL", "message": "task link failed",
            "status": None, "retryable": False, "request_id": operation_id,
            "retry_after_seconds": None, "outcome_unknown": False, "details": {},
        },
        "next_action": {
            "code": "FINALIZE_SAME_OPERATION",
            "message": "Finalize this operation; do not repeat or manually apply the Git merge.",
        },
    }
    now = datetime.now(timezone.utc).isoformat()
    with dbmod._conn() as connection:
        connection.execute(
            """INSERT INTO merge_operations (
                   operation_id, operation_type, session_id, scope, worker_name,
                   request_json, request_hash, dedupe_fingerprint,
                   accepted_worker_branch, accepted_worker_head,
                   accepted_base_branch, accepted_task_id, accepted_needs_switch,
                   state, commit_point, result_json, result_hash,
                   terminal_worker_branch, terminal_worker_head,
                   terminal_base_branch, terminal_task_id, terminal_needs_switch,
                   created_at, updated_at, finished_at, resolved_at
               ) VALUES (?, 'merge', ?, ?, ?, ?, ?, ?, ?, ?, 'main', '', 0,
                         'PARTIAL', 'REACHED', ?, ?, ?, ?, 'main', '', 1, ?, ?, ?, ?)""",
            (
                operation_id, "drift-session", str(env["repo"]), "drift-worker",
                operations._json(request), operations.request_hash(request),
                operations._hash({"seed": operation_id}),
                env["feat_branch"], head,
                operations._json(result), operations._hash(result),
                env["feat_branch"], head,
                now, now, now, now,
            ),
        )
    # needs_switch выставлен сбойным мержем — ровно это и запускает каскад
    row = dict(env["row"], needs_switch=1, task_id="")
    dbmod.save_session(row)
    env["row"] = row


async def _auto_switch(env) -> str:
    """Доставка сообщения idle-воркеру с needs_switch → adhoc-ветка (manager.py:781)."""
    import app.manager as mgr

    manager = mgr.SessionManager()
    session = manager._hydrate_row(env["db"].get_session("drift-session"))
    await manager._auto_switch_before_delivery(session)
    return _git(env["wt"], "rev-parse", "--abbrev-ref", "HEAD")


@pytest.mark.asyncio
async def test_merge_after_adhoc_switch_does_not_report_stale_success(drift_env):
    env = drift_env
    partial_id = str(uuid.uuid4())
    _simulate_partial(env, partial_id)

    adhoc = await _auto_switch(env)
    assert adhoc.startswith("adhoc-"), f"auto-switch не создал adhoc-ветку: {adhoc}"

    new_commit = _commit(env["wt"], "work.md", "работа воркера после switch\n")
    before = _target_commit_count(env["repo"])

    result = await _merge(env, str(uuid.uuid4()))
    after = _target_commit_count(env["repo"])

    # Страж F1: новый operation_id после переезда обязан слить ФАКТИЧЕСКУЮ ветку
    # (зелёный на main — ветка берётся из worktree, а не из схемы имени).
    if result["operation_state"] == "SUCCEEDED":
        assert after > before, (
            f"SUCCEEDED при нуле смерженного: operation_id={result['operation_id']}, "
            f"worker_branch={result['git']['worker_branch']}, "
            f"worker_head={result['git']['worker_head']}, "
            f"фактическая ветка={adhoc}, фактический HEAD={new_commit}, "
            f"коммитов в main до={before} после={after}"
        )
        assert result["git"]["worker_branch"] == adhoc
    else:
        # Честный отказ обязан назвать ФАКТИЧЕСКУЮ ветку — иначе агенту нечего искать.
        detail = env["operations"]._json(result)
        assert adhoc in detail, f"отказ не называет фактическую ветку {adhoc}: {detail}"


@pytest.mark.asyncio
async def test_stale_operation_is_not_reused_after_branch_change(drift_env):
    """Страж F2: отпечаток обязан ловить смену ветки, а не только HEAD (зелёный на main)."""
    env = drift_env
    partial_id = str(uuid.uuid4())
    _simulate_partial(env, partial_id)
    await _auto_switch(env)
    _commit(env["wt"], "work.md", "работа\n")

    result = await _merge(env, str(uuid.uuid4()))
    assert result["operation_id"] != partial_id, (
        "возвращена СТАРАЯ операция после смены ветки воркера"
    )



@pytest.mark.asyncio
async def test_replay_of_same_operation_id_after_worker_moved_is_not_success(drift_env):
    """#166: повтор с ТЕМ ЖЕ operation_id после переезда воркера на adhoc-ветку.

    Докстринг merge_worker прямо велит повторять с тем же operation_id, а
    `accept_merge_operation` на этом пути отдаёт сохранённый результат ДОСЛОВНО,
    ни разу не сверившись с воркером. Ответ несёт `git.status=SUCCEEDED` и
    `commits_merged=3` при нуле фактически смерженного.
    """
    env = drift_env
    operation_id = str(uuid.uuid4())
    _simulate_partial(env, operation_id)

    adhoc = await _auto_switch(env)
    assert adhoc.startswith("adhoc-")
    new_commit = _commit(env["wt"], "work.md", "работа воркера после switch\n")

    before = _target_commit_count(env["repo"])
    result = await _merge(env, operation_id)
    after = _target_commit_count(env["repo"])

    assert after == before, "стенд не тот: повтор что-то смержил"
    detail = env["operations"]._json(result)

    # 1. Ответ не имеет права отдавать git.status=SUCCEEDED, когда в цели ноль коммитов.
    assert result["git"]["status"] != "SUCCEEDED", (
        f"git.status=SUCCEEDED при нуле смерженного: worker_branch="
        f"{result['git']['worker_branch']}, worker_head={result['git']['worker_head']}, "
        f"фактическая ветка={adhoc}, фактический HEAD={new_commit}, "
        f"main до={before} после={after}"
    )
    # 2. Ответ обязан назвать ФАКТИЧЕСКУЮ ветку — иначе агенту нечего искать.
    assert adhoc in detail, f"ответ не называет фактическую ветку {adhoc}: {detail}"
    # 3. next_action не имеет права запрещать проверку артефакта.
    assert "do not repeat or manually apply" not in detail.lower(), (
        f"ответ запрещает единственный рабочий обход: {result['next_action']}"
    )


@pytest.mark.asyncio
async def test_replay_of_same_operation_id_without_drift_stays_idempotent(drift_env):
    """Воркер НЕ уехал → повтор обязан отдать тот же результат дословно.

    Иначе протокол STILL RUNNING («повтори с тем же operation_id») превращается
    в дубли мержей.
    """
    env = drift_env
    operation_id = str(uuid.uuid4())
    _simulate_partial(env, operation_id)

    first = await _merge(env, operation_id)
    second = await _merge(env, operation_id)

    assert first == second
    assert second["operation_id"] == operation_id
    assert second["operation_state"] == "PARTIAL"
    assert second["git"]["commits_merged"] == 3


@pytest.mark.asyncio
async def test_replay_refuses_when_worker_cannot_be_inspected(drift_env):
    """Fail-closed во ВТОРУЮ сторону: не смогли опросить воркера → отказ, не успех."""
    env = drift_env
    operation_id = str(uuid.uuid4())
    _simulate_partial(env, operation_id)

    # worktree исчез — опросить нечего
    row = dict(env["db"].get_session("drift-session"), worktree_path=str(env["wt"] / "gone"))
    env["db"].save_session(row)

    result = await _merge(env, operation_id)

    assert result["operation_state"] == "FAILED"
    assert result["git"]["status"] != "SUCCEEDED"
    assert result["error"]["code"] == "REPLAY_VERIFICATION_FAILED"


@pytest.mark.asyncio
async def test_refusal_never_reports_git_status_succeeded(drift_env):
    """`git.status` — поле, по которому читали инцидент. На отказе оно обязано быть FAILED.

    Envelope и внутреннее поле разъезжаются (в стухшем ответе было PARTIAL снаружи и
    SUCCEEDED внутри), поэтому проверяется именно внутреннее.
    """
    env = drift_env
    for drift in ("branch", "head"):
        operation_id = str(uuid.uuid4())
        _simulate_partial(env, operation_id)
        if drift == "branch":
            moved = await _auto_switch(env)      # воркер уехал на другую ветку
            assert moved.startswith("adhoc-")
        else:
            _commit(env["wt"], "more.md", "ещё\n")  # та же ветка, новый HEAD

        result = await _merge(env, operation_id)

        assert result["operation_state"] == "FAILED"
        assert result["git"]["status"] == "FAILED", (
            f"git.status={result['git']['status']} на отказе: {env['operations']._json(result)}"
        )
        assert int(result["git"].get("commits_merged") or 0) == 0
        with env["db"]._conn() as connection:
            connection.execute("DELETE FROM merge_operations")


@pytest.mark.asyncio
async def test_finalize_action_no_longer_forbids_verification(drift_env):
    """B: запрет на ручной мерж остаётся, запрет на ПРОВЕРКУ артефакта уходит."""
    import app.merge_operations as ops

    raw = {
        "ok": True, "state": "partial", "commit_point": "target_committed",
        "target_branch": "main", "target_before": "a" * 40, "target_after": "b" * 40,
        "worker_branch": "feat/x/worker", "worker_head": "c" * 40, "commits_merged": 2,
        "linked_tasks": {"166": {"ok": False, "error": "boom"}},
    }
    result = ops.normalize_merge_result(
        "op", raw, ops.normalize_request(name="w", scope="/s", target="main"),
    )
    message = result["next_action"]["message"]
    assert result["operation_state"] == "PARTIAL"
    assert "do not manually apply the Git merge" in message
    assert "do not repeat or manually apply" not in message
    assert "worker_wip" in message

