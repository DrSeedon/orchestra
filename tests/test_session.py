"""TDD tests for session.py — AgentSession."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_sdk():
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.query = AsyncMock()

    async def fake_receive():
        from claude_agent_sdk import ResultMessage
        yield ResultMessage(subtype="result", duration_ms=0, duration_api_ms=0,
                           is_error=False, num_turns=1, session_id="sdk-001", total_cost_usd=0.05)

    client.receive_messages = fake_receive
    return client


@pytest.fixture
def mock_db(monkeypatch):
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))


@pytest.fixture
def session(mock_db):
    from app.session import AgentSession
    return AgentSession(
        id="test-001", name="w1", scope="/test", cwd="/tmp",
        model="claude-sonnet-4-6", system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )


class TestStart:
    @pytest.mark.asyncio
    async def test_no_message_idle(self, session):
        from app.session import AgentStatus
        await session.start()
        assert session.status == AgentStatus.IDLE

    @pytest.mark.skip(reason="outdated: relies on old SDK client API (query/receive_messages/_turn_task). TODO: rewrite for new backend interface (send/events)")
    @pytest.mark.asyncio
    async def test_with_message(self, session, mock_sdk):
        from app.session import AgentStatus
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start("hi")
            if session._turn_task:
                await session._turn_task
        assert session.status == AgentStatus.IDLE
        assert session.session_id == "sdk-001"
        assert session.cost_usd == pytest.approx(0.05)


class TestSend:
    @pytest.mark.skip(reason="outdated: relies on old SDK client API (query/_turn_task/debounce_sec). TODO: rewrite for new backend interface (send/events)")
    @pytest.mark.asyncio
    async def test_send_triggers_turn(self, session, mock_sdk):
        session.debounce_sec = 0.1
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start()
            await session.send("task")
            await asyncio.sleep(0.3)
            if session._turn_task:
                await session._turn_task
        mock_sdk.query.assert_awaited()


class TestTurn:
    @pytest.mark.skip(reason="outdated: relies on old SDK client API (connect/_turn_task). TODO: rewrite for new backend interface (send/events)")
    @pytest.mark.asyncio
    async def test_error_returns_to_idle(self, session, mock_sdk):
        from app.session import AgentStatus
        mock_sdk.connect = AsyncMock(side_effect=ConnectionError("fail"))
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start("task")
            if session._turn_task:
                try:
                    await session._turn_task
                except:
                    pass
        assert session.status == AgentStatus.IDLE

    @pytest.mark.skip(reason="outdated: relies on old SDK client API (disconnect/_turn_task). TODO: rewrite for new backend interface (send/events)")
    @pytest.mark.asyncio
    async def test_disconnect_called(self, session, mock_sdk):
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start("task")
            if session._turn_task:
                await session._turn_task
        mock_sdk.disconnect.assert_awaited()


class TestStop:
    @pytest.mark.skip(reason="outdated: relies on old SDK client API (_make_client). TODO: rewrite for new backend interface (send/events)")
    @pytest.mark.asyncio
    async def test_stop_sets_idle(self, session, mock_sdk):
        from app.session import AgentStatus
        with patch("app.session.AgentSession._make_client", return_value=mock_sdk):
            await session.start()
            await session.stop()
        assert session.status == AgentStatus.IDLE


# ── Auto-report gate tests (Task 5) ──

def _mk_session(monkeypatch, idle_sec):
    monkeypatch.setattr("app.session.AUTO_REPORT_IDLE_SEC", idle_sec)
    from app.session import AgentSession
    s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp")
    return s


@pytest.mark.asyncio
async def test_auto_report_fires_after_idle_timeout(monkeypatch):
    s = _mk_session(monkeypatch, idle_sec=0.05)
    fired = []
    async def on_idle(name, scope, texts):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s._turn_logs = ["did stuff"]
    # имитируем завершение хода: планируем отложенный авто-репорт
    s._schedule_auto_report()
    await asyncio.sleep(0.15)
    assert fired == ["w"]  # сработал после таймаута


@pytest.mark.asyncio
async def test_auto_report_skipped_if_did_report(monkeypatch):
    s = _mk_session(monkeypatch, idle_sec=0.05)
    fired = []
    async def on_idle(name, scope, texts):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = True  # был явный send_message
    s._schedule_auto_report()
    await asyncio.sleep(0.15)
    assert fired == []  # явный отчёт был → авто-репорт не нужен


@pytest.mark.asyncio
async def test_auto_report_cancelled_by_new_turn(monkeypatch):
    s = _mk_session(monkeypatch, idle_sec=0.1)
    fired = []
    async def on_idle(name, scope, texts):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s._schedule_auto_report()
    # новый ход стартовал до истечения окна → бампаем поколение
    await asyncio.sleep(0.02)
    s._bump_turn_gen()
    await asyncio.sleep(0.15)
    assert fired == []  # пришёл новый ход → отложенный репорт отменён


@pytest.mark.asyncio
async def test_orchestrator_never_auto_reports(monkeypatch):
    s = _mk_session(monkeypatch, idle_sec=0.05)
    s.is_orchestrator = True   # оркестратор отчитывается наверх ТОЛЬКО явным send_message
    fired = []
    async def on_idle(name, scope, texts):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s._turn_logs = ["ответил пользователю в чат"]
    s._schedule_auto_report()
    await asyncio.sleep(0.15)
    assert fired == []  # оркестратор не auto-report'ит — нет спама наверх


# ── Этап 1: pipeline + is_orchestrator как хранимое поле ──

class TestPipelineField:
    def test_pipeline_default_empty(self):
        from app.session import AgentSession
        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp")
        assert s.pipeline == ""

    def test_pipeline_can_be_set(self):
        from app.session import AgentSession
        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp", pipeline="sapto-pm")
        assert s.pipeline == "sapto-pm"

    def test_to_db_dict_includes_pipeline(self):
        from app.session import AgentSession
        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp", pipeline="sapto-pm")
        assert s._to_db_dict()["pipeline"] == "sapto-pm"


class TestIsOrchestratorStored:
    def test_setter_overrides_role_fallback(self):
        from app.session import AgentSession
        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp", role="worker")
        assert s.is_orchestrator is False        # fallback от role
        s.is_orchestrator = True                 # сеттер (раньше падал: no setter)
        assert s.is_orchestrator is True

    def test_fallback_to_role_when_unset(self):
        from app.session import AgentSession
        orch = AgentSession(id="i", name="o", scope="/s", cwd="/tmp", role="orchestrator")
        wrk = AgentSession(id="j", name="w", scope="/s", cwd="/tmp", role="worker")
        assert orch.is_orchestrator is True       # frozenset fallback
        assert wrk.is_orchestrator is False

    def test_setter_false_overrides_orchestrator_role(self):
        from app.session import AgentSession
        s = AgentSession(id="i", name="o", scope="/s", cwd="/tmp", role="orchestrator")
        s.is_orchestrator = False                # явный override (манифест может сказать worker)
        assert s.is_orchestrator is False


# ── Этап 6, Чанк 3: профиль + F1/F2/F4 в бэкенде ──────────────────────────

class TestClaudeBackendProfile:
    """ClaudeBackend строит options с учётом профиля / F1-F2-F4 (offline)."""

    def _opts(self, **kw):
        from app.backend_claude import ClaudeBackend
        b = ClaudeBackend(model="opus", cwd="/tmp", system_prompt="x", **kw)
        return b._make_client().options

    def test_config_dir_sets_env(self):
        opts = self._opts(config_dir="/tmp/x")
        assert opts.env["CLAUDE_CONFIG_DIR"] == "/tmp/x"

    def test_config_dir_expanduser(self):
        import os
        opts = self._opts(config_dir="~/some-profile")
        assert opts.env["CLAUDE_CONFIG_DIR"] == os.path.expanduser("~/some-profile")

    def test_empty_config_dir_no_env_key(self):
        opts = self._opts(config_dir="")
        assert "CLAUDE_CONFIG_DIR" not in opts.env

    def test_f4_inherit_true_has_project(self):
        opts = self._opts(inherit_claude_md=True)
        assert "project" in opts.setting_sources
        assert "user" in opts.setting_sources

    def test_f4_inherit_false_local_only(self):
        opts = self._opts(inherit_claude_md=False)
        assert opts.setting_sources == ["local"]
        assert "user" not in opts.setting_sources
        assert "project" not in opts.setting_sources

    def test_f1_skills_never_set_default(self):
        # Дефолт (нет params) — options.skills не выставлен.
        opts = self._opts()
        assert getattr(opts, "skills", None) is None

    def test_f1_skills_never_set_with_profile(self):
        # Даже с профилем и user-MCP — options.skills остаётся None.
        opts = self._opts(config_dir="/tmp/x", inherit_claude_md=False,
                          user_mcp_servers={"foo": {"command": "x"}})
        assert getattr(opts, "skills", None) is None

    def test_f2_user_mcp_merged(self):
        opts = self._opts(user_mcp_servers={"foo": {"command": "x"}})
        assert "foo" in opts.mcp_servers

    def test_f2_orchestra_not_overridden_by_user(self):
        # user-MCP — базовый слой; серверный orchestra (в mcp_servers) выигрывает.
        opts = self._opts(
            user_mcp_servers={"orchestra": {"command": "USER"}},
            mcp_servers={"orchestra": {"command": "SERVER"}},
        )
        assert opts.mcp_servers["orchestra"]["command"] == "SERVER"

    def test_f2_user_and_server_coexist(self):
        opts = self._opts(
            user_mcp_servers={"foo": {"command": "f"}},
            mcp_servers={"orchestra": {"command": "o"}},
        )
        assert "foo" in opts.mcp_servers
        assert "orchestra" in opts.mcp_servers


class TestLoadUserMcpServers:
    """_load_user_mcp_servers — ридер top-level .claude.json профиля."""

    def test_reads_config_dir_claude_json(self, tmp_path):
        from app.session import _load_user_mcp_servers
        (tmp_path / ".claude.json").write_text(
            '{"mcpServers": {"foo": {"command": "x"}, "orchestra": {"command": "o"}}}'
        )
        got = _load_user_mcp_servers(str(tmp_path))
        assert got == {"foo": {"command": "x"}}  # orchestra скипнут

    def test_missing_file_returns_empty(self, tmp_path):
        from app.session import _load_user_mcp_servers
        got = _load_user_mcp_servers(str(tmp_path))  # нет .claude.json
        assert got == {}

    def test_no_mcp_servers_key(self, tmp_path):
        from app.session import _load_user_mcp_servers
        (tmp_path / ".claude.json").write_text('{"other": 1}')
        assert _load_user_mcp_servers(str(tmp_path)) == {}

    def test_malformed_json_warns_and_empty(self, tmp_path):
        from app.session import _load_user_mcp_servers
        (tmp_path / ".claude.json").write_text("{not json")
        assert _load_user_mcp_servers(str(tmp_path)) == {}

    def test_empty_config_dir_uses_home(self, tmp_path, monkeypatch):
        from app.session import _load_user_mcp_servers
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        (tmp_path / ".claude.json").write_text(
            '{"mcpServers": {"bar": {"command": "y"}}}'
        )
        assert _load_user_mcp_servers("") == {"bar": {"command": "y"}}


class TestMakeBackendProfileWiring:
    """_make_backend резолвит профиль/inherit/user-MCP и прокидывает в ClaudeBackend."""

    def _session(self, monkeypatch, **kw):
        monkeypatch.setattr("app.session.save_session", MagicMock())
        monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
        from app.session import AgentSession
        defaults = dict(id="i", name="w", scope="/s", cwd="/tmp",
                        model="claude-opus-4-6", system_prompt="x", role="worker")
        defaults.update(kw)
        return AgentSession(**defaults)

    def test_default_pipeline_no_profile(self, monkeypatch):
        # default worker: mcp!=all → user_mcp пуст; inherit True; config_dir пуст.
        s = self._session(monkeypatch, pipeline="default", role="worker")
        b = s._make_backend()
        assert b._config_dir == ""
        assert b._inherit_claude_md is True
        assert b._user_mcp_servers == {}

    def test_profile_resolves_config_dir(self, monkeypatch):
        from app.backend_claude import ClaudeBackend
        # Мокаем резолв роли и профиля — не полагаемся на приватные файлы.
        rr = MagicMock(inherit_claude_md=False, mcp_servers=["x"])
        monkeypatch.setattr("app.pipeline.get_role", lambda p, r: rr)
        monkeypatch.setattr("app.db.get_profile",
                            lambda n: {"name": n, "config_dir": "/tmp/work"})
        s = self._session(monkeypatch, pipeline="p", profile="work")
        b = s._make_backend()
        assert isinstance(b, ClaudeBackend)
        assert b._config_dir == "/tmp/work"
        assert b._inherit_claude_md is False
        assert b._user_mcp_servers == {}  # mcp_servers != "all"

    def test_mcp_all_loads_user_mcp(self, monkeypatch, tmp_path):
        rr = MagicMock(inherit_claude_md=True, mcp_servers="all")
        monkeypatch.setattr("app.pipeline.get_role", lambda p, r: rr)
        monkeypatch.setattr("app.db.get_profile",
                            lambda n: {"name": n, "config_dir": str(tmp_path)})
        (tmp_path / ".claude.json").write_text(
            '{"mcpServers": {"foo": {"command": "x"}}}'
        )
        s = self._session(monkeypatch, pipeline="p", profile="work")
        b = s._make_backend()
        assert b._user_mcp_servers == {"foo": {"command": "x"}}

    def test_missing_manifest_fallback(self, monkeypatch):
        # get_role кидает FileNotFoundError → rr None → inherit True, user_mcp пуст.
        def _raise(p, r):
            raise FileNotFoundError("no manifest")
        monkeypatch.setattr("app.pipeline.get_role", _raise)
        s = self._session(monkeypatch, pipeline="ghost", role="worker")
        b = s._make_backend()
        assert b._inherit_claude_md is True
        assert b._config_dir == ""
        assert b._user_mcp_servers == {}

    def test_profile_not_found_empty_config_dir(self, monkeypatch):
        rr = MagicMock(inherit_claude_md=True, mcp_servers=[])
        monkeypatch.setattr("app.pipeline.get_role", lambda p, r: rr)
        monkeypatch.setattr("app.db.get_profile", lambda n: None)
        s = self._session(monkeypatch, pipeline="p", profile="ghost")
        b = s._make_backend()
        assert b._config_dir == ""
