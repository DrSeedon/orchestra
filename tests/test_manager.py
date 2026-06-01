"""TDD tests for manager.py — SessionManager."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
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


@pytest.fixture(autouse=True)
def _isolate_pipelines_dir(tmp_path, monkeypatch):
    """По умолчанию изолируем PIPELINES_DIR на пустой tmp.

    Делает модуль детерминированным независимо от реального ``pipelines/``
    (Stage 4 параллельно создаёт ``pipelines/default/``). Тесты, которым нужен
    манифест, переопределяют PIPELINES_DIR своей фикстурой (``pipeline_dir``/
    ``roles_dir``), которая выполняется ПОСЛЕ этой autouse и выигрывает.
    """
    import app.pipeline as pl
    empty = tmp_path / "_no_pipelines_default"
    empty.mkdir()
    monkeypatch.setattr(pl, "PIPELINES_DIR", empty)
    pl.load_pipeline.cache_clear()
    yield
    pl.load_pipeline.cache_clear()


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


def _git_repo(tmp_path):
    """Минимальный git-репо с веткой main для worktree-тестов."""
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
    return repo


class TestInjectSkillsGating:
    """F1: при skills=="all" native-инъекция скиллов пропускается."""

    async def _run(self, mgr, tmp_path, role_mock):
        from tests.conftest import make_backend_mock
        repo = _git_repo(tmp_path)
        inject = MagicMock()
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()), \
             patch("app.manager._inject_skills_to_worktree", inject), \
             patch("app.manager.get_role", role_mock):
            await mgr.create_session(
                name="w1", scope="/s", cwd=str(repo), model="m",
                use_worktree=True, repo_path=str(repo),
            )
        return inject

    @pytest.mark.asyncio
    async def test_skills_all_skips_injection(self, mgr, tmp_path):
        rr = MagicMock(skills="all", is_orchestrator=False)
        inject = await self._run(mgr, tmp_path, lambda p, r: rr)
        inject.assert_not_called()

    @pytest.mark.asyncio
    async def test_skills_list_injects(self, mgr, tmp_path):
        rr = MagicMock(skills=["foo", "bar"], is_orchestrator=False)
        inject = await self._run(mgr, tmp_path, lambda p, r: rr)
        inject.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_manifest_injects(self, mgr, tmp_path):
        def _raise(p, r):
            raise FileNotFoundError("no manifest")
        inject = await self._run(mgr, tmp_path, _raise)
        inject.assert_called_once()


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
        # TestCanSpawn проверяет LEGACY-fallback (_role_can_spawn по frontmatter),
        # который срабатывает ТОЛЬКО когда манифеста нет. Изолируем PIPELINES_DIR
        # на пустой tmp (без pipelines/default/), чтобы load_pipeline кидал
        # FileNotFoundError → fallback-ветка валидации в create_session.
        import app.pipeline as pl
        empty_pipelines = tmp_path / "no_pipelines"
        empty_pipelines.mkdir()
        monkeypatch.setattr(pl, "PIPELINES_DIR", empty_pipelines)
        pl.load_pipeline.cache_clear()
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


# ── Stage 3: loader integration (pipeline manifest) ─────────────────────────

# Мини-манифест, повторяющий ключевые роли sapto-pm для тестов фильтра/изоляции.
_MINI_MANIFEST = """\
name: testpipe
description: Test pipeline
validation: fail-closed
defaults:
  model: opus
  skills: all
  mcp_servers: all
  prompt_layers:
    orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
    worker: [base.md, "roles/{role}.md"]
roles:
  pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, can_spawn: [pm-fichi, secretary]}
  pm-fichi: {kind: orchestrator, label: Фича ПМ, order: 2, can_spawn: [coder, secretary]}
  coder: {kind: orchestrator, label: Кодер, order: 4, can_spawn: [secretary], allow_unrouted_workers: true}
  secretary: {kind: worker, label: Секретарь, can_spawn: []}
  worker: {kind: worker, label: Воркер, can_spawn: []}
"""


def _write_pipeline(root, name, manifest_text, prompts=None):
    """Создать pipelines/<name>/ с pipeline.yaml + prompts/* в tmp-корне root."""
    pdir = root / name
    (pdir / "prompts" / "roles").mkdir(parents=True)
    (pdir / "pipeline.yaml").write_text(manifest_text)
    prompts = prompts or {}
    for rel, content in prompts.items():
        target = pdir / "prompts" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return pdir


@pytest.fixture
def pipeline_dir(tmp_path, monkeypatch):
    """tmp pipelines/ с манифестом testpipe + базовыми слоями промптов.

    Монкипатчит ``app.pipeline.PIPELINES_DIR`` и чистит lru_cache загрузчика,
    чтобы манифест читался из tmp, а не из реального дерева (которого нет).
    """
    import app.pipeline as pl
    root = tmp_path / "pipelines"
    root.mkdir()
    _write_pipeline(root, "testpipe", _MINI_MANIFEST, prompts={
        "base.md": "BASE-LAYER",
        "roles/pm-glava.md": "ROLE pm-glava",
        "roles/pm-fichi.md": "ROLE pm-fichi",
        "roles/coder.md": "ROLE coder",
        "roles/secretary.md": "ROLE secretary",
        "roles/worker.md": "ROLE worker",
        "_pipeline.md": "PIPELINE-LAYER",
    })
    monkeypatch.setattr(pl, "PIPELINES_DIR", root)
    pl.load_pipeline.cache_clear()
    yield root
    pl.load_pipeline.cache_clear()


class TestUpstreamFallbackCharacterization:
    """Зафиксировать: при отсутствии манифеста ROLE_SYSTEM_PROMPT(pipeline, role)
    идентичен поведению апстрима (_UPSTREAM_ROLE_SYSTEM_PROMPT)."""

    def _write_role(self, roles_dir, name, frontmatter_body):
        (roles_dir / f"{name}.md").write_text(
            f"---\n{frontmatter_body}\n---\n\nBody for {name}.\n")

    @pytest.fixture
    def upstream_prompts(self, tmp_path, monkeypatch):
        prompts = tmp_path / "uprompts"
        rdir = prompts / "roles"
        rdir.mkdir(parents=True)
        (prompts / "base.md").write_text("BASE")
        monkeypatch.setattr("app.manager._PROMPTS_DIR", prompts)
        monkeypatch.setattr("app.manager._SKILLS_DIR", prompts / "skills")
        self._write_role(rdir, "orchestrator", "name: orchestrator\nlabel: Orchestrator")
        self._write_role(rdir, "worker", "name: worker\nlabel: Worker")
        return rdir

    def test_upstream_helper_orchestrator_matches_legacy_shape(self, upstream_prompts, db):
        """_UPSTREAM_ROLE_SYSTEM_PROMPT собирает base.md + тело роли (orchestrator)."""
        from app.manager import _UPSTREAM_ROLE_SYSTEM_PROMPT
        out = _UPSTREAM_ROLE_SYSTEM_PROMPT("orchestrator", "/some/scope")
        assert out.startswith("BASE")
        assert "Body for orchestrator." in out

    def test_upstream_helper_worker(self, upstream_prompts, db):
        from app.manager import _UPSTREAM_ROLE_SYSTEM_PROMPT
        out = _UPSTREAM_ROLE_SYSTEM_PROMPT("worker")
        assert out.startswith("BASE")
        assert "Body for worker." in out

    def test_no_manifest_falls_back_to_upstream(self, upstream_prompts, db):
        """Нет манифеста (FileNotFoundError) → ROLE_SYSTEM_PROMPT(pipeline, ...) ==
        _UPSTREAM_ROLE_SYSTEM_PROMPT (fallback идентичен апстриму)."""
        import app.pipeline as pl
        pl.load_pipeline.cache_clear()
        from app.manager import ROLE_SYSTEM_PROMPT, _UPSTREAM_ROLE_SYSTEM_PROMPT
        # "ghost-pipe" манифеста нет → fallback
        assert ROLE_SYSTEM_PROMPT("ghost-pipe", "orchestrator", "/s") == \
            _UPSTREAM_ROLE_SYSTEM_PROMPT("orchestrator", "/s")
        assert ROLE_SYSTEM_PROMPT("ghost-pipe", "worker") == \
            _UPSTREAM_ROLE_SYSTEM_PROMPT("worker")


class TestRoleSystemPromptManifest:
    def test_static_layers_from_manifest(self, pipeline_dir, db):
        """ROLE_SYSTEM_PROMPT берёт статику из pipelines/<name>/prompts/ (изоляция)."""
        from app.manager import ROLE_SYSTEM_PROMPT
        out = ROLE_SYSTEM_PROMPT("testpipe", "coder", "/s")
        assert "BASE-LAYER" in out
        assert "ROLE coder" in out
        assert "PIPELINE-LAYER" in out  # coder — orchestrator → _pipeline.md есть

    def test_worker_role_no_pipeline_layer(self, pipeline_dir, db):
        """Воркер (kind:worker) НЕ получает _pipeline.md."""
        from app.manager import ROLE_SYSTEM_PROMPT
        out = ROLE_SYSTEM_PROMPT("testpipe", "secretary")
        assert "BASE-LAYER" in out
        assert "ROLE secretary" in out
        assert "PIPELINE-LAYER" not in out

    def test_orchestrator_gets_filtered_catalog(self, pipeline_dir, db):
        """Оркестратор pm-glava видит каталог только pm-fichi+secretary (can_spawn)."""
        from app.manager import ROLE_SYSTEM_PROMPT
        out = ROLE_SYSTEM_PROMPT("testpipe", "pm-glava", "/s")
        assert "pm-fichi" in out
        assert "secretary" in out
        # coder и worker НЕ в can_spawn pm-glava → нет их записей в каталоге
        # (проверяем заголовок записи ### `name`, т.к. слово worker есть в шапке каталога)
        assert "### `coder`" not in out
        assert "### `worker`" not in out


class TestRolesCatalogFromManifest:
    def test_pm_glava_shows_only_pm_fichi_and_secretary(self, pipeline_dir):
        from app.manager import _roles_catalog_from_manifest
        cat = _roles_catalog_from_manifest("testpipe", "pm-glava")
        assert "### `pm-fichi`" in cat
        assert "### `secretary`" in cat
        assert "### `coder`" not in cat
        assert "### `worker`" not in cat

    def test_sorted_by_order(self, pipeline_dir):
        """pm-fichi (order 2) перед secretary (order 100, дефолт)."""
        from app.manager import _roles_catalog_from_manifest
        cat = _roles_catalog_from_manifest("testpipe", "pm-glava")
        assert cat.index("pm-fichi") < cat.index("secretary")

    def test_star_can_spawn_shows_all(self, tmp_path, monkeypatch):
        """can_spawn=['*'] → каталог показывает ВСЕ роли пайплайна."""
        import app.pipeline as pl
        root = tmp_path / "pipelines"
        root.mkdir()
        manifest = (
            "name: starpipe\nvalidation: fail-open\n"
            "roles:\n"
            "  boss: {kind: orchestrator, label: Boss, order: 0, can_spawn: ['*']}\n"
            "  a: {kind: worker, label: A, order: 1, can_spawn: []}\n"
            "  b: {kind: worker, label: B, order: 2, can_spawn: []}\n"
        )
        _write_pipeline(root, "starpipe", manifest, prompts={"base.md": "B"})
        monkeypatch.setattr(pl, "PIPELINES_DIR", root)
        pl.load_pipeline.cache_clear()
        from app.manager import _roles_catalog_from_manifest
        cat = _roles_catalog_from_manifest("starpipe", "boss")
        pl.load_pipeline.cache_clear()
        assert "### `a`" in cat
        assert "### `b`" in cat


class TestPromptIsolation:
    def test_app_prompts_not_read_in_manifest_path(self, pipeline_dir, db, monkeypatch):
        """Манифест-путь НЕ читает app/prompts/ — отсутствие _PROMPTS_DIR не ломает."""
        # Указываем _PROMPTS_DIR на несуществующий путь — manifest-путь должен работать.
        monkeypatch.setattr("app.manager._PROMPTS_DIR", Path("/nonexistent/app/prompts"))
        from app.manager import ROLE_SYSTEM_PROMPT
        out = ROLE_SYSTEM_PROMPT("testpipe", "coder", "/s")
        assert "BASE-LAYER" in out  # из pipelines/testpipe/prompts/, не из app/prompts/
        assert "ROLE coder" in out


class TestValidateSpawnIntegration:
    @pytest.mark.asyncio
    async def test_forbidden_spawn_blocked_before_side_effect(self, mgr, pipeline_dir, tmp_path):
        """pm-glava НЕ может спавнить coder (нет в can_spawn) — ValueError ДО worktree."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        import subprocess
        repo = tmp_path / "repo2"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)

        save_session({
            "id": "pg-1", "name": "glava", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "pm-glava", "pipeline": "testpipe",
        })
        wt_calls = {"n": 0}
        real_cw = __import__("app.workspace", fromlist=["create_worktree"]).create_worktree

        def counting_cw(*a, **k):
            wt_calls["n"] += 1
            return real_cw(*a, **k)

        with patch("app.manager.create_worktree", side_effect=counting_cw):
            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                with pytest.raises(ValueError, match="cannot spawn"):
                    await mgr.create_session(
                        name="child-coder", scope="/s", cwd=str(repo), model="opus",
                        role="coder", parent_name="glava",
                        use_worktree=True, repo_path=str(repo), pipeline="testpipe",
                    )
        assert wt_calls["n"] == 0, "worktree не должен создаваться при запрещённом спавне"

    @pytest.mark.asyncio
    async def test_allowed_spawn_passes(self, mgr, pipeline_dir):
        """pm-glava МОЖЕТ спавнить secretary (в can_spawn)."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pg-2", "name": "glava", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "pm-glava", "pipeline": "testpipe",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="sec-1", scope="/s", cwd="/tmp", model="opus",
                role="secretary", parent_name="glava", pipeline="testpipe",
            )
        assert session.name == "sec-1"

    @pytest.mark.asyncio
    async def test_fallback_when_no_manifest(self, mgr, monkeypatch):
        """Нет манифеста → validate_spawn кидает FileNotFoundError → fallback _role_can_spawn.

        Воссоздаём fixture roles_dir-стиль для fallback-ветки.
        """
        from app.db import save_session
        from tests.conftest import make_backend_mock
        import app.pipeline as pl
        # Форсим отсутствие манифеста: PIPELINES_DIR на пустой tmp (Stage 4 мог
        # создать pipelines/default/) → load_pipeline FileNotFoundError → fallback.
        import tempfile
        empty = Path(tempfile.mkdtemp()) / "no_pipelines"
        empty.mkdir()
        monkeypatch.setattr(pl, "PIPELINES_DIR", empty)
        pl.load_pipeline.cache_clear()
        prompts = Path(self._mk_prompts(monkeypatch))
        save_session({
            "id": "p-fb", "name": "boss", "scope": "/s", "cwd": "/tmp",
            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "color": "#fff",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "boss",
        })
        (prompts / "roles" / "boss.md").write_text("---\nname: boss\ncan_spawn: [worker]\n---\nB")
        (prompts / "roles" / "full-cycle.md").write_text("---\nname: full-cycle\n---\nB")
        pl.load_pipeline.cache_clear()
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            with pytest.raises(ValueError, match="not allowed to spawn"):
                await mgr.create_session(
                    name="child", scope="/s", cwd="/tmp", model="m",
                    role="full-cycle", parent_name="boss",
                )

    def _mk_prompts(self, monkeypatch):
        import tempfile
        d = tempfile.mkdtemp()
        prompts = Path(d) / "prompts"
        (prompts / "roles").mkdir(parents=True)
        (prompts / "base.md").write_text("BASE")
        monkeypatch.setattr("app.manager._PROMPTS_DIR", prompts)
        monkeypatch.setattr("app.manager._SKILLS_DIR", prompts / "skills")
        return str(prompts)


class TestIsOrchestratorDenormalization:
    @pytest.mark.asyncio
    async def test_is_orch_from_manifest_kind(self, mgr, pipeline_dir):
        """coder (kind:orchestrator в манифесте) → session.is_orchestrator=True,
        хотя в frozenset апстрима его нет."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="coder-1", scope="/s", cwd="/tmp", model="opus",
                role="coder", is_orchestrator=True, pipeline="testpipe",
            )
        assert session.is_orchestrator is True
        assert session.pipeline == "testpipe"

    @pytest.mark.asyncio
    async def test_worker_kind_is_not_orchestrator(self, mgr, pipeline_dir):
        """secretary (kind:worker) → is_orchestrator=False даже при is_orchestrator=True arg."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pg-3", "name": "glava", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "pm-glava", "pipeline": "testpipe",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="sec-2", scope="/s", cwd="/tmp", model="opus",
                role="secretary", parent_name="glava", pipeline="testpipe",
            )
        assert session.is_orchestrator is False

    @pytest.mark.asyncio
    async def test_fallback_is_orch_when_no_manifest(self, mgr):
        """Нет манифеста → is_orch из is_orchestrator_role(role) (frozenset)."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="orch-fb", scope="/s", cwd="/tmp", model="m",
                role="orchestrator", is_orchestrator=True,
            )
        assert session.is_orchestrator is True


class TestPipelineInheritance:
    @pytest.mark.asyncio
    async def test_child_inherits_parent_pipeline(self, mgr, pipeline_dir):
        """Воркер без явного pipeline наследует пайплайн родителя."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pg-4", "name": "coderboss", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "coder", "pipeline": "testpipe",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            # coder.allow_unrouted_workers=true → generic worker (без role) допустим;
            # пайплайн наследуется от родителя coderboss (testpipe).
            session = await mgr.create_session(
                name="w-inh", scope="/s", cwd="/tmp", model="opus",
                parent_name="coderboss",
            )
        assert session.pipeline == "testpipe"

    @pytest.mark.asyncio
    async def test_root_defaults_to_default_pipeline(self, mgr, monkeypatch):
        """Корневой оркестратор без parent и без pipeline → DEFAULT_PIPELINE."""
        from tests.conftest import make_backend_mock
        from app.pipeline import DEFAULT_PIPELINE
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="root-orch", scope="/s", cwd="/tmp", model="m",
                role="orchestrator", is_orchestrator=True,
            )
        assert session.pipeline == DEFAULT_PIPELINE

    @pytest.mark.asyncio
    async def test_auto_found_parent_pipeline_inherited(self, mgr, pipeline_dir):
        """Воркер без явного parent_name авто-находит оркестратора в scope и
        наследует ЕГО пайплайн (не DEFAULT)."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            # активный оркестратор coder в scope с pipeline=testpipe
            await mgr.create_session(
                name="coderboss2", scope="/s", cwd="/tmp", model="opus",
                role="coder", is_orchestrator=True, pipeline="testpipe",
            )
            # generic worker без parent_name → авто-находит coderboss2 → testpipe
            worker = await mgr.create_session(
                name="auto-w", scope="/s", cwd="/tmp", model="opus",
            )
        assert worker.pipeline == "testpipe"
        assert worker.parent_name == "coderboss2"


class TestProfileInheritance:
    """Профиль Claude протягивается через create_session и наследуется детьми.

    Зеркало TestPipelineInheritance, но дефолт профиля — пусто (env процесса),
    а не константа.
    """

    @pytest.mark.asyncio
    async def test_root_with_profile_persists(self, mgr):
        """Корневой оркестратор с явным profile → session.profile и персист в БД."""
        from app.db import get_session_by_name
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="root-orch", scope="/s", cwd="/tmp", model="m",
                role="orchestrator", is_orchestrator=True, profile="work",
            )
        assert session.profile == "work"
        row = get_session_by_name("root-orch", "/s")
        assert row is not None
        assert row["profile"] == "work"

    @pytest.mark.asyncio
    async def test_child_inherits_parent_profile(self, mgr):
        """Ребёнок без явного profile наследует профиль родителя."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pp-1", "name": "boss", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "orchestrator", "pipeline": "", "profile": "work",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="child", scope="/s", cwd="/tmp", model="opus",
                parent_name="boss",
            )
        assert session.profile == "work"

    @pytest.mark.asyncio
    async def test_explicit_profile_overrides_inheritance(self, mgr):
        """Явный profile у ребёнка переопределяет наследование от родителя."""
        from app.db import save_session
        from tests.conftest import make_backend_mock
        save_session({
            "id": "pp-2", "name": "boss2", "scope": "/s", "cwd": "/tmp",
            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "role": "orchestrator", "pipeline": "", "profile": "work",
        })
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="child2", scope="/s", cwd="/tmp", model="opus",
                parent_name="boss2", profile="personal",
            )
        assert session.profile == "personal"

    @pytest.mark.asyncio
    async def test_no_profile_anywhere_is_empty(self, mgr):
        """Профиля нет ни явно, ни у родителя → session.profile == '' (env процесса)."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr.create_session(
                name="w-noprof", scope="/s", cwd="/tmp", model="m",
                role="orchestrator", is_orchestrator=True,
            )
        assert session.profile == ""

    @pytest.mark.asyncio
    async def test_auto_found_parent_profile_inherited(self, mgr):
        """Воркер без явного parent_name авто-находит оркестратора в scope и
        наследует ЕГО профиль."""
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.create_session(
                name="orch-prof", scope="/s", cwd="/tmp", model="opus",
                role="orchestrator", is_orchestrator=True, profile="work",
            )
            worker = await mgr.create_session(
                name="auto-w-prof", scope="/s", cwd="/tmp", model="opus",
            )
        assert worker.profile == "work"
        assert worker.parent_name == "orch-prof"
