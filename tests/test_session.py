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


# ── MockBackend для lifecycle тестов ──────────────────────────────────────

class _MockBackend:
    """Контролируемый backend для lifecycle тестов.

    events() ждёт сигнала через _finish_event, затем выдаёт turn_end.
    Это имитирует агента который молчит, потом завершает ход.
    """

    def __init__(self, events_to_yield=None, connect_error=None):
        from app.events import AgentEvent
        self._AgentEvent = AgentEvent
        self.sent: list[str] = []
        self.connected = False
        self.disconnected = False
        self._finish_event = asyncio.Event()
        self._events = events_to_yield or []
        self._connect_error = connect_error
        self.session_id = None

    async def connect(self) -> None:
        if self._connect_error:
            raise self._connect_error
        self.connected = True

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def events(self):
        # Сначала даём все запланированные события
        for event in self._events:
            yield event
        # Потом ждём сигнала финиша
        await self._finish_event.wait()
        yield self._AgentEvent(
            type="turn_end",
            metadata={"ok": True, "stop_reason": "end_turn",
                      "num_turns": 1, "cost_usd": 0.05, "session_id": "mock-sid"},
        )

    async def interrupt(self) -> None:
        self._finish_event.set()

    async def disconnect(self) -> None:
        self.disconnected = True
        self._finish_event.set()  # unblock events() if waiting

    async def reconnect(self) -> None:
        pass

    def finish(self):
        """Сигнализируем завершение хода (вызвать из теста)."""
        self._finish_event.set()


class TestStart:
    @pytest.mark.asyncio
    async def test_no_message_idle(self, session):
        from app.session import AgentStatus
        await session.start()
        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_with_message_sets_running_then_idle(self, session):
        """start("hi") → status=RUNNING, после turn_end → IDLE, cost обновлён."""
        from app.session import AgentStatus
        backend = _MockBackend()

        with patch.object(session, "_make_backend", return_value=backend):
            # Запускаем send в фоне (он стартует event loop)
            send_task = asyncio.create_task(session.start("hi"))
            # Ждём пока статус станет RUNNING
            for _ in range(50):
                await asyncio.sleep(0.01)
                if session.status == AgentStatus.RUNNING:
                    break
            assert session.status == AgentStatus.RUNNING

            # Завершаем ход
            backend.finish()
            await send_task
            # Ждём обработки turn_end event loop'ом
            await asyncio.sleep(0.1)

        assert session.status == AgentStatus.IDLE
        assert session.session_id == "mock-sid"
        assert session.cost_usd == pytest.approx(0.05)


class TestSend:
    @pytest.mark.asyncio
    async def test_send_idle_sets_running(self, session):
        """send() на IDLE сессии → status становится RUNNING."""
        from app.session import AgentStatus
        backend = _MockBackend()

        with patch.object(session, "_make_backend", return_value=backend):
            send_task = asyncio.create_task(session.send("task"))
            for _ in range(50):
                await asyncio.sleep(0.01)
                if session.status == AgentStatus.RUNNING:
                    break
            assert session.status == AgentStatus.RUNNING
            backend.finish()
            await send_task
            await asyncio.sleep(0.1)

        assert backend.sent  # backend.send() был вызван

    @pytest.mark.asyncio
    async def test_send_on_running_queues_message(self, session):
        """send() на RUNNING сессии (non-codex) → inject через backend.send() или в pending."""
        from app.session import AgentStatus
        backend = _MockBackend()

        with patch.object(session, "_make_backend", return_value=backend):
            # Первый send запускает ход
            send_task = asyncio.create_task(session.send("first"))
            for _ in range(50):
                await asyncio.sleep(0.01)
                if session.status == AgentStatus.RUNNING:
                    break
            assert session.status == AgentStatus.RUNNING

            # Второй send пока RUNNING — inject или pending
            await session.send("second")
            # Проверяем что второй send обработан (inject или pending queue)
            second_injected = "second" in backend.sent
            second_queued = "second" in session._pending_messages
            assert second_injected or second_queued, "второй send должен быть либо инжектирован, либо в очереди"

            backend.finish()
            await send_task
            await asyncio.sleep(0.1)


class TestTurn:
    @pytest.mark.asyncio
    async def test_turn_end_returns_to_idle(self, session):
        """После turn_end event статус возвращается в IDLE."""
        from app.session import AgentStatus
        backend = _MockBackend()

        with patch.object(session, "_make_backend", return_value=backend):
            send_task = asyncio.create_task(session.send("task"))
            for _ in range(50):
                await asyncio.sleep(0.01)
                if session.status == AgentStatus.RUNNING:
                    break
            assert session.status == AgentStatus.RUNNING

            backend.finish()
            await send_task
            await asyncio.sleep(0.1)

        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_connect_error_returns_to_idle(self, session):
        """Ошибка connect() → status остаётся/возвращается в IDLE."""
        from app.session import AgentStatus
        backend = _MockBackend(connect_error=ConnectionError("connect failed"))

        with patch.object(session, "_make_backend", return_value=backend):
            with pytest.raises(ConnectionError):
                await session.send("task")

        assert session.status == AgentStatus.IDLE


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sets_idle(self, session):
        """stop() на работающей сессии → status=IDLE, backend disconnect вызван."""
        from app.session import AgentStatus
        backend = _MockBackend()

        with patch.object(session, "_make_backend", return_value=backend):
            send_task = asyncio.create_task(session.send("task"))
            for _ in range(50):
                await asyncio.sleep(0.01)
                if session.status == AgentStatus.RUNNING:
                    break
            assert session.status == AgentStatus.RUNNING

            await session.stop()
            # Отменяем задачу если ещё висит
            if not send_task.done():
                send_task.cancel()
                try:
                    await send_task
                except (asyncio.CancelledError, Exception):
                    pass

        assert session.status == AgentStatus.IDLE


# ── Auto-report gate tests (Task 5) ──

# После мержа v2.16 авто-репорт стал немедленным (_fire_auto_report) вместо
# отложенного (_schedule_auto_report/AUTO_REPORT_IDLE_SEC). Тесты обновлены под
# живой API: проверяем те же гейты (did_report / orchestrator / pending / turn_ok),
# но через немедленный fire. on_idle теперь принимает 4 аргумента (+stop_reason).

def _mk_session(monkeypatch=None, idle_sec=None):
    from app.session import AgentSession
    s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp")
    s._last_turn_ok = True
    return s


@pytest.mark.asyncio
async def test_auto_report_fires_after_idle_timeout(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []
    async def on_idle(name, scope, texts, stop_reason=""):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s._turn_logs = ["did stuff"]
    # завершение хода → немедленный авто-репорт родителю
    s._fire_auto_report()
    await asyncio.sleep(0.05)
    assert fired == ["w"]


@pytest.mark.asyncio
async def test_auto_report_skipped_if_did_report(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []
    async def on_idle(name, scope, texts, stop_reason=""):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = True  # был явный send_message
    s._fire_auto_report()
    await asyncio.sleep(0.05)
    assert fired == []  # явный отчёт был → авто-репорт не нужен


@pytest.mark.asyncio
async def test_auto_report_cancelled_by_new_turn(monkeypatch):
    # Живой гейт "есть незавершённая активность" — pending_messages: если у агента
    # есть отложенные сообщения (пришёл новый ход), авто-репорт не стреляет.
    s = _mk_session(monkeypatch)
    fired = []
    async def on_idle(name, scope, texts, stop_reason=""):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s._pending_messages = ["новый ход пришёл"]
    s._fire_auto_report()
    await asyncio.sleep(0.05)
    assert fired == []  # есть pending → отчёт отложен


@pytest.mark.asyncio
async def test_orchestrator_never_auto_reports(monkeypatch):
    s = _mk_session(monkeypatch)
    s.is_orchestrator = True   # оркестратор отчитывается наверх ТОЛЬКО явным send_message
    fired = []
    async def on_idle(name, scope, texts, stop_reason=""):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s._turn_logs = ["ответил пользователю в чат"]
    s._fire_auto_report()
    await asyncio.sleep(0.05)
    assert fired == []  # оркестратор не auto-report'ит — нет спама наверх


# ── Этап 1: pipeline + is_orchestrator как хранимое поле ──

class TestPipelineField:
    def test_pipeline_default_empty(self):
        from app.session import AgentSession
        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp")
        assert s.pipeline == ""

    def test_pipeline_can_be_set(self):
        from app.session import AgentSession
        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp", pipeline="tasks-pm")
        assert s.pipeline == "tasks-pm"

    def test_to_db_dict_includes_pipeline(self):
        from app.session import AgentSession
        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp", pipeline="tasks-pm")
        assert s._to_db_dict()["pipeline"] == "tasks-pm"


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

    def test_claude_work_profile_end_to_end_env(self, monkeypatch, tmp_path):
        """C3: профиль work с config_dir='~/.claude-work' доходит до env агента.

        Полная цепочка: DB-профиль → _make_backend (config_dir) →
        _make_client → ClaudeAgentOptions.env['CLAUDE_CONFIG_DIR'], раскрытый
        через expanduser. HOME подменяем на tmp_path, чтобы тильда резолвилась
        предсказуемо и тест не зависел от реальной FS машины.
        """
        rr = MagicMock(inherit_claude_md=True, mcp_servers=[])
        monkeypatch.setattr("app.pipeline.get_role", lambda p, r: rr)
        monkeypatch.setattr(
            "app.db.get_profile",
            lambda n: {"name": n, "config_dir": "~/.claude-work"},
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        s = self._session(monkeypatch, pipeline="p", profile="work")
        b = s._make_backend()
        # config_dir хранится нераскрытым (expanduser — только при сборке env)
        assert b._config_dir == "~/.claude-work"
        opts = b._make_client().options
        assert opts.env["CLAUDE_CONFIG_DIR"] == str(tmp_path / ".claude-work")


# ── Task #39: P0 fixes ──

class TestPersistSingleFlight:
    @pytest.mark.asyncio
    async def test_persist_coalesces(self, session, monkeypatch):
        calls = []

        def slow_save(snapshot):
            calls.append(dict(snapshot))

        monkeypatch.setattr("app.session.save_session", slow_save)
        for i in range(5):
            session.progress_pct = i
            session._persist()
        await session._drain_persist()
        # single-flight: at most current + 1 coalesced write
        assert len(calls) <= 2
        # last write reflects the latest state
        assert calls[-1]["progress_pct"] == 4

    @pytest.mark.asyncio
    async def test_persist_last_wins(self, session, monkeypatch):
        from app.session import AgentStatus
        calls = []
        monkeypatch.setattr("app.session.save_session", lambda s: calls.append(dict(s)))
        session.status = AgentStatus.RUNNING
        session._persist()
        session.status = AgentStatus.IDLE
        session._persist()
        await session._drain_persist()
        assert calls[-1]["status"] == "idle"

    @pytest.mark.asyncio
    async def test_persist_survives_db_error(self, session, monkeypatch):
        calls = []

        def flaky_save(snapshot):
            calls.append(dict(snapshot))
            if len(calls) == 1:
                raise RuntimeError("db locked")

        monkeypatch.setattr("app.session.save_session", flaky_save)
        session.progress_pct = 1
        session._persist()
        await session._drain_persist()
        # first persist crashed; trigger a second — loop must still work
        session.progress_pct = 2
        session._persist()
        await session._drain_persist()
        assert len(calls) == 2
        assert calls[-1]["progress_pct"] == 2


class TestCompactGuards:
    @pytest.mark.asyncio
    async def test_compact_reentry_guard(self, session):
        session._compacting = True
        result = await session.compact()
        assert result == {"ok": False, "error": "compact already in progress"}

    @pytest.mark.asyncio
    async def test_compact_ack_bound_to_gen(self, session, monkeypatch):
        from app.events import AgentEvent
        from app.session import AgentStatus
        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        session._compact_ack_event = asyncio.Event()
        session._compact_ack_gen = 5

        # turn_end for a DIFFERENT gen must NOT set the ack event
        session._turn_gen = 4
        session.status = AgentStatus.RUNNING
        session._handle_turn_end(AgentEvent(type="turn_end", content="", metadata={}))
        assert not session._compact_ack_event.is_set()

        # turn_end for the matching gen SETS it
        session._turn_gen = 5
        session._handle_turn_end(AgentEvent(type="turn_end", content="", metadata={}))
        assert session._compact_ack_event.is_set()


class TestFlushPendingDefersDuringCompact:
    @pytest.mark.asyncio
    async def test_flush_defers_when_compacting(self, session):
        sent = []
        backend = AsyncMock()
        backend.send = AsyncMock(side_effect=lambda m: sent.append(m))
        session._backend = backend
        session._compacting = True
        session._pending_messages = ["queued"]
        await session._flush_pending()
        assert sent == []  # deferred — nothing sent during compact
        assert session._pending_messages == ["queued"]  # still queued

    @pytest.mark.asyncio
    async def test_flush_requeues_if_compact_grabs_lock(self, session):
        # Codex diff #P0: flush passed the outer _compacting check, but compact
        # set the flag + took the lock first. Inside-lock recheck must requeue.
        sent = []
        backend = AsyncMock()
        backend.send = AsyncMock(side_effect=lambda m: sent.append(m))
        session._backend = backend
        session._pending_messages = ["m1"]
        # hold the lifecycle lock as "compact" and flip the flag, then run flush:
        # flush must observe _compacting inside the lock and requeue without sending
        await session._lifecycle_lock.acquire()
        session._compacting = True
        try:
            # bypass the outer pre-lock sleep/check by calling the lock body logic:
            # _flush_pending will block on the lock; release after a tick
            task = asyncio.create_task(session._flush_pending())
            await asyncio.sleep(0.4)  # let it pass the 0.3s sleep + hit the lock
        finally:
            session._lifecycle_lock.release()
        await task
        assert sent == []  # not sent — requeued
        assert session._pending_messages == ["m1"]


class TestEnsureBackendForceFresh:
    @pytest.mark.asyncio
    async def test_force_fresh_rebuilds_existing_backend(self, session):
        # Codex diff #P1: _ensure_backend(force_fresh=True) must rebuild even
        # when a backend already exists (old one disconnected, fresh one made).
        old = object()
        session._backend = old
        new = AsyncMock()
        new.connect = AsyncMock()
        with patch.object(session, "_disconnect_backend", AsyncMock()) as disc, \
             patch.object(session, "_make_backend", return_value=new) as mk, \
             patch.object(session, "_claude_event_loop", AsyncMock()), \
             patch.object(session, "_heartbeat_loop", AsyncMock()):
            result = await session._ensure_backend(force_fresh=True)
        disc.assert_awaited_once()
        mk.assert_called_once_with(force_fresh=True)
        assert result is new

    @pytest.mark.asyncio
    async def test_no_force_fresh_reuses_existing(self, session):
        existing = object()
        session._backend = existing
        result = await session._ensure_backend()
        assert result is existing
