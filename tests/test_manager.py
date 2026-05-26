"""TDD tests for manager.py — SessionManager."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def mgr(db, tmp_path, monkeypatch):
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.manager import SessionManager
    return SessionManager()


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_returns_session(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="worker-1",
                scope="/test/scope",
                cwd="/tmp",
                model="claude-sonnet-4-6",
            )
        assert session.name == "worker-1"
        assert session.id is not None
        assert len(session.id) > 0

    @pytest.mark.asyncio
    async def test_generates_uuid(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            s1 = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            s2 = await mgr.create_session(name="w2", scope="/s", cwd="/tmp", model="m")
        assert s1.id != s2.id

    @pytest.mark.asyncio
    async def test_validates_cwd(self, mgr):
        with pytest.raises(ValueError, match="does not exist"):
            await mgr.create_session(
                name="w", scope="/s", cwd="/nonexistent/path", model="m"
            )

    @pytest.mark.asyncio
    async def test_duplicate_name_scope_raises(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            with pytest.raises(ValueError, match="already exists"):
                await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")

    @pytest.mark.asyncio
    async def test_persists_to_db(self, mgr):
        from app.db import get_session_by_name
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
        db_row = get_session_by_name("w1", "/s")
        assert db_row is not None
        assert db_row["id"] == session.id

    @pytest.mark.asyncio
    async def test_with_worktree(self, mgr, tmp_path):
        import subprocess
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)

        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w1", scope="/s", cwd=str(repo),
                model="m", use_worktree=True, repo_path=str(repo),
            )
        assert session.worktree_path is not None
        assert session.branch is not None


class TestWorktreeBaseBranch:
    @pytest.mark.asyncio
    async def test_worktree_from_feature_branch(self, mgr, tmp_path):
        import subprocess
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "feature/auth"], cwd=repo, capture_output=True, check=True)

        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w1", scope="/s", cwd=str(repo), model="m",
                use_worktree=True, repo_path=str(repo), base_branch="feature/auth",
            )
        head = subprocess.run(["git", "rev-parse", "feature/auth"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
        base = subprocess.run(["git", "merge-base", session.branch, "feature/auth"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
        assert base == head


class TestSendAndControl:
    @pytest.mark.asyncio
    async def test_send_routes(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            session.send = AsyncMock()
            await mgr.send(session.id, "hello")
        session.send.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_send_unknown_raises(self, mgr):
        with pytest.raises(KeyError):
            await mgr.send("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_stop_and_remove(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            await mgr.remove(session.id)
        assert mgr.get(session.id) is None

    @pytest.mark.asyncio
    async def test_remove_deletes_from_dict_and_db(self, mgr):
        from app.db import get_session
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            await mgr.remove(session.id)
        assert mgr.get(session.id) is None
        assert get_session(session.id) is None


class TestListSessions:
    @pytest.mark.asyncio
    async def test_scope_filter(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.create_session(name="w1", scope="/a", cwd="/tmp", model="m")
            await mgr.create_session(name="w2", scope="/b", cwd="/tmp", model="m")
        result = mgr.list_sessions(scope="/a")
        assert len(result) == 1
        assert result[0]["name"] == "w1"

    @pytest.mark.asyncio
    async def test_merges_active_and_db(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
        result = mgr.list_sessions()
        assert len(result) >= 1


class TestAutoResume:
    @pytest.mark.asyncio
    async def test_resumes_orchestrators(self, mgr):
        from app.db import save_session
        save_session({
            "id": "orch-1", "name": "orchestrator", "scope": "/tmp",
            "cwd": "/tmp", "model": "claude-opus-4-6", "system_prompt": "",
            "status": "idle", "session_id": "sdk-123",
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.auto_resume_orchestrators()
        assert mgr.get("orch-1") is not None

