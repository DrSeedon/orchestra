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
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
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
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
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
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            with pytest.raises(ValueError, match="already exists"):
                await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")

    @pytest.mark.asyncio
    async def test_persists_to_db(self, mgr):
        from app.db import get_session_by_name
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
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

        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            session = await mgr.create_session(
                name="w1", scope="/s", cwd=str(repo),
                model="m", use_worktree=True, repo_path=str(repo),
            )
        assert session.worktree_path is not None
        assert session.branch is not None


class TestSendAndControl:
    @pytest.mark.asyncio
    async def test_send_routes(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
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
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            await mgr.stop(session.id)
        from app.session import AgentStatus
        assert session.status == AgentStatus.STOPPED

    @pytest.mark.asyncio
    async def test_remove_deletes_from_dict_and_db(self, mgr):
        from app.db import get_session
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            await mgr.remove(session.id)
        assert mgr.get(session.id) is None
        assert get_session(session.id) is None


class TestListSessions:
    @pytest.mark.asyncio
    async def test_scope_filter(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            await mgr.create_session(name="w1", scope="/a", cwd="/tmp", model="m")
            await mgr.create_session(name="w2", scope="/b", cwd="/tmp", model="m")
        result = mgr.list_sessions(scope="/a")
        assert len(result) == 1
        assert result[0]["name"] == "w1"

    @pytest.mark.asyncio
    async def test_merges_active_and_db(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
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
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            await mgr.auto_resume_orchestrators()
        assert mgr.get("orch-1") is not None

    @pytest.mark.asyncio
    async def test_marks_stale(self, mgr):
        from app.db import save_session, get_session
        save_session({
            "id": "stale-1", "name": "worker-stale", "scope": "/tmp",
            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",             "status": "running", "session_id": None, "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False, "color": "#34d399",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        })
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock())):
            await mgr.auto_resume_orchestrators()
        got = get_session("stale-1")
        assert got["status"] == "error"


class TestArchivedSessions:
    """Data layer refactor: manager.archived holds stopped/error sessions in memory."""

    @pytest.mark.asyncio
    async def test_stop_moves_to_archived(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            sid = session.id
            await mgr.stop(sid)
        assert mgr.get(sid) is None
        assert sid in mgr.archived

    @pytest.mark.asyncio
    async def test_archived_has_correct_status(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            await mgr.stop(session.id)
        assert mgr.archived[session.id]["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_list_sessions_includes_archived(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            s1 = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            s2 = await mgr.create_session(name="w2", scope="/s", cwd="/tmp", model="m")
            await mgr.stop(s1.id)
        result = mgr.list_sessions()
        names = {s["name"] for s in result}
        assert "w2" in names
        assert any(s1.id[:6] in s["name"] for s in result)

    @pytest.mark.asyncio
    async def test_list_sessions_no_db_call(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
        with patch("app.db.get_all_sessions", side_effect=RuntimeError("should not call DB")):
            result = mgr.list_sessions()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_by_name_finds_archived(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            await mgr.stop(session.id)
        archived_name = session.name
        found = mgr.get_by_name(archived_name, "/s")
        assert found is not None
        assert found["id"] == session.id

    @pytest.mark.asyncio
    async def test_remove_deletes_from_archived(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            sid = session.id
            await mgr.stop(sid)
        assert sid in mgr.archived
        await mgr.remove(sid)
        assert sid not in mgr.archived

    @pytest.mark.asyncio
    async def test_load_archived_at_startup(self, mgr):
        from app.db import save_session
        save_session({
            "id": "arch-1", "name": "old-worker-abc123", "scope": "/tmp",
            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
            "status": "stopped", "session_id": None, "cost_usd": 0.5,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        mgr.load_archived()
        assert "arch-1" in mgr.archived
        assert mgr.archived["arch-1"]["name"] == "old-worker-abc123"

    @pytest.mark.asyncio
    async def test_load_archived_skips_active(self, mgr):
        from app.db import save_session
        save_session({
            "id": "idle-1", "name": "orch", "scope": "/tmp",
            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
            "status": "idle", "session_id": "sdk-123", "cost_usd": 0,
            "worktree_path": None, "branch": None, "is_orchestrator": True,
            "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })
        mgr.load_archived()
        assert "idle-1" not in mgr.archived

    @pytest.mark.asyncio
    async def test_list_sessions_scope_filter_on_archived(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            s1 = await mgr.create_session(name="w1", scope="/a", cwd="/tmp", model="m")
            s2 = await mgr.create_session(name="w2", scope="/b", cwd="/tmp", model="m")
            await mgr.stop(s1.id)
            await mgr.stop(s2.id)
        result_a = mgr.list_sessions(scope="/a")
        result_b = mgr.list_sessions(scope="/b")
        assert len(result_a) == 1
        assert len(result_b) == 1

    @pytest.mark.asyncio
    async def test_get_session_id_for_archived(self, mgr):
        with patch("app.session.AgentSession._make_client", return_value=AsyncMock(
            connect=AsyncMock(), query=AsyncMock(), disconnect=AsyncMock(),
            receive_messages=AsyncMock(return_value=iter([])),
        )):
            session = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="m")
            sid = session.id
            await mgr.stop(sid)
        found = mgr.get_session_id(session.name, "/s")
        assert found == sid
