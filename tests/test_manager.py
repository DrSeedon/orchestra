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
def _isolate_pipelines_dir(monkeypatch):
    """Point PIPELINES_DIR at the REAL pipelines/ so ROLE_SYSTEM_PROMPT resolves.

    Was: isolated to an empty tmp dir, relying on the app/prompts legacy fallback
    to still produce prompts. That fallback is removed (single source = pipelines),
    so ROLE_SYSTEM_PROMPT now fails loud on a missing manifest. These tests don't
    test prompts — they need SOME valid pipeline, so use the real default.
    Tests that want a custom manifest override PIPELINES_DIR via ``pipeline_dir``.
    """
    import app.pipeline as pl
    from pathlib import Path
    real = Path(__file__).parent.parent / "pipelines"
    monkeypatch.setattr(pl, "PIPELINES_DIR", real)
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
                model="claude-sonnet-5[1m]",
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
             patch("app.manager.inject_skills_to_worktree", inject), \
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
        # resolved pipeline skills are passed through, not the role name
        assert inject.call_args.args[0] == ["foo", "bar"]

    @pytest.mark.asyncio
    async def test_no_manifest_raises(self, mgr, tmp_path):
        # Was test_no_manifest_injects: legacy fallback let a spawn proceed (and
        # inject skills) when get_role raised FileNotFoundError. Fallback removed →
        # missing manifest is fail loud, spawn aborts before skill injection.
        def _raise(p, r):
            raise FileNotFoundError("no manifest")
        with pytest.raises((FileNotFoundError, ValueError)):
            await self._run(mgr, tmp_path, _raise)


class TestInjectSkillsRealCopy:
    """T0 AC: real injector actually copies skills/<name>.md → worktree/.claude/skills/<name>/SKILL.md.

    The mocked gating tests prove the resolved list is passed; this proves files land on disk.
    """

    def test_copies_pipeline_skills_to_worktree(self, tmp_path):
        from app.prompting import inject_skills_to_worktree
        wt = tmp_path / "wt"
        wt.mkdir()
        # codex-debate + html-artifacts are both real files in prompts/skills/
        inject_skills_to_worktree(["codex-debate", "html-artifacts"], str(wt))
        for name in ("codex-debate", "html-artifacts"):
            assert (wt / ".claude" / "skills" / name / "SKILL.md").is_file(), \
                f"{name} not injected into worktree"

    def test_empty_list_is_noop(self, tmp_path):
        from app.prompting import inject_skills_to_worktree
        wt = tmp_path / "wt"
        wt.mkdir()
        inject_skills_to_worktree([], str(wt))
        assert not (wt / ".claude").exists()


class TestResolveBaseBranch:
    """DESIGN §10: резолв base_branch по стратегии манифеста (B3).

    Тестируем ``_resolve_base_branch`` напрямую на инстансе manager, мокая
    ``app.manager.get_role`` (как в TestInjectSkillsGating) и подсовывая
    родителя в ``mgr.sessions`` через лёгкий объект с атрибутом ``branch``.
    """

    def _put_parent(self, mgr, name, scope, branch):
        """Лёгкий родитель в кэше сессий с нужной веткой (без БД)."""
        parent = MagicMock()
        parent.name = name
        parent.scope = scope
        parent.branch = branch
        mgr.sessions[name] = parent

    def test_strategy_main_returns_main(self, mgr):
        rr = MagicMock(base_branch_strategy="main")
        with patch("app.manager.get_role", lambda p, r: rr):
            out = mgr._resolve_base_branch("", "default", "pm-glava", "", "/s")
        assert out == "main"

    def test_strategy_parent_uses_parent_branch(self, mgr):
        rr = MagicMock(base_branch_strategy="parent")
        self._put_parent(mgr, "pm", "/s", "feature/x")
        with patch("app.manager.get_role", lambda p, r: rr):
            out = mgr._resolve_base_branch("", "tasks-pm", "coder", "pm", "/s")
        assert out == "feature/x"

    def test_strategy_parent_no_branch_falls_back_to_main(self, mgr, caplog):
        import logging
        rr = MagicMock(base_branch_strategy="parent")
        self._put_parent(mgr, "pm", "/s", "")  # у родителя нет ветки
        with patch("app.manager.get_role", lambda p, r: rr), caplog.at_level(logging.WARNING):
            out = mgr._resolve_base_branch("", "tasks-pm", "coder", "pm", "/s")
        assert out == "main"
        assert any("fallback на main" in rec.message for rec in caplog.records)

    def test_explicit_branch_overrides_strategy(self, mgr):
        # B3: явная ветка важнее strategy="parent" — get_role даже не зовётся.
        rr = MagicMock(base_branch_strategy="parent")
        self._put_parent(mgr, "pm", "/s", "feature/x")
        with patch("app.manager.get_role", lambda p, r: rr):
            out = mgr._resolve_base_branch("dev", "tasks-pm", "coder", "pm", "/s")
        assert out == "dev"

    def test_no_manifest_returns_main(self, mgr):
        def _raise(p, r):
            raise FileNotFoundError("no manifest")
        with patch("app.manager.get_role", _raise):
            out = mgr._resolve_base_branch("", "nope", "coder", "pm", "/s")
        assert out == "main"


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
        # v2.16: remove() — мягкое удаление (archive), а не DELETE. Сессия уходит
        # из runtime-словаря, а в БД помечается status='archived' (история жива).
        assert mgr.get(session.id) is None
        row = get_session(session.id)
        assert row is not None and row["status"] == "archived"


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

    @pytest.mark.asyncio
    async def test_runtime_cache_policy_for_active_and_persisted_sessions(self, mgr):
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            claude = await mgr.create_session(
                name="claude-cache", scope="/s", cwd="/tmp",
                model="claude-sonnet-5[1m]",
            )
            codex = await mgr.create_session(
                name="codex-cache", scope="/s", cwd="/tmp",
                model="gpt-5.6-sol",
            )
        mgr.sessions.pop(codex.id)

        rows = {row["name"]: row for row in mgr.list_sessions(scope="/s")}
        assert rows[claude.name]["cache_ttl_seconds"] == 3600
        assert rows[claude.name]["cache_ttl_approximate"] is False
        assert rows[codex.name]["cache_ttl_seconds"] == 1800
        assert rows[codex.name]["cache_ttl_approximate"] is True


class TestRemoveScope:
    @pytest.mark.asyncio
    async def test_passes_orch_names_to_tg_bridge_when_flag_set(self, mgr, monkeypatch):
        """remove_scope с delete_tg_topics=True должен передать имена орков в tg_bridge."""
        from app.db import save_session
        save_session({
            "id": "orch-x", "name": "orch-x-orchestrator", "scope": "/scope-x",
            "cwd": "/tmp", "model": "claude-opus-4-8[1m]", "system_prompt": "",
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

        mgr.tg_topics_remover = fake_remove  # P3: wired callback, not tg_bridge import

        result = await mgr.remove_scope("/scope-x", delete_tg_topics=True)

        assert called["names"] == ["orch-x-orchestrator"]
        assert result["tg"]["deleted"] == ["orch-x-orchestrator"]

    @pytest.mark.asyncio
    async def test_skips_tg_bridge_when_flag_false(self, mgr, monkeypatch):
        from app.db import save_session
        save_session({
            "id": "orch-y", "name": "orch-y-orchestrator", "scope": "/scope-y",
            "cwd": "/tmp", "model": "claude-opus-4-8[1m]", "system_prompt": "",
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

        mgr.tg_topics_remover = fake_remove  # P3: wired callback, not tg_bridge import

        result = await mgr.remove_scope("/scope-y", delete_tg_topics=False)

        assert called["hit"] is False
        assert result["tg"] == {}


class TestAutoResume:
    @pytest.mark.asyncio
    async def test_resumes_orchestrators(self, mgr):
        from app.db import save_session
        save_session({
            "id": "orch-1", "name": "orchestrator", "scope": "/tmp",
            "cwd": "/tmp", "model": "claude-opus-4-8[1m]", "system_prompt": "",
            "status": "idle", "session_id": "sdk-123",
            "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": True, "role": "orchestrator", "pipeline": "default",
            "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })
        from tests.conftest import make_backend_mock
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            await mgr.auto_resume_all()
        assert mgr.get("orch-1") is not None

    @pytest.mark.asyncio
    async def test_resume_normalizes_empty_pipeline(self, mgr):
        """Old migrated rows store pipeline='' → _load_from_db must normalize to
        DEFAULT_PIPELINE. Without it ROLE_SYSTEM_PROMPT('') fails loud (fallback
        removed) and pre-pipeline sessions can't resume."""
        from app.db import save_session, get_session_by_name
        from tests.conftest import make_backend_mock
        save_session({
            "id": "old-empty-pipe", "name": "oldw", "scope": "/tmp", "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
            "session_id": None, "cost_usd": 0.0, "worktree_path": None, "branch": None,
            "is_orchestrator": False, "role": "worker", "pipeline": "",
            "color": "#fff", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        })
        row = get_session_by_name("oldw", "/tmp")
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr._load_from_db(row)  # must NOT raise ValueError
        assert session.name == "oldw"
        assert session.system_prompt  # prompt built from default pipeline



class TestCanSpawn:
    def _write_role(self, roles_dir, name, frontmatter_body):
        (roles_dir / f"{name}.md").write_text(f"---\n{frontmatter_body}\n---\n\nBody for {name}.\n")

    @pytest.fixture
    def roles_dir(self, tmp_path, monkeypatch):
        # can_spawn is read from temp frontmatter (_PROMPTS_DIR). The prompt build
        # (ROLE_SYSTEM_PROMPT) reads real pipelines/ — the app/prompts fallback is
        # removed, so an empty PIPELINES_DIR would fail loud. These tests assert
        # spawn-whitelist behaviour and spawn role="worker" (present in default),
        # so point at the real default pipeline for the prompt step.
        from pathlib import Path
        prompts = tmp_path / "prompts"
        rdir = prompts / "roles"
        rdir.mkdir(parents=True)
        (prompts / "base.md").write_text("BASE")
        monkeypatch.setattr("app.prompting._PROMPTS_DIR", prompts)
        monkeypatch.setattr("app.prompting._SKILLS_DIR", prompts / "skills")
        import app.pipeline as pl
        monkeypatch.setattr(pl, "PIPELINES_DIR", Path(__file__).parent.parent / "pipelines")
        pl.load_pipeline.cache_clear()
        return rdir

    def test_role_can_spawn_absent_is_none(self, roles_dir):
        from app.prompting import role_can_spawn as _role_can_spawn
        self._write_role(roles_dir, "boss", "name: boss\nmodel: opus")
        assert _role_can_spawn("boss") is None

    def test_role_can_spawn_yaml_null_is_none(self, roles_dir):
        from app.prompting import role_can_spawn as _role_can_spawn
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn:")
        assert _role_can_spawn("boss") is None

    def test_role_can_spawn_non_list_is_none(self, roles_dir):
        from app.prompting import role_can_spawn as _role_can_spawn
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: worker")
        assert _role_can_spawn("boss") is None

    def test_role_can_spawn_empty_list_is_terminal(self, roles_dir):
        from app.prompting import role_can_spawn as _role_can_spawn
        self._write_role(roles_dir, "leaf", "name: leaf\ncan_spawn: []")
        assert _role_can_spawn("leaf") == []

    def test_role_can_spawn_whitelist(self, roles_dir):
        from app.prompting import role_can_spawn as _role_can_spawn
        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker, reviewer]")
        assert _role_can_spawn("boss") == ["worker", "reviewer"]

    def test_role_can_spawn_missing_file_is_none(self, roles_dir):
        from app.prompting import role_can_spawn as _role_can_spawn
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

    # REMOVED: test_whitelist_blocks_unlisted + test_empty_can_spawn_blocks_all.
    # They tested the legacy frontmatter can_spawn fallback (role_can_spawn reading
    # app/prompts/roles/*.md) triggered when validate_spawn hits FileNotFoundError.
    # app/prompts is removed and the manifest is the single source — spawn-whitelist
    # enforcement is now covered by validate_spawn / TestRolesCatalogFromManifest.
    # These tested removed legacy behaviour, so they're deleted (not "broken").

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
            "role": "worker", "pipeline": "default", "mcp_servers_custom": json.dumps(custom),
        })
        row = get_session_by_name("w24c", "/s")
        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
            session = await mgr._load_from_db(row)
        assert session.mcp_servers_custom == custom
        assert "playwright" in session.mcp_servers
        assert "orchestra" in session.mcp_servers


# ── Stage 3: loader integration (pipeline manifest) ─────────────────────────

# Мини-манифест, повторяющий ключевые роли tasks-pm для тестов фильтра/изоляции.
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


class TestRoleSystemPromptFailLoud:
    """app/prompts legacy-fallback удалён → нет манифеста ИЛИ роли → ValueError (fail loud).

    Раньше здесь был TestUpstreamFallbackCharacterization (3 теста) — он проверял
    _UPSTREAM_ROLE_SYSTEM_PROMPT, который РЕАЛЬНО собирал промпт из app/prompts при
    отсутствии манифеста. Тот код удалён (единый источник = pipelines/), поэтому
    тесты его поведения удалены, а не «сломались». Новое поведение — fail loud."""

    def test_no_manifest_raises(self, db):
        import app.pipeline as pl
        pl.load_pipeline.cache_clear()
        from app.manager import ROLE_SYSTEM_PROMPT
        with pytest.raises(ValueError, match="not resolvable"):
            ROLE_SYSTEM_PROMPT("ghost-pipe-no-manifest", "orchestrator", "/s")


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

    def test_unknown_role_raises(self, pipeline_dir, db):
        """Роли нет в манифесте (KeyError) → fail loud (ValueError), НЕ молчаливый
        fallback. Раньше делегировал в _UPSTREAM_ROLE_SYSTEM_PROMPT (app/prompts,
        удалён). Теперь роль обязана быть в pipeline.yaml или это ошибка."""
        from app.manager import ROLE_SYSTEM_PROMPT
        with pytest.raises(ValueError, match="not resolvable"):
            ROLE_SYSTEM_PROMPT("testpipe", "my-custom-worker")


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
        # S1: wildcard НЕ включает саму роль-родителя.
        assert "### `boss`" not in cat


class TestPromptIsolation:
    def test_app_prompts_not_read_in_manifest_path(self, pipeline_dir, db, monkeypatch):
        """Манифест-путь НЕ читает app/prompts/ — отсутствие _PROMPTS_DIR не ломает."""
        # Указываем _PROMPTS_DIR на несуществующий путь — manifest-путь должен работать.
        monkeypatch.setattr("app.prompting._PROMPTS_DIR", Path("/nonexistent/app/prompts"))
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

    # REMOVED: test_fallback_when_no_manifest — tested the legacy _role_can_spawn
    # frontmatter fallback (app/prompts) that fired on FileNotFoundError. That
    # fallback is removed (single source = pipelines, fail loud on missing manifest).

    def _mk_prompts(self, monkeypatch):
        import tempfile
        d = tempfile.mkdtemp()
        prompts = Path(d) / "prompts"
        (prompts / "roles").mkdir(parents=True)
        (prompts / "base.md").write_text("BASE")
        monkeypatch.setattr("app.prompting._PROMPTS_DIR", prompts)
        monkeypatch.setattr("app.prompting._SKILLS_DIR", prompts / "skills")
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
            s = await mgr.create_session(name=name, scope=scope, cwd="/tmp", model="claude-sonnet-5[1m]")
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
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "",
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
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": "archived", "session_id": "x", "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "role": "worker",
        })
        newdir = tmp_path / "newproj"; newdir.mkdir()
        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
        assert res["ok"] is True


class TestManagerLifecycle:
    @pytest.mark.asyncio
    async def test_shutdown_rebinds_background_primitives_for_next_event_loop(self, mgr):
        old_queue = mgr._spawn_queue
        mgr.start_background_tasks()
        await asyncio.sleep(0)

        await mgr.shutdown_all()

        assert mgr._spawn_task is None
        assert mgr._cleanup_task is None
        assert mgr._wt_cleanup_task is None
        assert mgr._spawn_queue is not old_queue
        assert mgr._session_locks == {}


class TestLiveChildren:
    """Orphan-guard: _live_children finds active sub-workers of a parent."""

    def _row(self, name, parent_name, status, scope="/proj"):
        from datetime import datetime, timezone
        return {
            "id": f"id-{name}", "name": name, "scope": scope,
            "cwd": "/tmp", "model": "claude-sonnet-5[1m]", "system_prompt": "",
            "status": status, "session_id": "x", "cost_usd": 0.0,
            "worktree_path": None, "branch": None, "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "role": "worker", "parent_name": parent_name,
        }

    def test_finds_live_children_from_db(self, mgr):
        from app.db import save_session
        save_session(self._row("child-a", "parent-w", "idle"))
        save_session(self._row("child-b", "parent-w", "running"))
        assert mgr._live_children("parent-w", "/proj") == ["child-a", "child-b"]

    def test_archived_children_not_blocking(self, mgr):
        from app.db import save_session
        save_session(self._row("child-dead", "parent-w", "archived"))
        assert mgr._live_children("parent-w", "/proj") == []

    def test_only_own_children(self, mgr):
        from app.db import save_session
        save_session(self._row("mine", "parent-w", "idle"))
        save_session(self._row("other", "another-parent", "idle"))
        assert mgr._live_children("parent-w", "/proj") == ["mine"]

    def test_scope_isolation(self, mgr):
        from app.db import save_session
        save_session(self._row("here", "parent-w", "idle", scope="/proj"))
        save_session(self._row("elsewhere", "parent-w", "idle", scope="/other"))
        assert mgr._live_children("parent-w", "/proj") == ["here"]

    def test_empty_parent_name_returns_empty(self, mgr):
        assert mgr._live_children("", "/proj") == []

    def test_no_children_returns_empty(self, mgr):
        from app.db import save_session
        save_session(self._row("lonely", "", "idle"))
        assert mgr._live_children("parent-w", "/proj") == []
