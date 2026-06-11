"""P1: get_by_name returns AgentSession | None — never a raw dict.

DB-only sessions hydrate into detached AgentSession (loaded=False, db_row kept
for response-shape compatibility). Live-only operations must reject detached.
"""

from unittest.mock import patch

import pytest

from app.manager import SessionManager
from app.session import AgentSession, AgentStatus
from tests.conftest import make_backend_mock


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
    return SessionManager()


async def _spawn(mgr, name="worker-1", scope="/test/scope"):
    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        return await mgr.create_session(name=name, scope=scope, cwd="/tmp",
                                        model="claude-sonnet-4-6")


class TestGetByNameUnion:
    @pytest.mark.asyncio
    async def test_live_session_is_loaded(self, mgr):
        await _spawn(mgr)
        found = mgr.get_by_name("worker-1", "/test/scope")
        assert isinstance(found, AgentSession)
        assert found.loaded is True

    @pytest.mark.asyncio
    async def test_db_only_session_hydrates_detached(self, mgr):
        created = await _spawn(mgr)
        fresh = SessionManager()  # empty registry → DB fallback
        found = fresh.get_by_name("worker-1", "/test/scope")
        assert isinstance(found, AgentSession)
        assert found.loaded is False
        assert found.id == created.id
        assert found.name == "worker-1"
        assert found.scope == "/test/scope"

    @pytest.mark.asyncio
    async def test_db_only_keeps_raw_row_for_response_shape(self, mgr):
        await _spawn(mgr)
        found = SessionManager().get_by_name("worker-1", "/test/scope")
        assert isinstance(found.db_row, dict)
        # raw row keys that AgentSession.to_dict() does NOT expose
        assert "cwd" in found.db_row
        assert found.db_row["name"] == "worker-1"

    def test_miss_returns_none(self, mgr):
        assert mgr.get_by_name("ghost", "/nowhere") is None

    @pytest.mark.asyncio
    async def test_status_hydrated_from_db(self, mgr):
        s = await _spawn(mgr)
        s.status = AgentStatus.WAITING
        from app.db import save_session
        save_session(s._to_db_dict())
        found = SessionManager().get_by_name("worker-1", "/test/scope")
        assert found.status is AgentStatus.WAITING

    @pytest.mark.asyncio
    async def test_unknown_status_falls_back_to_idle(self, mgr):
        s = await _spawn(mgr)
        from app.db import _conn
        with _conn() as c:
            c.execute("UPDATE sessions SET status='hibernated-weird' WHERE id=?", (s.id,))
        found = SessionManager().get_by_name("worker-1", "/test/scope")
        assert found.status is AgentStatus.IDLE


class TestUpdateSessionFields:
    @pytest.mark.asyncio
    async def test_live_path_sets_attr(self, mgr):
        await _spawn(mgr)
        res = mgr.update_session_fields("worker-1", "/test/scope", description="hi")
        assert res is not None and res.loaded
        assert mgr.get_by_name("worker-1", "/test/scope").description == "hi"

    @pytest.mark.asyncio
    async def test_detached_path_updates_db(self, mgr):
        await _spawn(mgr)
        fresh = SessionManager()
        res = fresh.update_session_fields("worker-1", "/test/scope", description="from-db",
                                          tg_topic=True)
        assert res is not None and not res.loaded
        from app.db import get_session_by_name
        row = get_session_by_name("worker-1", "/test/scope")
        assert row["description"] == "from-db"
        assert row["tg_topic"] == 1

    def test_miss_returns_none(self, mgr):
        assert mgr.update_session_fields("ghost", "/nowhere", description="x") is None

    @pytest.mark.asyncio
    async def test_unknown_field_rejected(self, mgr):
        await _spawn(mgr)
        with pytest.raises(ValueError):
            mgr.update_session_fields("worker-1", "/test/scope", cost_usd=999)


class TestLiveOnlyGuards:
    @pytest.mark.asyncio
    async def test_change_orchestrator_scope_rejects_detached(self, mgr, tmp_path):
        await _spawn(mgr, name="orch-1")
        fresh = SessionManager()
        new_cwd = tmp_path / "new"
        new_cwd.mkdir()
        result = await fresh.change_orchestrator_scope(
            "orch-1", "/test/scope", "/new/scope", str(new_cwd))
        assert "not loaded" in result.get("error", "")
