"""#27 — авто-switch перед доставкой: имя без цикла и запрет усыновления чужой ветки.

Оба слоя проверяются на настоящем git. Тесты печатают ФАКТ попадания в спорную ветку
(что именно вернул workspace), а не только зелёный статус: в #17 я уже утверждал, что эта
ветка недостижима, и ошибся.
"""
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
    return repo


@pytest.fixture
def wt_root(tmp_path, monkeypatch):
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", root)
    return root


@pytest.fixture
def db(tmp_path, monkeypatch):
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()
    return dbmod


def _row(sid, scope, worktree, branch):
    return {
        "id": sid, "name": "worker", "scope": scope, "cwd": scope, "model": "m",
        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": worktree, "branch": branch, "base_branch": "main",
        "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 1,
    }


def _branch(cwd):
    return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


class TestAdhocName:
    def test_two_names_in_one_second_differ(self, monkeypatch):
        from app.manager import next_adhoc_branch

        monkeypatch.setattr(time, "time", lambda: 1785775458.0)
        first, second = next_adhoc_branch("worker"), next_adhoc_branch("worker")
        assert first != second, (first, second)

    def test_cycle_of_the_old_generator_is_gone(self, monkeypatch):
        """Старое имя повторялось каждые 10**6 с (11.57 суток) — новое не повторяется."""
        from app.manager import next_adhoc_branch

        t0 = 1785775458
        old = lambda t: f"adhoc-{str(int(t))[-6:]}/worker"  # noqa: E731 — снимок прежней формы
        assert old(t0) == old(t0 + 10**6), "предпосылка теста: старый генератор цикличен"

        monkeypatch.setattr(time, "time", lambda: float(t0))
        now = next_adhoc_branch("worker")
        monkeypatch.setattr(time, "time", lambda: float(t0 + 10**6))
        later = next_adhoc_branch("worker")
        assert now != later
        assert now.split("-")[1] != later.split("-")[1]

    def test_name_is_a_valid_git_branch(self, monkeypatch, git_repo):
        from app.manager import next_adhoc_branch

        name = next_adhoc_branch("feat-instant")
        assert subprocess.run(["git", "check-ref-format", "--branch", name],
                              cwd=git_repo, capture_output=True).returncode == 0


async def _auto_switch(db, git_repo, wt, sid):
    """Прогнать авто-switch на детач-сессии и вернуть (исключение, результат workspace)."""
    import app.manager as mgr
    import app.workspace as ws

    manager = mgr.SessionManager()
    session = manager._hydrate_row(db.get_session(sid))
    session.needs_switch = True
    seen = {}
    original = ws.switch_worktree_branch

    def spy(*a, **k):
        out = original(*a, **k)
        seen["result"] = out
        return out

    ws.switch_worktree_branch = spy
    try:
        error = ""
        try:
            await manager._auto_switch_before_delivery(session)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
    finally:
        ws.switch_worktree_branch = original
    return error, seen.get("result")


@pytest.mark.asyncio
async def test_existing_branch_is_never_adopted(git_repo, wt_root, db, monkeypatch):
    """E2: имя занято чужой веткой с чужой работой. Переселять нельзя даже успешно."""
    import app.manager as mgr
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    stolen = "adhoc-1785700000-1/worker"
    subprocess.run(["git", "checkout", "-b", stolen], cwd=wt.path, capture_output=True, check=True)
    (Path(wt.path) / "old.txt").write_text("чужая работа 11 суток назад")
    subprocess.run(["git", "add", "-A"], cwd=wt.path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "чужая работа"], cwd=wt.path,
                   capture_output=True, check=True)
    subprocess.run(["git", "checkout", "task-17/worker"], cwd=wt.path,
                   capture_output=True, check=True)

    sid = str(uuid.uuid4())
    db.save_session(_row(sid, str(git_repo), wt.path, "task-17/worker"))
    monkeypatch.setattr(mgr, "next_adhoc_branch", lambda _name: stolen)

    error, result = await _auto_switch(db, git_repo, wt, sid)
    print("\nфакт попадания — результат workspace:", result)
    print("исключение:", error)

    assert result is not None and result["state"] == "target_branch_exists"
    assert "refusing to adopt someone else's history" in result["error"]
    assert stolen in result["error"] and "last commit" in result["error"]
    assert error.startswith("RuntimeError: auto-switch failed:")
    assert _branch(wt.path) == "task-17/worker"
    assert not (Path(wt.path) / "old.txt").exists(), "чужой файл приехал в рабочую копию"
    assert db.get_session(sid)["needs_switch"] == 1


@pytest.mark.asyncio
async def test_branch_existing_only_as_ref_is_refused(git_repo, wt_root, db, monkeypatch):
    """Путь 4: ветка осталась в ref'ах после убитого воркера, рабочей копии у неё нет."""
    import app.manager as mgr
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    orphan = "adhoc-1785700000-2/worker"
    subprocess.run(["git", "branch", orphan, "main"], cwd=git_repo,
                   capture_output=True, check=True)
    sid = str(uuid.uuid4())
    db.save_session(_row(sid, str(git_repo), wt.path, "task-17/worker"))
    monkeypatch.setattr(mgr, "next_adhoc_branch", lambda _name: orphan)

    error, result = await _auto_switch(db, git_repo, wt, sid)
    print("\nпуть 4 — результат workspace:", result)
    assert result["state"] == "target_branch_exists"
    assert error.startswith("RuntimeError: auto-switch failed:")
    assert _branch(wt.path) == "task-17/worker"


@pytest.mark.asyncio
async def test_branch_checked_out_in_another_worktree_is_refused(
    git_repo, wt_root, db, monkeypatch,
):
    """Путь 3: имя занято веткой, выкаченной в ЧУЖОМ worktree."""
    import app.manager as mgr
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    other = create_worktree(str(git_repo), "neighbour", "18", base_branch="main")
    sid = str(uuid.uuid4())
    db.save_session(_row(sid, str(git_repo), wt.path, "task-17/worker"))
    monkeypatch.setattr(mgr, "next_adhoc_branch", lambda _name: other.branch)

    error, result = await _auto_switch(db, git_repo, wt, sid)
    print("\nпуть 3 — результат workspace:", result)
    assert result["ok"] is False
    assert "another worktree" in result["error"] or "already exists" in result["error"]
    assert _branch(wt.path) == "task-17/worker"
    assert db.get_session(sid)["needs_switch"] == 1


@pytest.mark.asyncio
async def test_own_current_branch_stays_idempotent_success(git_repo, wt_root, db, monkeypatch):
    """E1 из #17 не должен пострадать от второго слоя: своя текущая ветка — успех."""
    import app.manager as mgr
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    mine = "adhoc-1785700000-3/worker"
    subprocess.run(["git", "checkout", "-b", mine], cwd=wt.path, capture_output=True, check=True)
    sid = str(uuid.uuid4())
    db.save_session(_row(sid, str(git_repo), wt.path, "task-17/worker"))
    monkeypatch.setattr(mgr, "next_adhoc_branch", lambda _name: mine)

    error, result = await _auto_switch(db, git_repo, wt, sid)
    print("\nE1 после второго слоя — результат workspace:", result, "| исключение:", error or "нет")
    assert result["ok"] is True and result["state"] == "already_on_branch"
    assert error == ""
    assert db.get_session(sid)["needs_switch"] == 0
    assert db.get_session(sid)["branch"] == mine


@pytest.mark.asyncio
async def test_auto_switch_clears_owned_dirs_and_prompt(git_repo, wt_root, db, monkeypatch):
    from app.manager import SessionManager
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
    old_prompt = "BASE" + SessionManager._ownership_prompt(["old/path"])
    sid = str(uuid.uuid4())
    row = _row(sid, str(git_repo), wt.path, "task-17/worker")
    row.update(
        task_id="17", system_prompt=old_prompt,
        prompt_overlay=SessionManager._ownership_prompt(["old/path"]),
        owned_dirs='["old/path"]',
    )
    db.save_session(row)

    error, result = await _auto_switch(db, git_repo, wt, sid)

    assert error == ""
    assert result["ok"] is True
    saved = db.get_session(sid)
    assert saved["owned_dirs"] in (None, "", "[]")
    assert "old/path" not in saved["system_prompt"]


class TestLockWaitIsVisible:
    """T3: ожидание лока обязано быть видно снаружи и кончаться раньше клиентского таймаута."""

    @pytest.mark.asyncio
    async def test_wait_is_logged_and_reported(self, git_repo, wt_root, db, monkeypatch, caplog):
        import asyncio
        import json
        import logging

        import app.manager as mgr
        import app.routes.sessions as S
        import app.tm as tm
        from app.workspace import create_worktree

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        sid = str(uuid.uuid4())
        row = _row(sid, str(git_repo), wt.path, "task-17/worker")
        row["needs_switch"] = 0
        db.save_session(row)
        manager = mgr.SessionManager()
        session = manager._hydrate_row(db.get_session(sid))
        monkeypatch.setattr(S.manager, "get_by_name", lambda *_a: session)
        monkeypatch.setattr(S.manager, "get_session_lock", manager.get_session_lock)
        monkeypatch.setattr(S.manager, "persist_lifecycle", manager.persist_lifecycle)
        monkeypatch.setattr(tm, "resolve_scoped_task_identity",
                            lambda scope, task_id: {"par_number": 27, "project_id": "p"})
        monkeypatch.setattr(tm, "api_update_task_if_current", lambda *a, **k: {"ok": True})

        lock = manager.get_session_lock(session.id)

        async def hold():
            async with lock:
                await asyncio.sleep(1.0)

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0.05)
        with caplog.at_level(logging.WARNING):
            resp = await S.switch_branch(
                "worker", {"scope": str(git_repo), "task_id": "27", "force": True},
            )
        await holder
        body = resp if isinstance(resp, dict) else json.loads(resp.body)
        print("\nT3 ответ:", {k: body[k] for k in ("ok", "waited_seconds") if k in body})
        print("T3 в журнале:", [r.getMessage() for r in caplog.records if "session lock" in r.getMessage()])
        # Порог с запасом: лок держится 1.0 с, но замер идёт по wall-clock на живой
        # машине и при нагрузке даёт 0.88. Проверяем ФАКТ заметного ожидания, а не
        # точность секундомера — иначе тест меряет соседей, а не код.
        assert body["waited_seconds"] >= 0.5
        assert any("waited" in r.getMessage() and "session lock" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_gives_up_before_client_timeout_with_actionable_409(
        self, git_repo, wt_root, db, monkeypatch,
    ):
        import asyncio
        import json

        import app.manager as mgr
        import app.routes.sessions as S
        import app.tm as tm
        from app.workspace import create_worktree

        wt = create_worktree(str(git_repo), "worker", "17", base_branch="main")
        sid = str(uuid.uuid4())
        row = _row(sid, str(git_repo), wt.path, "task-17/worker")
        row["needs_switch"] = 0
        db.save_session(row)
        manager = mgr.SessionManager()
        session = manager._hydrate_row(db.get_session(sid))
        monkeypatch.setattr(S.manager, "get_by_name", lambda *_a: session)
        monkeypatch.setattr(S.manager, "get_session_lock", manager.get_session_lock)
        monkeypatch.setattr(tm, "resolve_scoped_task_identity",
                            lambda scope, task_id: {"par_number": 27, "project_id": "p"})
        # Предел ожидания в бою 25 с — заведомо меньше клиентских 30 с. В тесте укорачиваем
        # сам предел, а не спим 25 секунд: проверяем поведение, а не терпение.
        monkeypatch.setattr(mgr, "LOCK_WAIT_LIMIT_SECONDS", 0.3)

        lock = manager.get_session_lock(session.id)
        released = asyncio.Event()

        async def hold():
            async with lock:
                await asyncio.sleep(1.5)
            released.set()

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0.05)
        t0 = time.monotonic()
        resp = await S.switch_branch(
            "worker", {"scope": str(git_repo), "task_id": "27", "force": True},
        )
        gave_up_after = time.monotonic() - t0
        body = json.loads(resp.body)
        await holder
        print(f"\nT3 отказ за {gave_up_after:.2f} с: {body['error']}")
        assert resp.status_code == 409
        assert gave_up_after < 1.0, "отказ обязан прийти раньше, чем клиент отвалится"
        assert "retry switch_worker_branch" in body["error"]
        assert "Nothing was changed" in body["error"]
