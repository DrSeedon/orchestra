"""TDD tests for session.py — AgentSession."""

import asyncio
from datetime import datetime, timedelta, timezone
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
        model="claude-sonnet-5[1m]", system_prompt="test",
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
        # one turn_end per finish(): re-arm so the next events() call suspends on
        # wait() instead of hot-looping turn_ends without a single yield point
        self._finish_event.clear()
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


def test_codex_live_activity_is_brokered_without_db_noise(session, monkeypatch):
    from app.events import AgentEvent
    from app.live_broker import broker

    published = []
    monkeypatch.setattr(broker, "publish", lambda sid, payload: published.append((sid, payload)))
    session._log = MagicMock()

    session._handle_event(AgentEvent(
        "thinking_stream",
        "Checking the renderer",
        {"activity": "reasoning", "item_id": "reason-1"},
    ))
    session._handle_event(AgentEvent(
        "tool_stream",
        "line 1\n",
        {"tool_use_id": "cmd-1"},
    ))
    session._handle_event(AgentEvent(
        "tool_patch",
        '{"changes":[]}',
        {"tool_use_id": "patch-1"},
    ))
    session._handle_event(AgentEvent(
        "turn_diff",
        "@@ -1 +1 @@\n-old\n+new\n",
        {"turn_id": "turn-1"},
    ))

    assert [payload["type"] for _, payload in published] == [
        "thinking_stream",
        "tool_stream",
        "tool_patch",
        "turn_diff",
    ]
    assert published[0][1]["activity"] == "reasoning"
    assert published[1][1]["tool_use_id"] == "cmd-1"
    session._log.assert_not_called()


def test_codex_plan_warning_and_review_are_persisted(session):
    from app.events import AgentEvent

    session._log = MagicMock()
    session._handle_event(AgentEvent("plan", '{"plan":[]}'))
    session._handle_event(AgentEvent("warning", "Transport degraded"))
    session._handle_event(AgentEvent("review", '{"phase":"entered"}'))

    assert session._log.call_args_list == [
        ((("plan", '{"plan":[]}')), {}),
        ((("warning", "Transport degraded")), {}),
        ((("review", '{"phase":"entered"}')), {}),
    ]


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
    async def test_stale_claude_resume_uses_bounded_log_handoff(self, session):
        backend = AsyncMock()
        backend.resume_failed = True
        backend.send = AsyncMock()
        session.session_id = "stale-session"
        session._current_prompt = "refreshed worker context"
        session._ensure_backend = AsyncMock(return_value=backend)
        session._build_runtime_handoff = AsyncMock(return_value=(
            "User:\nold request\n\nAssistant:\nold answer"
        ))

        await session.send("what do you remember?")

        assert session.session_id is None
        sent = backend.send.await_args.args[0]
        assert "<prior-conversation>" in sent
        assert "old answer" in sent
        assert "<current-user-message>\n[Orchestra platform note:" in sent
        assert "what do you remember?" in sent
        session._build_runtime_handoff.assert_awaited_once_with(
            exclude_latest_user="what do you remember?"
        )
        assert session.runtime_handoff == ""
        assert session.session_id_history[-1]["session_id"] == "stale-session"
        assert session._last_context["percentage"] == 0

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

    @pytest.mark.asyncio
    async def test_interrupt_marks_idle_first_and_disconnects_on_missing_ack(self, session):
        from app.session import AgentStatus

        observed = {}

        class InterruptBackend:
            disconnected = False

            async def interrupt(self):
                observed["status"] = session.status
                observed["lock"] = session._lifecycle_lock.locked()
                return False

            async def disconnect(self):
                self.disconnected = True

        backend = InterruptBackend()
        session._backend = backend
        session.status = AgentStatus.RUNNING
        session._turn_start = 123.0

        await session.interrupt()
        await session._drain_persist()

        assert observed == {"status": AgentStatus.IDLE, "lock": True}
        assert backend.disconnected is True
        assert session._backend is None
        assert session._turn_start == 0

    @pytest.mark.asyncio
    async def test_message_waits_for_interrupt_before_starting_clean_turn(self, session):
        from app.session import AgentStatus

        interrupt_started = asyncio.Event()
        release_interrupt = asyncio.Event()

        class InterruptBackend:
            def __init__(self):
                self.sent = []

            async def interrupt(self):
                interrupt_started.set()
                await release_interrupt.wait()
                return True

            async def send(self, message):
                self.sent.append(message)

        backend = InterruptBackend()
        session._backend = backend
        session.status = AgentStatus.RUNNING

        interrupt_task = asyncio.create_task(session.interrupt())
        await interrupt_started.wait()
        send_task = asyncio.create_task(session.send("new direction"))
        await asyncio.sleep(0)

        assert backend.sent == []
        assert not send_task.done()

        release_interrupt.set()
        await interrupt_task
        await send_task

        assert backend.sent == ["new direction"]
        assert session.status == AgentStatus.RUNNING
        assert session._manually_interrupted is False

    @pytest.mark.asyncio
    async def test_manual_interrupt_suppresses_stale_auto_report(self, session):
        from app.session import AgentStatus

        backend = AsyncMock()
        backend.interrupt = AsyncMock(return_value=True)
        session._backend = backend
        session.status = AgentStatus.RUNNING
        session.last_task_sender = "parent"
        session.on_idle = AsyncMock()

        await session.interrupt()
        session._turns.fire_auto_report()
        await asyncio.sleep(0)

        session.on_idle.assert_not_awaited()


class TestClaudeTurnLifecycle:
    @pytest.mark.asyncio
    async def test_long_active_turn_keeps_event_and_does_not_inject_timeout(self, session, monkeypatch):
        from app.events import AgentEvent
        from app.session import AgentStatus

        class DelayedBackend:
            def __init__(self):
                self.sent = []

            async def events(self):
                await asyncio.sleep(0.06)
                yield AgentEvent("status", "late but valid event")
                yield AgentEvent("turn_end", metadata={
                    "ok": True,
                    "stop_reason": "end_turn",
                    "num_turns": 1,
                    "session_id": "claude-session-1",
                })

            async def send(self, message):
                self.sent.append(message)

        backend = DelayedBackend()
        logs = []
        session._log = lambda log_type, content: logs.append((log_type, content))
        session._backend = backend
        session.status = AgentStatus.RUNNING
        session._turn_start = asyncio.get_running_loop().time()
        monkeypatch.setattr(session, "TURN_TIMEOUT", 0.02, raising=False)
        monkeypatch.setattr("app.bg_jobs.bg_manager", None)

        await asyncio.wait_for(session._persistent_event_loop(), timeout=0.5)
        await session._drain_persist()

        assert backend.sent == []
        assert ("status", "late but valid event") in logs
        assert session.status == AgentStatus.IDLE


# ── Auto-report gate tests (Task 5) ──

# После мержа v2.16 авто-репорт стал немедленным (_fire_auto_report) вместо
# отложенного (_schedule_auto_report/AUTO_REPORT_IDLE_SEC). Тесты обновлены под
# живой API: проверяем те же гейты (did_report / orchestrator / pending / turn_ok),
# но через немедленный fire. on_idle принимает stop_reason и turn_ok.

def _mk_session(monkeypatch=None, idle_sec=None):
    from app.session import AgentSession
    s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp")
    s._last_turn_ok = True
    return s


@pytest.mark.asyncio
async def test_auto_report_fires_after_idle_timeout(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []
    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s.last_task_sender = "parent"
    s._turn_logs = ["did stuff"]
    # завершение хода → немедленный авто-репорт родителю
    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)
    assert fired == ["w"]


@pytest.mark.asyncio
async def test_auto_report_fires_for_parented_worker_without_sender_metadata(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []

    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append(name)

    s.on_idle = on_idle
    s.parent_name = "parent-orchestrator"
    s.last_task_sender = ""
    s._turn_logs = ["finished"]

    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)

    assert fired == ["w"]


@pytest.mark.asyncio
async def test_auto_report_skips_unparented_direct_worker(monkeypatch):
    s = _mk_session(monkeypatch)
    s.on_idle = AsyncMock()
    s.parent_name = ""
    s.last_task_sender = ""

    s._turns.fire_auto_report()
    await asyncio.sleep(0)

    s.on_idle.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_report_skipped_if_did_report(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []
    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = True  # был явный send_message
    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)
    assert fired == []  # явный отчёт был → авто-репорт не нужен


@pytest.mark.asyncio
async def test_auto_report_skips_successful_silent_turn(monkeypatch):
    s = _mk_session(monkeypatch)
    s.on_idle = AsyncMock()
    s.last_task_sender = "parent"
    s._turn_logs = []

    s._turns.fire_auto_report()
    await asyncio.sleep(0)

    s.on_idle.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_report_cancelled_by_new_turn(monkeypatch):
    # Живой гейт "есть незавершённая активность" — pending_messages: если у агента
    # есть отложенные сообщения (пришёл новый ход), авто-репорт не стреляет.
    s = _mk_session(monkeypatch)
    fired = []
    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s._pending_messages = ["новый ход пришёл"]
    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)
    assert fired == []  # есть pending → отчёт отложен


@pytest.mark.asyncio
async def test_orchestrator_never_auto_reports(monkeypatch):
    s = _mk_session(monkeypatch)
    s.is_orchestrator = True   # оркестратор отчитывается наверх ТОЛЬКО явным send_message
    fired = []
    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append(name)
    s.on_idle = on_idle
    s._did_report = False
    s._turn_logs = ["ответил пользователю в чат"]
    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)
    assert fired == []  # оркестратор не auto-report'ит — нет спама наверх


@pytest.mark.asyncio
async def test_auto_report_passes_failed_turn_state(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []

    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append((stop_reason, turn_ok))

    s.on_idle = on_idle
    s.last_task_sender = "parent"
    s._last_stop_reason = "stop_sequence"
    s._last_turn_ok = False
    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)

    assert fired == [("stop_sequence", False)]


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
                        model="claude-opus-4-8[1m]", system_prompt="x", role="worker")
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
    async def test_compact_on_running_fails(self, session):
        """compact() на RUNNING сессии → ошибка (нельзя компактировать активный ход)."""
        from app.session import AgentStatus
        session.status = AgentStatus.RUNNING
        result = await session.compact()
        assert result["ok"] is False
        assert "running" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_compact_blocked_while_claude_subscription_is_exhausted(
        self, session, monkeypatch
    ):
        session._log = MagicMock()
        session._make_backend = MagicMock()
        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active",
            lambda: True,
        )

        result = await session.compact()

        assert result["ok"] is False
        assert "subscription limit active" in result["error"].lower()
        assert session._compacting is False
        session._make_backend.assert_not_called()
        session._log.assert_called_once_with("error", result["error"])

    @pytest.mark.asyncio
    async def test_compact_rejects_limit_message_and_preserves_session(
        self, session, monkeypatch
    ):
        from app.events import AgentEvent

        class LimitBackend:
            async def connect(self):
                return None

            async def send(self, _message):
                return None

            async def events(self):
                yield AgentEvent(
                    type="text",
                    content=(
                        "You've hit your monthly spend limit · raise it at "
                        "claude.ai/settings/usage"
                    ),
                )
                yield AgentEvent(
                    type="turn_end",
                    metadata={"session_id": "bad-compact-session"},
                )

            async def disconnect(self):
                return None

        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active",
            lambda: False,
        )
        session.session_id = "original-session"
        session.last_summary = "previous valid summary"
        session.session_id_history = []
        session._log = MagicMock()
        session._make_backend = MagicMock(return_value=LimitBackend())
        session._ensure_backend = AsyncMock()

        result = await session.compact()

        assert result["ok"] is False
        assert result["error"] == "Claude subscription limit active; compact aborted"
        assert session.session_id == "original-session"
        assert session.last_summary == "previous valid summary"
        assert session.session_id_history == []
        assert session._compacting is False
        session._ensure_backend.assert_not_awaited()
        assert not any(
            call.args[0] == "text" and "Compact summary" in call.args[1]
            for call in session._log.call_args_list
        )

    @pytest.mark.asyncio
    async def test_compact_ack_limit_rolls_back_summary_and_session(
        self, session, monkeypatch
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus

        summary = (
            "INTENT: Preserve the current task across compaction.\n"
            "DECISIONS: Keep the existing implementation and tests.\n"
            "FILES: app/session.py contains compaction state.\n"
            "PENDING: Continue after the fresh session acknowledges this handoff.\n"
            "RECENT: The user requested a safe compact operation."
        )

        class CompactBackend:
            async def connect(self):
                return None

            async def send(self, _message):
                return None

            async def events(self):
                yield AgentEvent(type="text", content=summary)
                yield AgentEvent(
                    type="turn_end",
                    metadata={"session_id": "compact-session"},
                )

            async def disconnect(self):
                return None

        backend = CompactBackend()
        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active",
            lambda: False,
        )
        session.session_id = "original-session"
        session.last_summary = "previous valid summary"
        session.session_id_history = []
        session.status = AgentStatus.IDLE
        session._log = MagicMock()
        session._make_backend = MagicMock(return_value=backend)

        async def fail_ack(force_fresh=False):
            session._backend = backend

            async def finish():
                await asyncio.sleep(0)
                session._session_limit_hit = True
                session._compact_ack_event.set()

            asyncio.create_task(finish())
            return backend

        session._ensure_backend = AsyncMock(side_effect=fail_ack)

        result = await session.compact()

        assert result["ok"] is False
        assert "during compact acknowledgement" in result["error"]
        assert session.session_id == "original-session"
        assert session.last_summary == "previous valid summary"
        assert session.session_id_history == []
        assert session.status == AgentStatus.IDLE
        assert session._compacting is False

    @pytest.mark.asyncio
    async def test_compact_logs_preamble_as_user_message(self, session, monkeypatch):
        """После compact, preamble с summary содержит summary и логируется как user_message."""
        from app.events import AgentEvent
        from app.session import AgentStatus
        monkeypatch.setattr("app.bg_jobs.bg_manager", None)

        logged = []

        def fake_log(log_type, content):
            logged.append((log_type, content))

        session._log = fake_log

        # Мокаем весь compact чтобы проверить только логирование preamble
        # Патчим внутренности compact после получения summary
        original_compact = session.compact

        summary_text = "INTENT: Working on feature X.\nDECISIONS: Chose approach A over B.\nFILES: app/main.py — refactored handler.\nPENDING: Need to update tests.\nRECENT: User asked for refactor, implemented it.\nIMPORTANT: Use proxy for all requests. " + "x" * 50

        # Симулируем compact через патч backend + ack
        class CompactBackend:
            session_id = None
            sent = []
            async def connect(self): pass
            async def send(self, msg): self.sent.append(msg)
            async def events(self):
                yield AgentEvent(type="text", content=summary_text)
                yield AgentEvent(type="turn_end", metadata={"ok": True, "stop_reason": "end_turn",
                                                             "num_turns": 1, "session_id": "cid"})
            async def interrupt(self): pass
            async def disconnect(self): pass
            async def reconnect(self): pass

        backend = CompactBackend()
        # Мокаем _ensure_backend чтобы не стартовать heartbeat/listen задачи
        ack_set = False
        async def fake_ensure_backend(force_fresh=False):
            nonlocal ack_set
            session._backend = backend
            if not ack_set and session._compact_ack_event:
                # Ставим ack немедленно чтобы compact не ждал 60s
                async def _set_ack():
                    await asyncio.sleep(0.05)
                    if session._compact_ack_event:
                        session._compact_ack_event.set()
                asyncio.create_task(_set_ack())
                ack_set = True
            return backend

        with patch.object(session, "_make_backend", return_value=backend), \
             patch.object(session, "_ensure_backend", side_effect=fake_ensure_backend):
            result = await session.compact()

        assert result["ok"] is True
        # preamble должен быть отправлен через backend.send с summary внутри
        preamble_msgs = [m for m in backend.sent if "Acknowledge briefly." in m]
        assert preamble_msgs, "preamble с 'Acknowledge briefly.' должен быть отправлен"
        assert summary_text in preamble_msgs[0], "summary должен быть в preamble"
        # user_message должен быть залогирован
        user_msgs = [(t, c) for t, c in logged if t == "user_message"]
        assert any(summary_text in c for _, c in user_msgs), "preamble должен быть залогирован как user_message"

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
        session._turns.handle_turn_end(AgentEvent(type="turn_end", content="", metadata={}))
        assert not session._compact_ack_event.is_set()

        # turn_end for the matching gen SETS it
        session._turn_gen = 5
        session._turns.handle_turn_end(AgentEvent(type="turn_end", content="", metadata={}))
        assert session._compact_ack_event.is_set()


class TestPrecompactTimer:
    def test_codex_post_turn_schedules_native_precompact_without_generic_handoff(self, session):
        spawned = []
        logs = []

        def capture(coro):
            spawned.append(coro.cr_code.co_name)
            coro.close()

        session.backend_type = "codex"
        session._is_orchestrator = False
        session._schedule_precompact_timer = MagicMock()
        session._spawn_bg = capture
        session._log = lambda log_type, content: logs.append((log_type, content))
        session._turns.fire_auto_report = MagicMock()
        session._hibernate.schedule = MagicMock()
        session._pending_messages = []

        session._turns.after_turn_idle_actions(95)

        session._schedule_precompact_timer.assert_called_once_with(95)
        assert "_auto_compact" not in spawned
        assert not any("auto-compact triggered" in content for _, content in logs)

    def test_claude_post_turn_keeps_orchestra_compaction(self, session):
        spawned = []

        def capture(coro):
            spawned.append(coro.cr_code.co_name)
            coro.close()

        session.backend_type = "claude"
        session._is_orchestrator = False
        session._schedule_precompact_timer = MagicMock()
        session._spawn_bg = capture
        session._log = MagicMock()
        session._turns.fire_auto_report = MagicMock()
        session._hibernate.schedule = MagicMock()
        session._pending_messages = []

        session._turns.after_turn_idle_actions(95)

        session._schedule_precompact_timer.assert_called_once_with(95)
        assert "_auto_compact" in spawned
        assert any(
            "auto-compact triggered" in call.args[1]
            for call in session._log.call_args_list
        )

    def test_codex_precompact_policy_uses_25m_and_60pct_threshold(self, session):
        launched = []
        session.backend_type = "codex"
        session._log = lambda *_: None

        def capture(coro):
            launched.append(coro)
            coro.close()
            return MagicMock(done=lambda: False)

        session._spawn_bg = capture

        session._schedule_precompact_timer(59)
        assert session._precompact_timer is None

        session._schedule_precompact_timer(60)

        assert len(launched) == 1
        assert session._precompact_timer["delay_seconds"] == 25 * 60
        assert session._precompact_timer["cache_window_seconds"] == 30 * 60
        assert session._precompact_timer["context_threshold"] == 60
        assert session._precompact_timer["compact_mode"] == "native"

    @pytest.mark.asyncio
    async def test_codex_precompact_timer_calls_native_session_compact(self, session, monkeypatch):
        from app.session import AgentStatus

        session.backend_type = "codex"
        session.status = AgentStatus.IDLE
        session._last_context["percentage"] = 70
        session._log = MagicMock()
        session.compact = AsyncMock(return_value={
            "ok": True,
            "mode": "native",
            "before_pct": 70,
            "after_pct": 12,
        })
        monkeypatch.setattr(
            "app.bg_jobs.bg_manager",
            MagicMock(has_active_jobs=lambda *_: False),
        )
        session.CODEX_PRECOMPACT_DELAY_SECONDS = 0

        session._schedule_precompact_timer(70)
        await asyncio.sleep(0.05)

        session.compact.assert_awaited_once_with()
        assert session._precompact_timer["compact_result"]["mode"] == "native"

    @pytest.mark.asyncio
    async def test_codex_manual_compact_uses_native_backend_and_preserves_session(
        self, session
    ):
        from app.session import AgentStatus

        backend = MagicMock()
        backend.compact_context = AsyncMock(return_value={
            "ok": True,
            "thread_id": "thread-1",
            "context_tokens": 31_000,
            "max_tokens": 258_400,
        })
        session.backend_type = "codex"
        session.session_id = "thread-1"
        session.status = AgentStatus.IDLE
        session._last_context = {
            "percentage": 88,
            "total_tokens": 227_000,
            "max_tokens": 258_400,
        }
        session._ensure_backend = AsyncMock(return_value=backend)
        session._hibernate.schedule = MagicMock()
        session._log = MagicMock()
        session._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "backend": "codex",
        }

        result = await session.compact()

        backend.compact_context.assert_awaited_once_with()
        assert session.session_id == "thread-1"
        assert result["ok"] is True
        assert result["mode"] == "native"
        assert result["before_pct"] == 88
        assert result["after_pct"] == 12
        assert session._last_context["total_tokens"] == 31_000
        assert session._precompact_timer is None
        session._hibernate.schedule.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_codex_native_compact_queues_message_until_completion(self, session):
        from app.session import AgentStatus

        compact_started = asyncio.Event()
        finish_compact = asyncio.Event()

        async def compact_context():
            compact_started.set()
            await finish_compact.wait()
            return {
                "ok": True,
                "thread_id": "thread-1",
                "context_tokens": 30_000,
                "max_tokens": 258_400,
            }

        backend = MagicMock()
        backend.compact_context = AsyncMock(side_effect=compact_context)
        session.backend_type = "codex"
        session.session_id = "thread-1"
        session.status = AgentStatus.IDLE
        session._ensure_backend = AsyncMock(return_value=backend)
        session._log = MagicMock()
        session._hibernate.schedule = MagicMock()
        spawned = []

        def capture(coro):
            spawned.append(coro.cr_code.co_name)
            coro.close()
            return MagicMock()

        session._spawn_bg = capture

        task = asyncio.create_task(session.compact())
        await asyncio.wait_for(compact_started.wait(), timeout=1)
        await session.send("follow-up while compacting")

        assert session._pending_messages == ["follow-up while compacting"]
        finish_compact.set()
        result = await asyncio.wait_for(task, timeout=1)

        assert result["ok"] is True
        assert "_flush_pending" in spawned
        session._hibernate.schedule.assert_not_called()

    @pytest.mark.asyncio
    async def test_precompact_timer_fires_and_logs_outcome_when_ready(self, session, monkeypatch):
        from app.session import AgentStatus
        from unittest.mock import MagicMock

        logs = []
        session._log = lambda log_type, content: logs.append((log_type, content))
        session.status = AgentStatus.IDLE
        session._last_context["percentage"] = 55

        compact_called = asyncio.Event()

        async def compact_ok() -> dict:
            compact_called.set()
            return {"ok": True}

        session.compact = compact_ok
        monkeypatch.setattr("app.bg_jobs.bg_manager", MagicMock(has_active_jobs=lambda *_: False))
        session.PRECOMPACT_DELAY_SECONDS = 0

        session._schedule_precompact_timer(55)
        await asyncio.wait_for(compact_called.wait(), timeout=1)
        await asyncio.sleep(0)

        assert session._precompact_timer is not None
        assert session._precompact_timer.get("fired_at") is not None
        session._precompact_timer["scheduled_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=1, minutes=5)
        ).isoformat()
        session._note_next_precompact_activity()

        outcome = [c for t, c in logs if t == "status" and "precompact timer outcome" in c]
        assert outcome, "next activity must be logged with crossed cache window"
        assert '"crossed_cache_window": true' in outcome[0].lower()
        assert '"crossed_60m": true' in outcome[0].lower()

    @pytest.mark.asyncio
    async def test_precompact_timer_suppressed_when_not_idle(self, session, monkeypatch):
        from app.session import AgentStatus
        from unittest.mock import MagicMock

        logs = []
        session._log = lambda log_type, content: logs.append((log_type, content))
        session.backend_type = "claude"
        session.status = AgentStatus.WAITING
        session._last_context["percentage"] = 55

        session.compact = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr("app.bg_jobs.bg_manager", MagicMock(has_active_jobs=lambda *_: False))
        session.PRECOMPACT_DELAY_SECONDS = 0

        session._schedule_precompact_timer(55)
        await asyncio.sleep(0.05)

        assert session.compact.await_count == 0
        assert session._precompact_timer is None
        assert any("precompact timer skipped" in c for _, c in logs)

    def test_precompact_timer_arm_once_per_episode(self, session):
        launched = []
        session._log = lambda *_: None

        def capture(coro):
            launched.append(coro)
            try:
                coro.close()
            except Exception:
                pass
            return AsyncMock()

        session._spawn_bg = capture
        session._precompact_timer = None

        session._schedule_precompact_timer(55)
        session._schedule_precompact_timer(55)

        assert len(launched) == 1

    def test_precompact_timer_activity_cancels_pending_before_fire(self, session):
        session._log = lambda *_: None
        session._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "role": session.role,
            "backend": session.backend_type,
            "context_pct": 55,
        }
        session._precompact_timer_task = None

        session._note_next_precompact_activity()

        assert session._precompact_timer is None

    @pytest.mark.asyncio
    async def test_precompact_timer_skipped_when_bg_job_active(self, session, monkeypatch):
        from app.session import AgentStatus
        from unittest.mock import MagicMock

        logs = []
        session._log = lambda log_type, content: logs.append((log_type, content))
        session.status = AgentStatus.IDLE
        session._last_context["percentage"] = 55
        session.compact = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr("app.bg_jobs.bg_manager", MagicMock(has_active_jobs=lambda *_: True))
        session.PRECOMPACT_DELAY_SECONDS = 0

        session._schedule_precompact_timer(55)
        await asyncio.sleep(0.05)

        assert session.compact.await_count == 0
        assert session._precompact_timer is None
        assert any("precompact timer skipped" in c for _, c in logs)
class TestRateLimitClassification:
    @staticmethod
    def _capture_coroutines(session):
        spawned = []
        session._log = lambda *_args, **_kwargs: None

        def capture(coro):
            spawned.append(coro)
            coro.close()

        session._spawn_bg = capture
        return spawned

    def test_monthly_spend_limit_is_terminal_and_never_retried(self, session):
        from app.events import AgentEvent
        spawned = self._capture_coroutines(session)

        session._handle_event(AgentEvent(
            type="text",
            content="You've hit your monthly spend limit · raise it at claude.ai/settings/usage",
        ))
        session._handle_event(AgentEvent(type="error", content="rate_limit"))

        assert session._rate_limit_retries == 0
        assert spawned == []

    @pytest.mark.asyncio
    async def test_terminal_limit_turn_skips_duplicate_error_and_precompact(
        self, session, monkeypatch
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus

        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        logs = []
        session._log = lambda log_type, content: logs.append((log_type, content))
        session._spawn_bg = lambda coro: coro.close()
        session._schedule_precompact_timer = MagicMock()
        session._hibernate.schedule = MagicMock()
        session.status = AgentStatus.RUNNING

        session._handle_event(AgentEvent(
            type="text",
            content="You've hit your monthly spend limit · raise it at claude.ai/settings/usage",
        ))
        session._handle_event(AgentEvent(type="error", content="rate_limit"))
        session._handle_event(AgentEvent(
            type="turn_end",
            metadata={
                "ok": False,
                "stop_reason": "stop_sequence",
                "num_turns": 1,
                "model_error": "rate_limit",
                "errors": ["rate_limit"],
            },
        ))

        assert not any("turn FAILED: rate_limit" in content for _, content in logs)
        assert sum(
            "subscription limit" in content for _, content in logs
        ) == 1
        session._schedule_precompact_timer.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_turn_does_not_reset_transient_retry_budget(self, session, monkeypatch):
        from app.events import AgentEvent
        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        self._capture_coroutines(session)
        session._rate_limit_retries = 2

        session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
            "ok": False, "stop_reason": "error", "num_turns": 0,
        }))
        await session._drain_persist()

        assert session._rate_limit_retries == 2

    @pytest.mark.asyncio
    async def test_new_user_message_resets_retry_budget(self, session):
        from app.session import AgentStatus
        session.model = "gpt-5.6-sol"
        session.backend_type = "codex"
        session.status = AgentStatus.RUNNING
        session._rate_limit_retries = 2
        session._server_error_retries = 2
        session._log = lambda *_args, **_kwargs: None
        backend = AsyncMock()
        backend.send = AsyncMock()
        session._backend = backend

        await session.send("new user request")

        assert session._rate_limit_retries == 0
        assert session._server_error_retries == 0
        backend.send.assert_awaited_once_with("new user request")

    @pytest.mark.asyncio
    async def test_server_error_retries_fresh_without_false_auto_report(
            self, session, monkeypatch):
        from app.events import AgentEvent
        from app.session import AgentStatus

        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        session.status = AgentStatus.RUNNING
        session.last_task_sender = "parent"
        session._turn_gen = 7
        session._hibernate.schedule = MagicMock()
        session._turns.fire_auto_report = MagicMock()

        async def noop():
            return None

        spawned = []

        def capture(coro):
            spawned.append(coro.cr_code.co_name)
            coro.close()

        session._spawn_bg = capture
        session._retry_after_server_error = MagicMock(
            side_effect=lambda *_args: noop())

        session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
            "ok": False,
            "stop_reason": "stop_sequence",
            "num_turns": 1,
            "model_error": "server_error",
            "errors": ["server_error"],
        }))
        await session._drain_persist()

        assert session.status == AgentStatus.IDLE
        assert session._server_error_retries == 1
        assert session._rate_limit_retries == 0
        session._retry_after_server_error.assert_called_once_with(5, 7)
        assert "noop" in spawned
        session._turns.fire_auto_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_server_error_retry_reconnects_only_if_turn_is_still_current(
            self, session):
        from app.session import AgentStatus

        session.status = AgentStatus.IDLE
        session._turn_gen = 4
        session._disconnect_backend = AsyncMock()
        session.send = AsyncMock()

        await session._retry_after_server_error(0, 4)

        session._disconnect_backend.assert_awaited_once()
        retry_message = session.send.await_args.args[0]
        assert retry_message.startswith("[system] Retrying after transient server error.")

        session._disconnect_backend.reset_mock()
        session.send.reset_mock()
        session._turn_gen = 5

        await session._retry_after_server_error(0, 4)

        session._disconnect_backend.assert_not_awaited()
        session.send.assert_not_awaited()


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
             patch.object(session, "_persistent_event_loop", AsyncMock()), \
             patch.object(session._hibernate, "heartbeat_loop", AsyncMock()):
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


class TestCodexTurnLifecycle:
    @pytest.mark.asyncio
    async def test_active_turn_is_not_killed_by_total_wall_clock_timeout(self, session, monkeypatch):
        from app.events import AgentEvent
        from app.session import AgentStatus

        class DelayedBackend:
            def __init__(self):
                self.disconnected = False

            async def events(self):
                yield AgentEvent("status", "thread started", {"session_id": "codex-thread-1"})
                for _ in range(3):
                    await asyncio.sleep(0.03)
                    yield AgentEvent("status", "still active")

            async def disconnect(self):
                self.disconnected = True

        backend = DelayedBackend()
        session.backend_type = "codex"
        session.status = AgentStatus.RUNNING
        session._backend = backend
        # The old implementation wrapped the whole turn in this timeout. A stream that
        # stays active for longer than the threshold was still killed at the deadline.
        monkeypatch.setattr(session, "CODEX_TURN_TIMEOUT", 0.05, raising=False)

        await asyncio.wait_for(session._turn_event_loop(), timeout=0.5)
        await session._drain_persist()

        assert backend.disconnected is False
        assert session.session_id == "codex-thread-1"
        assert session.status == AgentStatus.IDLE


class TestRuntimeCapabilities:
    @pytest.mark.asyncio
    async def test_per_turn_runtime_queues_mid_turn_message(self, session):
        from app.session import AgentStatus

        backend = AsyncMock()
        backend.send = AsyncMock()
        session.backend_type = "opencode"
        session.status = AgentStatus.RUNNING
        session._backend = backend
        session._log = lambda *_args, **_kwargs: None

        await session.send("queue me")

        backend.send.assert_not_awaited()
        assert session._pending_messages == ["queue me"]

    @pytest.mark.asyncio
    async def test_codex_runtime_steers_mid_turn_message(self, session):
        from app.session import AgentStatus

        backend = AsyncMock()
        backend.send = AsyncMock()
        session.backend_type = "codex"
        session.status = AgentStatus.RUNNING
        session._backend = backend
        session._log = lambda *_args, **_kwargs: None

        await session.send("steer now")

        backend.send.assert_awaited_once_with("steer now")
        assert session._pending_messages == []

    @pytest.mark.asyncio
    async def test_cross_runtime_model_switch_resets_native_session_and_builds_handoff(
            self, session, monkeypatch):
        from app.session import AgentStatus

        session.model = "claude-sonnet-5[1m]"
        session.backend_type = "claude"
        session.session_id = "claude-native-session"
        session.session_id_history = [{"session_id": "legacy-claude-session"}]
        session.status = AgentStatus.IDLE
        session._backend = AsyncMock()
        session._backend.disconnect = AsyncMock()
        session._log = lambda *_args, **_kwargs: None
        monkeypatch.setattr("app.session.get_logs", lambda *_args, **_kwargs: [
            {"type": "user_message", "content": "Fix the parser"},
            {"type": "text", "content": "Parser fixed and tests pass"},
        ])

        result = await session.change_model("gpt-5.6-sol")

        assert result["ok"] is True
        assert result["runtime_changed"] is True
        assert session.backend_type == "codex"
        assert session.session_id is None
        assert "Fix the parser" in session.runtime_handoff
        assert "Parser fixed" in session.runtime_handoff
        assert session.session_id_history[0]["runtime"] == "claude"
        assert session.session_id_history[0]["model"] == "claude-sonnet-5[1m]"

    @pytest.mark.asyncio
    async def test_codex_model_switch_starts_fresh_native_thread(
            self, session, monkeypatch):
        from app.session import AgentStatus

        session.model = "gpt-5.5"
        session.backend_type = "codex"
        session.session_id = "codex-native-session"
        session.status = AgentStatus.IDLE
        session._backend = AsyncMock()
        session._backend.disconnect = AsyncMock()
        session._log = lambda *_args, **_kwargs: None
        monkeypatch.setattr(
            session,
            "_build_runtime_handoff",
            AsyncMock(return_value="provider-neutral handoff"),
        )

        result = await session.change_model("gpt-5.6-sol")

        assert result["runtime_changed"] is False
        assert result["native_session_reset"] is True
        assert session.session_id is None
        assert session.runtime_handoff == "provider-neutral handoff"
        assert session.session_id_history[-1]["session_id"] == "codex-native-session"

    @pytest.mark.asyncio
    async def test_runtime_handoff_is_one_shot_user_message_context(self, session):
        from app.session import AgentStatus

        backend = _MockBackend()
        session.backend_type = "codex"
        session.model = "gpt-5.6-sol"
        session.runtime_handoff = "User:\nold request\n\nAssistant:\nold answer"

        with patch.object(session, "_make_backend", return_value=backend):
            await session.send("first after switch")
            assert "<prior-conversation>" in backend.sent[0]
            assert "old answer" in backend.sent[0]
            assert "<current-user-message>\nfirst after switch" in backend.sent[0]
            assert session.runtime_handoff == ""

            backend.finish()
            for _ in range(50):
                await asyncio.sleep(0.01)
                if session.status == AgentStatus.IDLE:
                    break

            await session.send("second after switch")
            assert backend.sent[1] == "second after switch"
            backend.finish()
            for _ in range(50):
                await asyncio.sleep(0.01)
                if session.status == AgentStatus.IDLE:
                    break
