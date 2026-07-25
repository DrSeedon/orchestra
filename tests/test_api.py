"""TDD tests for main.py — HTTP API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    import app.routes.system as sysmod
    monkeypatch.setattr(sysmod, "_ALLOWED_ROOTS", ["/tmp", str(tmp_path)])
    from app.db import init_db
    init_db()


@pytest.fixture
def client(db):
    from tests.conftest import make_backend_mock
    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import app, manager
        manager.sessions.clear()
        with TestClient(app) as c:
            yield c


class TestDashboard:
    def test_root_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


class TestCreateSession:
    def test_201(self, client):
        r = client.post("/api/sessions", json={
            "name": "worker-1",
            "scope": "/tmp",
            "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "worker-1"
        assert "id" in data

    def test_422_bad_name(self, client):
        r = client.post("/api/sessions", json={
            "name": "worker/bad",
            "scope": "/tmp",
            "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]",
        })
        assert r.status_code == 422

    def test_422_empty_name(self, client):
        r = client.post("/api/sessions", json={
            "name": "",
            "scope": "/tmp",
            "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]",
        })
        assert r.status_code == 422

    def test_409_duplicate(self, client):
        body = {"name": "w1", "scope": "/tmp", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"}
        r1 = client.post("/api/sessions", json=body)
        assert r1.status_code == 201
        r2 = client.post("/api/sessions", json=body)
        assert r2.status_code == 409

    def test_422_bad_cwd(self, client):
        r = client.post("/api/sessions", json={
            "name": "w1",
            "scope": "/tmp",
            "cwd": "/nonexistent/path",
            "model": "claude-sonnet-5[1m]",
        })
        assert r.status_code == 422


class TestGetSessions:
    def test_list_empty(self, client):
        r = client.get("/api/sessions")
        assert r.status_code == 200
        # May contain bootstrap orchestrator from startup — just check it's a list
        assert isinstance(r.json(), list)

    def test_list_with_scope(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/a", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        client.post("/api/sessions", json={"name": "w2", "scope": "/b", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.get("/api/sessions", params={"scope": "/a"})
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["name"] == "w1"

    def test_get_by_name(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.get("/api/sessions/w1", params={"scope": "/s"})
        assert r.status_code == 200
        assert r.json()["name"] == "w1"

    def test_get_404(self, client):
        r = client.get("/api/sessions/nonexistent", params={"scope": "/s"})
        assert r.status_code == 404


class TestSendMessage:
    def test_send(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.post("/api/sessions/w1/send", json={"message": "hello", "scope": "/s"})
        assert r.status_code == 200

    def test_send_404(self, client):
        r = client.post("/api/sessions/ghost/send", json={"message": "hi", "scope": "/s"})
        assert r.status_code == 404


class TestInterrupt:
    def test_interrupt(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.post("/api/sessions/w1/interrupt", json={"scope": "/s"})
        assert r.status_code == 200


class TestDeleteSession:
    def test_delete(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.delete("/api/sessions/w1", params={"scope": "/s"})
        assert r.status_code == 200
        r2 = client.get("/api/sessions/w1", params={"scope": "/s"})
        assert r2.status_code == 404

    def test_delete_404(self, client):
        r = client.delete("/api/sessions/ghost", params={"scope": "/s"})
        assert r.status_code == 404


class TestLogs:
    def test_logs_empty(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-5[1m]"})
        r = client.get("/api/sessions/w1/logs", params={"scope": "/s"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_logs_404(self, client):
        r = client.get("/api/sessions/ghost/logs", params={"scope": "/s"})
        assert r.status_code == 404


class TestStats:
    def test_stats(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_sessions" in data

    def test_stats_with_scope(self, client):
        r = client.get("/api/stats", params={"scope": "/s"})
        assert r.status_code == 200


class TestTestLockApi:
    def test_acquire_and_status_and_release(self, client):
        # свободен
        st = client.get("/api/test-lock", params={"scope": "/s"})
        assert st.status_code == 200
        assert st.json()["held"] is False

        # захват
        r = client.post("/api/test-lock/acquire", json={"scope": "/s", "holder": "coder-a", "reason": "suite"})
        assert r.status_code == 200
        assert r.json()["acquired"] is True

        # занято другим
        r2 = client.post("/api/test-lock/acquire", json={"scope": "/s", "holder": "coder-b", "reason": "x"})
        assert r2.status_code == 200
        assert r2.json()["acquired"] is False
        assert r2.json()["holder"] == "coder-a"

        # статус
        st2 = client.get("/api/test-lock", params={"scope": "/s"})
        assert st2.status_code == 200
        assert st2.json()["held"] is True
        assert st2.json()["holder"] == "coder-a"

        # релиз
        rel = client.post("/api/test-lock/release", json={"scope": "/s", "holder": "coder-a"})
        assert rel.status_code == 200
        assert rel.json()["released"] is True


class TestOrchestrators:
    def test_list_orchestrators(self, client):
        r = client.get("/api/orchestrators")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_orchestrators_exposes_runtime_cache_policy(self, client):
        for name, model in (
            ("claude-orch", "claude-opus-4-8[1m]"),
            ("codex-orch", "gpt-5.6-sol"),
        ):
            response = client.post("/api/sessions", json={
                "name": name,
                "scope": f"/tmp/{name}",
                "cwd": "/tmp",
                "model": model,
                "is_orchestrator": True,
                "role": "orchestrator",
            })
            assert response.status_code == 201

        rows = {row["name"]: row for row in client.get("/api/orchestrators").json()}
        assert rows["claude-orch"]["cache_ttl_seconds"] == 3600
        assert rows["claude-orch"]["cache_ttl_approximate"] is False
        assert rows["codex-orch"]["cache_ttl_seconds"] == 1800
        assert rows["codex-orch"]["cache_ttl_approximate"] is True


def test_create_request_accepts_base_branch():
    from app.routes.sessions import CreateSessionRequest
    req = CreateSessionRequest(name="w1", cwd="/tmp", model="claude-sonnet-5[1m]",
                               use_worktree=True, repo_path="/tmp",
                               base_branch="feature/auth")
    assert req.base_branch == "feature/auth"


def test_create_request_base_branch_default_empty():
    # Sentinel "" = авто-резолв базовой ветки по стратегии пайплайна (DESIGN §10).
    # Резолв в "main" происходит в manager/workspace, а не в дефолте запроса.
    from app.routes.sessions import CreateSessionRequest
    req = CreateSessionRequest(name="w1", cwd="/tmp", model="claude-sonnet-5[1m]")
    assert req.base_branch == ""


@pytest.mark.asyncio
async def test_merge_endpoint_passes_target(db, monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    import asyncio
    captured = {}

    def fake_merge(worktree_path, repo_path, target_branch="main"):
        captured["target_branch"] = target_branch
        return {"ok": True, "commits_merged": 1, "branch": "task-1/w", "merged_commits": {}}
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)

    class FakeSession:
        loaded = True
        class _S:
            value = "idle"
        status = _S()
        _lifecycle_lock = asyncio.Lock()
        worktree_path = "/wt"
        scope = "/s"
        id = "sid"
        name = "w"
        def _persist(self):
            pass
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: FakeSession())

    res = await sessmod.merge_session("w", {"scope": "/s", "target": "feature/auth"})
    assert captured["target_branch"] == "feature/auth"


@pytest.mark.asyncio
async def test_merge_waits_for_running_worker_to_finish_turn(db, monkeypatch):
    import asyncio
    import app.main as mainmod
    import app.routes.sessions as sessmod

    class Status:
        value = "running"

    class FakeSession:
        loaded = True
        status = Status()
        _lifecycle_lock = asyncio.Lock()
        worktree_path = "/wt"
        scope = "/s"
        id = "merge-finish"
        name = "w"

        def _persist(self):
            pass

    session = FakeSession()
    merge_called = False

    async def finish_turn(_delay):
        session.status.value = "idle"

    def fake_merge(*_args, **_kwargs):
        nonlocal merge_called
        merge_called = True
        return {"ok": True, "merged_commits": {}}

    monkeypatch.setattr(sessmod.asyncio, "sleep", finish_turn)
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)

    result = await sessmod.merge_session("w", {"scope": "/s"})

    assert result["ok"] is True
    assert merge_called is True


@pytest.mark.asyncio
async def test_merge_rejects_worker_that_stays_running_without_merging(monkeypatch):
    import asyncio
    import app.main as mainmod
    import app.routes.sessions as sessmod

    class Status:
        value = "running"

    class FakeSession:
        loaded = True
        status = Status()
        _lifecycle_lock = asyncio.Lock()
        worktree_path = "/wt"
        scope = "/s"
        id = "merge-running"
        name = "w"

    session = FakeSession()
    merge_called = False

    async def no_wall_clock_wait(_delay):
        return None

    def fake_merge(*_args, **_kwargs):
        nonlocal merge_called
        merge_called = True
        return {"ok": True, "merged_commits": {}}

    monkeypatch.setattr(sessmod.asyncio, "sleep", no_wall_clock_wait)
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)

    response = await sessmod.merge_session("w", {"scope": "/s"})

    assert response.status_code == 400
    assert merge_called is False


@pytest.mark.asyncio
async def test_merge_and_switch_hold_lifecycle_lock_against_worker_wakeup(db, monkeypatch):
    import asyncio
    import threading
    import app.main as mainmod
    import app.routes.sessions as sessmod

    observed = {"persist_locked": []}

    class Status:
        value = "idle"

    class FakeSession:
        loaded = True
        status = Status()
        _lifecycle_lock = asyncio.Lock()
        worktree_path = "/wt"
        scope = "/s"
        id = "merge-switch-lock"
        name = "w"

        def _persist(self):
            observed["persist_locked"].append(self._lifecycle_lock.locked())

    session = FakeSession()
    loop = asyncio.get_running_loop()
    wake_attempted = threading.Event()
    wake_entered = asyncio.Event()

    async def wake_worker():
        wake_attempted.set()
        async with session._lifecycle_lock:
            wake_entered.set()

    def fake_merge(*_args, **_kwargs):
        observed["merge_locked"] = session._lifecycle_lock.locked()
        loop.call_soon_threadsafe(lambda: asyncio.create_task(wake_worker()))
        assert wake_attempted.wait(1)
        return {"ok": True, "merged_commits": {}}

    def fake_switch(*_args, **_kwargs):
        observed["switch_locked"] = session._lifecycle_lock.locked()
        observed["wake_blocked_during_switch"] = not wake_entered.is_set()
        return {"ok": True, "branch": "task-43/w"}

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
    monkeypatch.setattr("app.workspace.switch_worktree_branch", fake_switch)
    monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)
    monkeypatch.setattr("app.tm.api_update_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)

    result = await sessmod.merge_session("w", {
        "scope": "/s",
        "target": "main",
        "next_task_id": "43",
    })
    await asyncio.wait_for(wake_entered.wait(), timeout=1)

    assert result["switch"]["ok"] is True
    assert observed["merge_locked"] is True
    assert observed["switch_locked"] is True
    assert observed["wake_blocked_during_switch"] is True
    assert observed["persist_locked"] and all(observed["persist_locked"])


class TestPipelines:
    def test_list_valid_only(self, client):
        r = client.get("/api/pipelines")
        assert r.status_code == 200
        data = r.json()
        names = [p["name"] for p in data]
        assert "default" in names
        # все возвращённые — валидны (поле valid не отдаётся, но битых быть не должно)
        for p in data:
            assert "name" in p and "description" in p and "roles" in p

    def test_excludes_invalid(self, client, monkeypatch):
        import app.routes.system as sysmod
        monkeypatch.setattr(sysmod, "list_pipelines", lambda: [
            {"name": "good", "description": "d", "roles": ["pm"], "valid": True, "error": None},
            {"name": "broken", "description": "", "roles": [], "valid": False, "error": "boom"},
        ])
        r = client.get("/api/pipelines")
        names = [p["name"] for p in r.json()]
        assert "good" in names
        assert "broken" not in names


class TestProfiles:
    def test_list_contains_personal(self, client):
        r = client.get("/api/profiles")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert "personal" in names

    def test_create_and_update(self, client):
        r = client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/x"})
        assert r.status_code == 200
        g = client.get("/api/profiles").json()
        work = [p for p in g if p["name"] == "work"]
        assert len(work) == 1
        assert work[0]["config_dir"] == "/tmp/x"

        # повторный POST с другим config_dir — обновляет, не дублирует
        r2 = client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/y"})
        assert r2.status_code == 200
        g2 = client.get("/api/profiles").json()
        work2 = [p for p in g2 if p["name"] == "work"]
        assert len(work2) == 1
        assert work2[0]["config_dir"] == "/tmp/y"

    def test_create_invalid_name_400(self, client):
        r = client.post("/api/profiles", json={"name": "a b!", "config_dir": "/tmp/x"})
        assert r.status_code == 400

    def test_delete_profile(self, client):
        client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/x"})
        r = client.delete("/api/profiles/work")
        assert r.status_code == 200
        names = [p["name"] for p in client.get("/api/profiles").json()]
        assert "work" not in names

    def test_delete_personal_protected(self, client):
        r = client.delete("/api/profiles/personal")
        assert r.status_code == 409
        names = [p["name"] for p in client.get("/api/profiles").json()]
        assert "personal" in names

    # ── C1: мягкая валидация config_dir ──

    def test_create_existing_dir_no_warning(self, client, tmp_path):
        """config_dir указывает на существующую папку → 200, warning отсутствует."""
        cfg = tmp_path / "claude-cfg"
        cfg.mkdir()
        r = client.post("/api/profiles", json={"name": "work", "config_dir": str(cfg)})
        assert r.status_code == 200
        body = r.json()
        assert body["warning"] is None
        # профиль реально в списке
        g = client.get("/api/profiles").json()
        assert any(p["name"] == "work" and p["config_dir"] == str(cfg) for p in g)

    def test_create_missing_dir_warns_but_saves(self, client, tmp_path):
        """Несуществующий config_dir → 200 (НЕ ошибка), warning есть, профиль СОХРАНЁН."""
        missing = tmp_path / "does-not-exist"
        r = client.post("/api/profiles", json={"name": "work", "config_dir": str(missing)})
        assert r.status_code == 200
        body = r.json()
        assert body["warning"] is not None
        assert str(missing) in body["warning"]
        # несмотря на warning — профиль сохранён и виден в GET
        g = client.get("/api/profiles").json()
        assert any(p["name"] == "work" and p["config_dir"] == str(missing) for p in g)
        # warning-ответ содержит и сам список профилей
        assert any(p["name"] == "work" for p in body["profiles"])

    def test_create_empty_config_dir_no_warning(self, client):
        """Пустой config_dir (как у personal) → warning отсутствует."""
        r = client.post("/api/profiles", json={"name": "noenv", "config_dir": ""})
        assert r.status_code == 200
        assert r.json()["warning"] is None

    def test_create_tilde_expands_existing(self, client, tmp_path, monkeypatch):
        """C3: путь вида ``~/.claude-work`` нормализуется через expanduser.

        HOME подменяем на tmp_path и создаём реальную ``.claude-work`` —
        warning не должен появиться, что доказывает раскрытие тильды.
        """
        work = tmp_path / ".claude-work"
        work.mkdir()
        monkeypatch.setenv("HOME", str(tmp_path))
        r = client.post("/api/profiles", json={"name": "work", "config_dir": "~/.claude-work"})
        assert r.status_code == 200
        assert r.json()["warning"] is None

    def test_create_tilde_missing_warns(self, client, tmp_path, monkeypatch):
        """C3: ``~/.claude-work`` без реальной папки → warning (но сохранён as-is)."""
        monkeypatch.setenv("HOME", str(tmp_path))  # пусто, .claude-work не создаём
        r = client.post("/api/profiles", json={"name": "work", "config_dir": "~/.claude-work"})
        assert r.status_code == 200
        body = r.json()
        assert body["warning"] is not None
        # хранится исходная (нераскрытая) строка — expanduser только для проверки
        g = client.get("/api/profiles").json()
        assert any(p["config_dir"] == "~/.claude-work" for p in g)


@pytest.mark.asyncio
async def test_create_session_passes_pipeline_and_profile(monkeypatch):
    import app.main as mainmod
    import app.routes.sessions as sessmod
    import app.routes.system as sysmod
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)

        class _Sess:
            def to_dict(self):
                return {"name": kwargs["name"], "id": "sid"}
        return _Sess()

    monkeypatch.setattr(mainmod.manager, "create_session", fake_create)
    monkeypatch.setattr(sysmod, "_is_safe_path", lambda p: True)

    req = sessmod.CreateSessionRequest(
        name="w1", cwd="/tmp", model="claude-sonnet-5[1m]",
        pipeline="default", profile="work",
    )
    await sessmod.create_session(req)
    assert captured["pipeline"] == "default"
    assert captured["profile"] == "work"
class TestChangeScopeEndpoint:
    def test_success(self, client, tmp_path):
        newdir = tmp_path / "newproj"; newdir.mkdir()
        from app.main import manager
        with patch.object(manager, "change_orchestrator_scope",
                          new=AsyncMock(return_value={"ok": True, "scope": str(newdir), "cwd": str(newdir)})) as m:
            r = client.post("/api/orchestrators/orch/change-scope", json={
                "old_scope": "/tmp", "new_scope": str(newdir),
            })
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # new_cwd defaults to new_scope
        m.assert_awaited_once_with("orch", "/tmp", str(newdir), str(newdir))

    def test_explicit_cwd(self, client, tmp_path):
        newdir = tmp_path / "newproj"; newdir.mkdir()
        cwddir = tmp_path / "cwddir"; cwddir.mkdir()
        from app.main import manager
        with patch.object(manager, "change_orchestrator_scope",
                          new=AsyncMock(return_value={"ok": True})) as m:
            client.post("/api/orchestrators/orch/change-scope", json={
                "old_scope": "/tmp", "new_scope": str(newdir), "new_cwd": str(cwddir),
            })
        m.assert_awaited_once_with("orch", "/tmp", str(newdir), str(cwddir))

    def test_403_unsafe_path(self, client):
        r = client.post("/api/orchestrators/orch/change-scope", json={
            "old_scope": "/tmp", "new_scope": "/etc/passwd",
        })
        assert r.status_code == 403

    def test_409_on_manager_error(self, client, tmp_path):
        newdir = tmp_path / "newproj"; newdir.mkdir()
        from app.main import manager
        with patch.object(manager, "change_orchestrator_scope",
                          new=AsyncMock(return_value={"error": "live workers in scope"})):
            r = client.post("/api/orchestrators/orch/change-scope", json={
                "old_scope": "/tmp", "new_scope": str(newdir),
            })
        assert r.status_code == 409
        assert "error" in r.json()

    def test_422_missing_fields(self, client):
        r = client.post("/api/orchestrators/orch/change-scope", json={"old_scope": "/tmp"})
        assert r.status_code == 422

    def test_403_sibling_prefix_escape(self, client, tmp_path):
        # /tmp_evil must NOT pass just because it shares the "/tmp" prefix
        from app.main import manager
        with patch.object(manager, "change_orchestrator_scope", new=AsyncMock()) as m:
            r = client.post("/api/orchestrators/orch/change-scope", json={
                "old_scope": "/tmp", "new_scope": "/tmproot_escape",
            })
        assert r.status_code == 403
        m.assert_not_awaited()


class TestDeleteOrphanGuard:
    """kill (DELETE) a parent with live children → blocked unless force."""

    def _mk(self, client, name, parent_name=""):
        body = {"name": name, "scope": "/tmp", "cwd": "/tmp",
                "model": "claude-sonnet-5[1m]"}
        if parent_name:
            # worker parent + unrouted child is blocked by validate_spawn
            # (allow_unrouted_workers=False) — give the child an explicit role.
            body["parent_name"] = parent_name
            body["role"] = "worker"
        r = client.post("/api/sessions", json=body)
        assert r.status_code == 201, r.text

    def test_blocks_kill_with_live_child(self, client):
        self._mk(client, "par")
        self._mk(client, "kid", parent_name="par")
        r = client.delete("/api/sessions/par", params={"scope": "/tmp"})
        assert r.status_code == 400
        assert "child" in r.json()["error"]
        assert "kid" in r.json()["error"]

    def test_force_overrides(self, client):
        self._mk(client, "par2")
        self._mk(client, "kid2", parent_name="par2")
        r = client.delete("/api/sessions/par2", params={"scope": "/tmp", "force": "true"})
        assert r.status_code == 200

    def test_no_children_not_blocked(self, client):
        self._mk(client, "lonely")
        r = client.delete("/api/sessions/lonely", params={"scope": "/tmp"})
        assert r.status_code == 200
