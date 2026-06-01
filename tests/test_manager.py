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


class TestRemoveScope:
    @pytest.mark.asyncio
    async def test_passes_orch_names_to_tg_bridge_when_flag_set(self, mgr, monkeypatch):
        """remove_scope с delete_tg_topics=True должен передать имена орков в tg_bridge."""
        from app.db import save_session
        save_session({
            "id": "orch-x", "name": "orch-x-orchestrator", "scope": "/scope-x",
            "cwd": "/tmp", "model": "claude-opus-4-6", "system_prompt": "",
            "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })

        called = {}

        async def fake_remove(names):
            called["names"] = list(names)
            return {"deleted": list(names), "failed": [], "skipped": []}

        monkeypatch.setattr("app.tg_bridge.remove_topics_for_orchs", fake_remove)

        result = await mgr.remove_scope("/scope-x", delete_tg_topics=True)

        assert called["names"] == ["orch-x-orchestrator"]
        assert result["tg"]["deleted"] == ["orch-x-orchestrator"]

    @pytest.mark.asyncio
    async def test_skips_tg_bridge_when_flag_false(self, mgr, monkeypatch):
        from app.db import save_session
        save_session({
            "id": "orch-y", "name": "orch-y-orchestrator", "scope": "/scope-y",
            "cwd": "/tmp", "model": "claude-opus-4-6", "system_prompt": "",
            "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })

        called = {"hit": False}

        async def fake_remove(names):
            called["hit"] = True
            return {}

        monkeypatch.setattr("app.tg_bridge.remove_topics_for_orchs", fake_remove)

        result = await mgr.remove_scope("/scope-y", delete_tg_topics=False)

        assert called["hit"] is False
        assert result["tg"] == {}


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



class TestCanSpawn:
    def _write_role(self, roles_dir, name, frontmatter_body):
        (roles_dir / f"{name}.md").write_text(f"---\n{frontmatter_body}\n---\n\nBody for {name}.\n")

    @pytest.fixture
    def roles_dir(self, tmp_path, monkeypatch):
        prompts = tmp_path / "prompts"
        rdir = prompts / "roles"
        rdir.mkdir(parents=True)
        (prompts / "base.md").write_text("BASE")
        monkeypatch.setattr("app.manager._PROMPTS_DIR", prompts)
        monkeypatch.setattr("app.manager._SKILLS_DIR", prompts / "skills")
        return rdir

    def test_role_can_spawn_absent_is_none(self, roles_dir):
        from app.manager import _role_can_spawn
        self._write_role(roles_dir, "boss", "name: boss\nmodel: opus")
        assert _role_can_spawn("boss") is None

    def test_role_can_spawn_yaml_null_is_none(self, roles_dir):
        from app.manager import _role_can_spawn
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn:")
        assert _role_can_spawn("boss") is None

    def test_role_can_spawn_non_list_is_none(self, roles_dir):
        from app.manager import _role_can_spawn
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: worker")
        assert _role_can_spawn("boss") is None

    def test_role_can_spawn_empty_list_is_terminal(self, roles_dir):
        from app.manager import _role_can_spawn
        self._write_role(roles_dir, "leaf", "name: leaf\ncan_spawn: []")
        assert _role_can_spawn("leaf") == []

    def test_role_can_spawn_whitelist(self, roles_dir):
        from app.manager import _role_can_spawn
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker, reviewer]")
        assert _role_can_spawn("boss") == ["worker", "reviewer"]

    def test_role_can_spawn_missing_file_is_none(self, roles_dir):
        from app.manager import _role_can_spawn
        assert _role_can_spawn("ghost") is None

    @pytest.mark.asyncio
    async def test_whitelist_allows_listed(self, mgr, roles_dir):
        from app.db import save_session
        from tests.conftest import make_backend_mock
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker]")
        self._write_role(roles_dir, "worker", "name: worker")
        save_session({
            "id": "p-1", "name": "parent", "scope": "/s", "cwd": "/tmp",
            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "color": "#fff",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "boss",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="child", scope="/s", cwd="/tmp", model="m",
                role="worker", parent_name="parent",
            )
        assert session.name == "child"

    @pytest.mark.asyncio
    async def test_whitelist_blocks_unlisted(self, mgr, roles_dir):
        from app.db import save_session
        from tests.conftest import make_backend_mock
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker]")
        self._write_role(roles_dir, "full-cycle", "name: full-cycle")
        save_session({
            "id": "p-2", "name": "parent", "scope": "/s", "cwd": "/tmp",
            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "color": "#fff",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "boss",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            with pytest.raises(ValueError, match="not allowed to spawn"):
                await mgr.create_session(
                    name="child", scope="/s", cwd="/tmp", model="m",
                    role="full-cycle", parent_name="parent",
                )

    @pytest.mark.asyncio
    async def test_empty_can_spawn_blocks_all(self, mgr, roles_dir):
        from app.db import save_session
        from tests.conftest import make_backend_mock
        self._write_role(roles_dir, "leaf", "name: leaf\ncan_spawn: []")
        self._write_role(roles_dir, "worker", "name: worker")
        save_session({
            "id": "p-3", "name": "parent", "scope": "/s", "cwd": "/tmp",
            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "color": "#fff",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "leaf",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            with pytest.raises(ValueError, match="terminal role"):
                await mgr.create_session(
                    name="child", scope="/s", cwd="/tmp", model="m",
                    role="worker", parent_name="parent",
                )

    @pytest.mark.asyncio
    async def test_unknown_parent_fails_open(self, mgr, roles_dir):
        from tests.conftest import make_backend_mock
        self._write_role(roles_dir, "worker", "name: worker")
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="child", scope="/s", cwd="/tmp", model="m",
                role="worker", parent_name="ghost-parent",
            )
        assert session.name == "child"


class TestCustomMcp:
    def test_parse_none_is_empty(self):
        from app.manager import _parse_custom_mcp
        assert _parse_custom_mcp(None) == {}
        assert _parse_custom_mcp("") == {}

    def test_parse_dict_passthrough(self):
        from app.manager import _parse_custom_mcp
        d = {"playwright": {"command": "npx", "args": ["-y", "@playwright/mcp"]}}
        assert _parse_custom_mcp(d) == d

    def test_parse_json_string(self):
        from app.manager import _parse_custom_mcp
        raw = '{"playwright": {"command": "npx"}}'
        assert _parse_custom_mcp(raw) == {"playwright": {"command": "npx"}}

    def test_parse_invalid_json_is_empty(self):
        from app.manager import _parse_custom_mcp
        assert _parse_custom_mcp("{not json") == {}

    def test_parse_non_dict_is_empty(self):
        from app.manager import _parse_custom_mcp
        assert _parse_custom_mcp("[1, 2, 3]") == {}
        assert _parse_custom_mcp(42) == {}

    def test_parse_strips_orchestra_key(self):
        from app.manager import _parse_custom_mcp
        raw = {"orchestra": {"command": "evil"}, "playwright": {"command": "npx"}}
        assert _parse_custom_mcp(raw) == {"playwright": {"command": "npx"}}

    def test_make_mcp_config_merges_extra(self):
        from app.manager import _make_mcp_config
        cfg = _make_mcp_config("w", "/s", "worker", extra={"playwright": {"command": "npx"}})
        assert "orchestra" in cfg
        assert cfg["playwright"] == {"command": "npx"}

    def test_make_mcp_config_extra_cannot_override_orchestra(self):
        from app.manager import _make_mcp_config
        cfg = _make_mcp_config("w", "/s", "worker", extra={"orchestra": {"command": "evil"}})
        assert cfg["orchestra"]["command"] != "evil"

    @pytest.mark.asyncio
    async def test_create_session_wires_custom_mcp(self, mgr):
        from tests.conftest import make_backend_mock
        custom = {"playwright": {"command": "npx", "args": ["-y", "@playwright/mcp"]}}
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w24a", scope="/s", cwd="/tmp", model="m",
                role="worker", mcp_servers=custom,
            )
        assert session.mcp_servers_custom == custom
        assert "playwright" in session.mcp_servers
        assert "orchestra" in session.mcp_servers

    @pytest.mark.asyncio
    async def test_create_session_persists_custom_mcp(self, mgr):
        import json
        from app.db import get_session_by_name
        from tests.conftest import make_backend_mock
        custom = {"playwright": {"command": "npx"}}
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.create_session(
                name="w24b", scope="/s", cwd="/tmp", model="m",
                role="worker", mcp_servers=custom,
            )
        row = get_session_by_name("w24b", "/s")
        assert json.loads(row["mcp_servers_custom"]) == custom

    @pytest.mark.asyncio
    async def test_load_from_db_remerges_custom_mcp(self, mgr):
        import json
        from app.db import save_session, get_session_by_name
        from tests.conftest import make_backend_mock
        custom = {"playwright": {"command": "npx"}}
        save_session({
            "id": "r-24", "name": "w24c", "scope": "/s", "cwd": "/tmp",
            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "color": "#fff",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "worker", "mcp_servers_custom": json.dumps(custom),
        })
        row = get_session_by_name("w24c", "/s")
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr._load_from_db(row)
        assert session.mcp_servers_custom == custom
        assert "playwright" in session.mcp_servers
        assert "orchestra" in session.mcp_servers


class TestSystemPromptAppend:
    @pytest.mark.asyncio
    async def test_worker_custom_prompt_appended(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                session = await mgr.create_session(
                    name="w-sp1", scope="/s", cwd="/tmp", model="m",
                    role="worker", system_prompt="CUSTOM",
                )
        assert "ROLE_BASE" in session.system_prompt
        assert "CUSTOM" in session.system_prompt
        assert session.system_prompt.index("ROLE_BASE") < session.system_prompt.index("CUSTOM")

    @pytest.mark.asyncio
    async def test_orchestrator_custom_prompt_appended(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                session = await mgr.create_session(
                    name="w-sp2", scope="/s", cwd="/tmp", model="m",
                    role="orchestrator", system_prompt="CUSTOM",
                )
        assert "ROLE_BASE" in session.system_prompt
        assert "CUSTOM" in session.system_prompt
        assert session.system_prompt.index("ROLE_BASE") < session.system_prompt.index("CUSTOM")

    @pytest.mark.asyncio
    async def test_orchestrator_no_custom_prompt_uses_role_base(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                session = await mgr.create_session(
                    name="w-sp3", scope="/s", cwd="/tmp", model="m",
                    role="orchestrator",
                )
        assert session.system_prompt == "ROLE_BASE"


class TestChangeOrchestratorScope:
    async def _make_orch(self, mgr, name="orch", scope="/old/proj"):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            s = await mgr.create_session(
                name=name, scope=scope, cwd="/tmp", model="claude-opus-4-8",
                is_orchestrator=True,
            )
        s.session_id = "sdk-resume-token"
        from app.session import AgentStatus
        s.status = AgentStatus.IDLE
        return s

    async def _make_worker(self, mgr, name="w1", scope="/old/proj"):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            s = await mgr.create_session(name=name, scope=scope, cwd="/tmp", model="claude-sonnet-4-6")
        from app.session import AgentStatus
        s.status = AgentStatus.IDLE
        return s

    @pytest.mark.asyncio
    async def test_happy_path_updates_runtime_and_db(self, mgr, tmp_path):
        from app.db import get_session
        orch = await self._make_orch(mgr)
        newdir = tmp_path / "newproj"
        newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True
        assert orch.scope == str(newdir)
        assert orch.cwd == str(newdir)
        # mcp env rebuilt with new scope
        assert orch.mcp_servers["orchestra"]["env"]["ORCHESTRA_SCOPE"] == str(newdir)
        # db reflects change
        assert get_session(orch.id)["scope"] == str(newdir)
        # context preserved
        assert orch.session_id == "sdk-resume-token"

    @pytest.mark.asyncio
    async def test_disconnects_backend(self, mgr, tmp_path):
        orch = await self._make_orch(mgr)
        newdir = tmp_path / "newproj"; newdir.mkdir()
        orch._disconnect_backend = AsyncMock()
        await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        orch._disconnect_backend.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_when_running(self, mgr, tmp_path):
        from app.session import AgentStatus
        orch = await self._make_orch(mgr)
        orch.status = AgentStatus.RUNNING
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "running" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_non_orchestrator(self, mgr, tmp_path):
        w = await self._make_worker(mgr, name="w1")
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("w1", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "orchestrator" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_when_live_workers_in_old_scope(self, mgr, tmp_path):
        orch = await self._make_orch(mgr)
        await self._make_worker(mgr, name="w1", scope="/old/proj")
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "worker" in res["error"].lower()
        assert "w1" in res["error"]

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_cwd(self, mgr):
        await self._make_orch(mgr)
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", "/new/proj", "/nonexistent/xyz")
        assert res.get("ok") is not True
        assert "error" in res

    @pytest.mark.asyncio
    async def test_not_found(self, mgr, tmp_path):
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("ghost", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "not" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_drains_persist_before_db_write(self, mgr, tmp_path):
        # fence: any in-flight _persist() must be drained BEFORE change_scope()
        # so the transaction's cwd write is the last writer (no stale clobber).
        orch = await self._make_orch(mgr)
        newdir = tmp_path / "newproj"; newdir.mkdir()
        order = []
        orch._drain_persist = AsyncMock(side_effect=lambda: order.append("drain"))
        import app.db as dbmod
        real_change = dbmod.change_scope
        def traced(*a, **k):
            order.append("change_scope")
            return real_change(*a, **k)
        with patch("app.db.change_scope", side_effect=traced):
            res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True
        orch._drain_persist.assert_awaited_once()
        assert order == ["drain", "change_scope"]  # drain strictly before the write

    @pytest.mark.asyncio
    async def test_db_cwd_is_new_after_inflight_persist(self, mgr, tmp_path):
        # end-to-end: even with several queued _persist() (old cwd snapshots)
        # the final DB cwd must be the new one — _drain_persist awaits ALL,
        # not just the last submitted future.
        from app.db import get_session
        orch = await self._make_orch(mgr)
        newdir = tmp_path / "newproj"; newdir.mkdir()
        orch._persist(); orch._persist(); orch._persist()  # queue stale snapshots
        assert orch._persist_task is not None
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True
        assert get_session(orch.id)["cwd"] == str(newdir)
        # all drained before the transaction → nothing left to clobber
        assert orch._persist_task.done() and not orch._persist_dirty


class TestChangeScopeUnloadedWorkerGuard:
    @pytest.mark.asyncio
    async def test_rejects_unloaded_active_worker_in_old_scope(self, mgr, tmp_path):
        """An active worker row in the DB but NOT in self.sessions must still block."""
        from tests.conftest import make_backend_mock
        from app.session import AgentStatus
        from app.db import save_session, get_session
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            orch = await mgr.create_session(
                name="orch", scope="/old/proj", cwd="/tmp",
                model="claude-opus-4-8", is_orchestrator=True,
            )
        orch.session_id = "sdk-tok"
        orch.status = AgentStatus.IDLE
        # Worker row exists in DB only (not loaded into manager.sessions)
        save_session({
            "id": "ghost-worker-id", "name": "ghostw", "scope": "/old/proj",
            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
            "status": "idle", "session_id": "x", "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "role": "worker",
        })
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res.get("ok") is not True
        assert "ghostw" in res["error"]
        assert get_session(orch.id)["scope"] == "/old/proj"  # not moved

    @pytest.mark.asyncio
    async def test_archived_worker_does_not_block(self, mgr, tmp_path):
        from tests.conftest import make_backend_mock
        from app.session import AgentStatus
        from app.db import save_session
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            orch = await mgr.create_session(
                name="orch", scope="/old/proj", cwd="/tmp",
                model="claude-opus-4-8", is_orchestrator=True,
            )
        orch.session_id = "sdk-tok"
        orch.status = AgentStatus.IDLE
        save_session({
            "id": "dead-worker-id", "name": "deadw", "scope": "/old/proj",
            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
            "status": "archived", "session_id": "x", "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "role": "worker",
        })
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True
