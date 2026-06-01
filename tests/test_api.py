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
    import app.main as mainmod
    monkeypatch.setattr(mainmod, "_ALLOWED_ROOTS", ["/tmp", str(tmp_path)])
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
            "model": "claude-sonnet-4-6",
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
            "model": "claude-sonnet-4-6",
        })
        assert r.status_code == 422

    def test_422_empty_name(self, client):
        r = client.post("/api/sessions", json={
            "name": "",
            "scope": "/tmp",
            "cwd": "/tmp",
            "model": "claude-sonnet-4-6",
        })
        assert r.status_code == 422

    def test_409_duplicate(self, client):
        body = {"name": "w1", "scope": "/tmp", "cwd": "/tmp", "model": "claude-sonnet-4-6"}
        r1 = client.post("/api/sessions", json=body)
        assert r1.status_code == 201
        r2 = client.post("/api/sessions", json=body)
        assert r2.status_code == 409

    def test_422_bad_cwd(self, client):
        r = client.post("/api/sessions", json={
            "name": "w1",
            "scope": "/tmp",
            "cwd": "/nonexistent/path",
            "model": "claude-sonnet-4-6",
        })
        assert r.status_code == 422


class TestGetSessions:
    def test_list_empty(self, client):
        r = client.get("/api/sessions")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_with_scope(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/a", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
        client.post("/api/sessions", json={"name": "w2", "scope": "/b", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
        r = client.get("/api/sessions", params={"scope": "/a"})
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["name"] == "w1"

    def test_get_by_name(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
        r = client.get("/api/sessions/w1", params={"scope": "/s"})
        assert r.status_code == 200
        assert r.json()["name"] == "w1"

    def test_get_404(self, client):
        r = client.get("/api/sessions/nonexistent", params={"scope": "/s"})
        assert r.status_code == 404


class TestSendMessage:
    def test_send(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
        r = client.post("/api/sessions/w1/send", json={"message": "hello", "scope": "/s"})
        assert r.status_code == 200

    def test_send_404(self, client):
        r = client.post("/api/sessions/ghost/send", json={"message": "hi", "scope": "/s"})
        assert r.status_code == 404


class TestInterrupt:
    def test_interrupt(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
        r = client.post("/api/sessions/w1/interrupt", json={"scope": "/s"})
        assert r.status_code == 200


class TestDeleteSession:
    def test_delete(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
        r = client.delete("/api/sessions/w1", params={"scope": "/s"})
        assert r.status_code == 200
        r2 = client.get("/api/sessions/w1", params={"scope": "/s"})
        assert r2.status_code == 404

    def test_delete_404(self, client):
        r = client.delete("/api/sessions/ghost", params={"scope": "/s"})
        assert r.status_code == 404


class TestLogs:
    def test_logs_empty(self, client):
        client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
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


def test_create_request_accepts_base_branch():
    from app.main import CreateSessionRequest
    req = CreateSessionRequest(name="w1", cwd="/tmp", model="claude-sonnet-4-6",
                               use_worktree=True, repo_path="/tmp",
                               base_branch="feature/auth")
    assert req.base_branch == "feature/auth"


def test_create_request_base_branch_default_empty():
    # Sentinel "" = авто-резолв базовой ветки по стратегии пайплайна (DESIGN §10).
    # Резолв в "main" происходит в manager/workspace, а не в дефолте запроса.
    from app.main import CreateSessionRequest
    req = CreateSessionRequest(name="w1", cwd="/tmp", model="claude-sonnet-4-6")
    assert req.base_branch == ""


@pytest.mark.asyncio
async def test_merge_endpoint_passes_target(monkeypatch):
    import app.main as mainmod
    captured = {}

    def fake_merge(worktree_path, repo_path, target_branch="main"):
        captured["target_branch"] = target_branch
        return {"ok": True, "commits_merged": 1, "branch": "task-1/w", "merged_commits": {}}
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)

    class FakeSession:
        class _S:
            value = "idle"
        status = _S()
        worktree_path = "/wt"
        scope = "/s"
        id = "sid"
        name = "w"
    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: FakeSession())

    import asyncio
    res = await mainmod.merge_session("w", {"scope": "/s", "target": "feature/auth"})
    assert captured["target_branch"] == "feature/auth"


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
        import app.main as mainmod
        monkeypatch.setattr(mainmod, "list_pipelines", lambda: [
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


@pytest.mark.asyncio
async def test_create_session_passes_pipeline_and_profile(monkeypatch):
    import app.main as mainmod
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)

        class _Sess:
            def to_dict(self):
                return {"name": kwargs["name"], "id": "sid"}
        return _Sess()

    monkeypatch.setattr(mainmod.manager, "create_session", fake_create)
    monkeypatch.setattr(mainmod, "_is_safe_path", lambda p: True)

    req = mainmod.CreateSessionRequest(
        name="w1", cwd="/tmp", model="claude-sonnet-4-6",
        pipeline="default", profile="work",
    )
    await mainmod.create_session(req)
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
