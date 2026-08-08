"""TDD tests for session.py — AgentSession."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)


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


def _quota_decision(state="available", model="claude-sonnet-5[1m]", *, valid_for=60):
    import time
    from app.quota_gate import QuotaDecision

    provider = "anthropic" if model.startswith("claude-") else "codex"
    return QuotaDecision(
        state=state,
        model=model,
        provider=provider,
        provider_label="Claude" if provider == "anthropic" else "Codex",
        weekly_utilization=97 if state == "blocked" else 1,
        observed_at=time.time(),
        valid_until=time.time() + valid_for,
        reset_at=None,
        alternatives=(),
        reason="test decision",
    )


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

    @pytest.mark.asyncio
    async def test_unpublished_start_does_not_schedule_persistence(self, session):
        session._persist = MagicMock()

        await session.start(persist=False)

        session._persist.assert_not_called()
        assert session._persist_task is None

    @pytest.mark.asyncio
    async def test_abort_unpublished_closes_runtime_without_db_side_effects(
        self, session,
    ):
        blocker = asyncio.Event()
        background = asyncio.create_task(blocker.wait())
        persist = asyncio.create_task(blocker.wait())
        session._background_tasks.add(background)
        session._persist_task = persist
        session._persist_dirty = True
        session._disconnect_backend = AsyncMock()
        session._persist = MagicMock()
        session._log = MagicMock()

        await session.abort_unpublished()

        assert background.cancelled()
        assert persist.cancelled()
        assert session._background_tasks == set()
        assert session._persist_task is None
        assert session._persist_dirty is False
        session._disconnect_backend.assert_awaited_once()
        session._persist.assert_not_called()
        session._log.assert_not_called()


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


@pytest.mark.asyncio
async def test_explicit_tool_failure_is_correlated_before_persistence(
    session, monkeypatch
):
    from app.events import AgentEvent

    add_error = MagicMock(return_value=True)
    monkeypatch.setattr("app.session.tool_error_add", add_error)
    session._log = MagicMock()

    session._handle_event(AgentEvent(
        "tool_use",
        "Read: {}",
        {"tool_use_id": "tool-1", "tool_name": "Read"},
    ))
    session._handle_event(AgentEvent(
        "tool_result",
        "file not found",
        {"tool_use_id": "tool-1", "is_error": True},
    ))
    if session._log_futures:
        await asyncio.gather(*tuple(session._log_futures), return_exceptions=True)

    add_error.assert_called_once_with(
        "w1",
        "/test",
        "Read",
        "file not found",
        runtime="claude",
        tool_use_id="tool-1",
    )

    add_error.reset_mock()
    session._handle_event(AgentEvent(
        "tool_use",
        "Read: {}",
        {"tool_use_id": "tool-2", "tool_name": "Read"},
    ))
    session._handle_event(AgentEvent(
        "tool_result",
        "ok",
        {"tool_use_id": "tool-2", "is_error": False},
    ))
    add_error.assert_not_called()


@pytest.mark.asyncio
async def test_tool_telemetry_failure_does_not_break_event_handling(
    session, monkeypatch, caplog
):
    from app.events import AgentEvent

    monkeypatch.setattr(
        "app.session.tool_error_add",
        MagicMock(side_effect=RuntimeError("database locked")),
    )
    session._log = MagicMock()
    session._handle_event(AgentEvent(
        "tool_use",
        "Read: {}",
        {"tool_use_id": "tool-1", "tool_name": "Read"},
    ))

    session._handle_event(AgentEvent(
        "tool_result",
        "file not found",
        {"tool_use_id": "tool-1", "is_error": True},
    ))
    if session._log_futures:
        await asyncio.gather(*tuple(session._log_futures), return_exceptions=True)

    assert "telemetry write failed: database locked" in caplog.text


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
    @pytest.mark.parametrize("runtime_id", ("claude", "codex", "grok", "opencode"))
    @pytest.mark.asyncio
    async def test_turn_completion_signal_follows_persist_for_every_runtime(
        self, session, monkeypatch, runtime_id,
    ):
        from app.events import AgentEvent
        from app.runtime_registry import get_runtime
        from app.session import AgentStatus

        class OneTurnBackend:
            async def events(self):
                yield AgentEvent(
                    type="turn_end",
                    metadata={
                        "ok": True,
                        "stop_reason": "end_turn",
                        "num_turns": 1,
                        "cost_usd": 0,
                    },
                )

        observed = []
        runtime = get_runtime(runtime_id)
        session.backend_type = runtime_id
        session._backend = OneTurnBackend()
        session._log = lambda *_args, **_kwargs: None
        session._turns.bump_turn_gen()
        session.status = AgentStatus.RUNNING
        monkeypatch.setattr(
            session,
            "_persist",
            lambda: observed.append(
                (session.status, session._turn_finished_event.is_set())
            ),
        )
        monkeypatch.setattr(
            session._turns,
            "after_turn_idle_actions",
            lambda *_args, **_kwargs: None,
        )

        def discard_background(coroutine):
            coroutine.close()

        monkeypatch.setattr(session, "_spawn_bg", discard_background)

        waiter = asyncio.create_task(session.wait_for_turn_completion())
        await asyncio.sleep(0)
        assert waiter.done() is False

        if runtime.capabilities.event_stream == "persistent":
            await session._persistent_event_loop()
        else:
            await session._turn_event_loop()

        assert observed == [(AgentStatus.IDLE, False)]
        assert await asyncio.wait_for(waiter, timeout=0.2) is True
        assert session._turn_finished_event.is_set() is True

    @pytest.mark.asyncio
    async def test_waiting_status_finishes_turn_but_is_not_merge_ready(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        class ActiveJobs:
            def has_active_jobs(self, _session_id):
                return True

        monkeypatch.setattr("app.bg_jobs.bg_manager", ActiveJobs())
        session._log = lambda *_args, **_kwargs: None
        session._turns.bump_turn_gen()
        session.status = AgentStatus.RUNNING
        monkeypatch.setattr(session, "_persist", lambda: None)

        waiter = asyncio.create_task(session.wait_for_turn_completion())
        await asyncio.sleep(0)
        session._turns.finish_turn_status()

        assert await asyncio.wait_for(waiter, timeout=0.2) is False
        assert session.status is AgentStatus.WAITING

    @pytest.mark.asyncio
    async def test_auto_continue_segment_does_not_publish_terminal_signal(
        self, session, monkeypatch,
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus

        session.backend_type = "codex"
        session._log = lambda *_args, **_kwargs: None
        session._turns.bump_turn_gen()
        session.status = AgentStatus.RUNNING
        monkeypatch.setattr(session, "_persist", lambda: None)

        def discard_background(coroutine):
            coroutine.close()

        monkeypatch.setattr(session, "_spawn_bg", discard_background)
        waiter = asyncio.create_task(session.wait_for_turn_completion())
        await asyncio.sleep(0)

        session._handle_event(AgentEvent(
            type="turn_end",
            metadata={
                "ok": True,
                "stop_reason": "max_turns",
                "num_turns": 5,
                "cost_usd": 0,
            },
        ))

        assert session.status is AgentStatus.RUNNING
        assert session._turn_finished_event.is_set() is False
        assert waiter.done() is False
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

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
    async def test_stop_marks_running_session_interrupted(self, session):
        """stop() на РАБОТАЮЩЕЙ сессии → status=INTERRUPTED, backend disconnect вызван.

        Было IDLE. Изменено в #160: stop() зовётся только из shutdown_all, то есть
        ход не завершён, а оборван выключением сервера. Запись 'idle' стирала этот
        факт, и старт не знал, кого будить. Проверка поведения, не формы: агент,
        застигнутый в RUNNING, обязан остаться отличимым от честно закончившего.
        """
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

        assert session.status == AgentStatus.INTERRUPTED

    @pytest.mark.asyncio
    async def test_stop_leaves_finished_session_idle(self, session):
        """Обратная сторона: агент, честно закончивший ход, признака НЕ получает.

        Fail-closed в обе стороны (#160): пометить прерванным того, кто уже был IDLE,
        значит будить его после рестарта без причины.
        """
        from app.session import AgentStatus

        session.status = AgentStatus.IDLE
        await session.stop()

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
    async def test_running_reconnect_continues_without_quota_admission(
        self, session, monkeypatch,
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus

        class ReconnectingBackend:
            def __init__(self):
                self.event_calls = 0
                self.sent = []
                self.reconnects = 0

            async def events(self):
                self.event_calls += 1
                if self.event_calls == 1:
                    raise RuntimeError("stream dropped")
                yield AgentEvent("turn_end", metadata={
                    "ok": True, "stop_reason": "end_turn", "num_turns": 1,
                })

            async def reconnect(self):
                self.reconnects += 1

            async def send(self, message):
                self.sent.append(message)

        backend = ReconnectingBackend()
        session._backend = backend
        session.status = AgentStatus.RUNNING
        session._admission_service = AsyncMock(side_effect=AssertionError("reconnect read quota"))
        session._log = lambda *_args, **_kwargs: None
        monkeypatch.setattr("app.bg_jobs.bg_manager", None)

        await session._persistent_event_loop()

        assert backend.reconnects == 1
        assert backend.sent == [
            "[system] Connection was restored after interruption. Continue your work."
        ]
        session._admission_service.assert_not_awaited()

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
        session._log = lambda log_type, content, **_kwargs: logs.append((log_type, content))
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

    def test_dicts_include_git_lifecycle_fields(self):
        from app.session import AgentSession
        s = AgentSession(
            id="i", name="w", scope="/s", cwd="/tmp",
            branch="task-90/w", base_branch="master",
        )
        s.needs_switch = True

        assert s._to_db_dict()["base_branch"] == "master"
        assert s._to_db_dict()["needs_switch"] == 1
        assert s.to_dict()["base_branch"] == "master"
        assert s.to_dict()["needs_switch"] is True


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
                        model="claude-opus-5[1m]", system_prompt="x", role="worker")
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
        # Guard reads the live usage cache: at 100% of the 5h window compact refuses and
        # this test fails for a reason unrelated to what it checks.
        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active", lambda: False,
        )

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
        # LOG_COMPACT_SUMMARY off by default → summary не уходит в TG как речь агента
        assert not [c for t, c in logged if t == "text" and "Compact summary" in c]

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
    @pytest.fixture(autouse=True)
    def _auto_compact_enabled(self, monkeypatch):
        """#144: планирование компакта проверяется при ВКЛЮЧЁННОМ выключателе (#122).

        Иначе прогон читает `AUTO_COMPACT_ENABLED` из окружения машины — на VPS юнит подаёт
        `.env`, где стоит `0`, и три теста класса краснели на чужой настройке, а не на дефекте.
        Фикстура стоит на классе, а не на модуле: `TestAutoCompactKillSwitch` задаёт значение
        сам, и общая фикстура заглушила бы проверки самого выключателя.
        """
        monkeypatch.setenv("AUTO_COMPACT_ENABLED", "1")

    @staticmethod
    def _capture_background(session):
        spawned = []

        def capture(coro):
            spawned.append(coro.cr_code.co_name)
            coro.close()
            return MagicMock()

        session._spawn_bg = capture
        return spawned

    @pytest.mark.parametrize(
        ("current_tokens", "reason_fragment"),
        [
            (None, "aggregate totals"),
            (-1, "negative"),
            (500_001, "exceeds maximum"),
        ],
    )
    @pytest.mark.asyncio
    async def test_unknown_context_skips_both_compaction_paths_and_window_gate(
        self, session, monkeypatch, current_tokens, reason_fragment,
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus
        from app.usage_contract import AggregateUsage, TurnUsage, current_context

        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        logs = []
        session.backend_type = "grok"
        session.status = AgentStatus.RUNNING
        session._last_context = {
            "percentage": 100,
            "total_tokens": 1_678_471,
            "max_tokens": 500_000,
            "known": True,
        }
        session._log = lambda kind, content, **_kwargs: logs.append((kind, content))
        session._schedule_precompact_timer = MagicMock()
        session._auto_compact_window_state = MagicMock(side_effect=AssertionError)
        session._hibernate.schedule = MagicMock()
        spawned = self._capture_background(session)
        usage = TurnUsage(
            AggregateUsage.normalized(
                input_tokens=1_665_949,
                output_tokens=12_522,
                cache_read_tokens=1_581_056,
                model_calls=25,
            ),
            current_context(
                current_tokens,
                500_000,
                unknown_reason="aggregate totals are not current context",
            ),
        )

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={
                "ok": True,
                "stop_reason": "end_turn",
                "num_turns": 1,
                "cost_usd": 0,
                **usage.metadata(),
            },
            usage=usage,
        ))
        await session._drain_persist()

        assert session._last_context["known"] is False
        assert session._last_context["percentage"] == 0
        session._schedule_precompact_timer.assert_not_called()
        assert "_auto_compact" not in spawned
        session._auto_compact_window_state.assert_not_called()
        assert any(
            "context unknown" in content
            and reason_fragment in content
            and "automatic compaction skipped" in content
            for _, content in logs
        )

    @pytest.mark.asyncio
    async def test_claude_deferred_context_preserves_known_compaction_behavior(
        self, session, monkeypatch,
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus
        from app.usage_contract import (
            AggregateUsage,
            TurnUsage,
            deferred_context,
        )

        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        session.backend_type = "claude"
        session.status = AgentStatus.RUNNING
        session._last_context = {
            "percentage": 95,
            "total_tokens": 190_000,
            "max_tokens": 200_000,
            "known": True,
        }
        session._log = MagicMock()
        session._schedule_precompact_timer = MagicMock()
        session._hibernate.schedule = MagicMock()
        spawned = self._capture_background(session)
        usage = TurnUsage(
            AggregateUsage.normalized(input_tokens=10_000, model_calls=1),
            deferred_context(200_000, "claude_context_usage"),
        )

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={
                "ok": True,
                "stop_reason": "end_turn",
                "num_turns": 1,
                "cost_usd": 0,
                **usage.metadata(),
            },
            usage=usage,
        ))
        await session._drain_persist()

        session._schedule_precompact_timer.assert_called_once_with(95)
        assert "_auto_compact" in spawned

    @pytest.mark.asyncio
    async def test_codex_known_context_keeps_native_precompact_behavior(
        self, session, monkeypatch,
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus
        from app.usage_contract import AggregateUsage, TurnUsage, current_context

        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        session.backend_type = "codex"
        session.status = AgentStatus.RUNNING
        session._log = MagicMock()
        session._schedule_precompact_timer = MagicMock()
        session._hibernate.schedule = MagicMock()
        spawned = self._capture_background(session)
        usage = TurnUsage(
            AggregateUsage.normalized(input_tokens=60_000),
            current_context(180_880, 258_400),
        )

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={
                "ok": True,
                "stop_reason": "end_turn",
                "num_turns": 1,
                "cost_usd": 0,
                **usage.metadata(),
            },
            usage=usage,
        ))
        await session._drain_persist()

        session._schedule_precompact_timer.assert_called_once_with(70)
        assert "_auto_compact" not in spawned

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("schedule_on_success", "expected_calls"),
        [(True, 1), (False, 0)],
    )
    async def test_claude_context_refresh_reenters_shared_compaction_gate_once(
        self, session, schedule_on_success, expected_calls,
    ):
        backend = MagicMock()
        backend.context_usage = AsyncMock(return_value={
            "percentage": 95,
            "total_tokens": 190_000,
            "max_tokens": 200_000,
        })
        session._backend = backend
        session._turns.schedule_context_compaction = MagicMock()
        session._log = MagicMock()

        await session._refresh_context_from_api(
            schedule_compaction_on_success=schedule_on_success,
        )
        await session._drain_persist()

        assert session._last_context["known"] is True
        assert session._last_context["percentage"] == 95
        assert (
            session._turns.schedule_context_compaction.call_count
            == expected_calls
        )
        if schedule_on_success:
            session._turns.schedule_context_compaction.assert_called_once_with(95)

    @pytest.mark.asyncio
    async def test_invalid_context_refresh_cannot_reenter_compaction_gate(
        self, session,
    ):
        backend = MagicMock()
        backend.context_usage = AsyncMock(return_value={
            "percentage": 100,
            "total_tokens": 500_001,
            "max_tokens": 500_000,
        })
        session._backend = backend
        session._turns.schedule_context_compaction = MagicMock()
        session._cancel_precompact_timer = MagicMock()
        session._log = MagicMock()

        await session._refresh_context_from_api(
            schedule_compaction_on_success=True,
        )
        await session._drain_persist()

        assert session._last_context["known"] is False
        session._turns.schedule_context_compaction.assert_not_called()
        session._cancel_precompact_timer.assert_called_once_with("context_unknown")

    @pytest.mark.parametrize(
        ("subscription_limited", "stop_reason"),
        [(True, "end_turn"), (False, "max_turns")],
    )
    @pytest.mark.asyncio
    async def test_deferred_refresh_preserves_full_turn_compaction_gate(
        self, session, monkeypatch, subscription_limited, stop_reason,
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus
        from app.usage_contract import (
            AggregateUsage,
            TurnUsage,
            deferred_context,
        )

        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        flags = []

        def refresh(*, schedule_compaction_on_success):
            flags.append(schedule_compaction_on_success)

            async def done():
                return None

            return done()

        session.backend_type = "claude"
        session.status = AgentStatus.RUNNING
        session._session_limit_hit = subscription_limited
        session._refresh_context_from_api = refresh
        session._schedule_precompact_timer = MagicMock()
        session._hibernate.schedule = MagicMock()
        session._log = MagicMock()
        self._capture_background(session)
        usage = TurnUsage(
            AggregateUsage.normalized(input_tokens=10_000),
            deferred_context(200_000, "claude_context_usage"),
        )

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={
                "ok": True,
                "stop_reason": stop_reason,
                "num_turns": 1,
                "cost_usd": 0,
                **usage.metadata(),
            },
            usage=usage,
        ))
        await session._drain_persist()

        assert flags == [False]
        session._schedule_precompact_timer.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_precompact_rechecks_known_context_before_window(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        session.backend_type = "claude"
        session.status = AgentStatus.IDLE
        session._last_context = {
            "percentage": 95,
            "total_tokens": 0,
            "max_tokens": 200_000,
            "known": False,
        }
        session._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "backend": "claude",
            "context_threshold": 20,
        }
        session._log = MagicMock()
        session.compact = AsyncMock()
        session._auto_compact_window_state = MagicMock(side_effect=AssertionError)
        monkeypatch.setattr(
            "app.bg_jobs.bg_manager",
            MagicMock(has_active_jobs=lambda *_: False),
        )

        await session._fire_precompact_timer()

        session.compact.assert_not_awaited()
        session._auto_compact_window_state.assert_not_called()
        assert session._precompact_timer is None
        assert any(
            '"skip_reason": "unknown_context"' in call.args[1]
            for call in session._log.call_args_list
        )

    @pytest.mark.parametrize(
        ("now_utc", "allowed"),
        [
            (datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc), True),
            (datetime(2026, 7, 28, 22, 59, tzinfo=timezone.utc), True),
            (datetime(2026, 7, 28, 23, 0, tzinfo=timezone.utc), False),
            (datetime(2026, 7, 28, 5, 0, tzinfo=timezone.utc), False),
        ],
    )
    def test_auto_compact_window_uses_explicit_timezone(
        self, session, now_utc, allowed, monkeypatch,
    ):
        monkeypatch.delenv("AUTO_COMPACT_WINDOW_START", raising=False)
        monkeypatch.delenv("AUTO_COMPACT_WINDOW_END", raising=False)
        monkeypatch.delenv("AUTO_COMPACT_TIMEZONE", raising=False)
        session.AUTO_COMPACT_WINDOW_START = "21:00"
        session.AUTO_COMPACT_WINDOW_END = "06:00"
        session.AUTO_COMPACT_TIMEZONE = "Asia/Krasnoyarsk"

        state = session._auto_compact_window_state(now_utc)

        assert state["allowed"] is allowed
        assert state["timezone"] == "Asia/Krasnoyarsk"
        assert state["window"] == "21:00-06:00"

    def test_auto_compact_window_rejects_invalid_timezone(
        self, session, monkeypatch,
    ):
        monkeypatch.delenv("AUTO_COMPACT_WINDOW_START", raising=False)
        monkeypatch.delenv("AUTO_COMPACT_WINDOW_END", raising=False)
        monkeypatch.delenv("AUTO_COMPACT_TIMEZONE", raising=False)
        session.AUTO_COMPACT_TIMEZONE = "UTC+7"

        with pytest.raises(RuntimeError, match="AUTO_COMPACT_TIMEZONE"):
            session._auto_compact_window_state(
                datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc)
            )

    def test_startup_validation_rejects_invalid_window(self, monkeypatch):
        from app.session import validate_auto_compact_window_config

        monkeypatch.setenv("AUTO_COMPACT_WINDOW_START", "25:00")

        with pytest.raises(RuntimeError, match="AUTO_COMPACT_WINDOW_START"):
            validate_auto_compact_window_config()

    def test_auto_compact_window_reads_environment_at_runtime(
        self, session, monkeypatch,
    ):
        monkeypatch.setenv("AUTO_COMPACT_WINDOW_START", "22:00")
        monkeypatch.setenv("AUTO_COMPACT_WINDOW_END", "05:00")
        monkeypatch.setenv("AUTO_COMPACT_TIMEZONE", "Europe/Berlin")

        state = session._auto_compact_window_state(
            datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc)
        )

        assert state["allowed"] is True
        assert state["window"] == "22:00-05:00"
        assert state["timezone"] == "Europe/Berlin"

    @pytest.mark.asyncio
    async def test_orchestrator_precompact_is_blocked_outside_window(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        logs = []
        session.is_orchestrator = True
        session.backend_type = "claude"
        session.status = AgentStatus.IDLE
        session._last_context["percentage"] = 60
        session._log = lambda log_type, content, **_kwargs: logs.append((log_type, content))
        session.compact = AsyncMock(return_value={"ok": True})
        session._auto_compact_window_state = MagicMock(return_value={
            "allowed": False,
            "local_time": "2026-07-28T15:35+07:00",
            "timezone": "Asia/Krasnoyarsk",
            "window": "21:00-06:00",
        })
        session._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "backend": "claude",
            "context_threshold": 20,
        }
        monkeypatch.setattr(
            "app.bg_jobs.bg_manager",
            MagicMock(has_active_jobs=lambda *_: False),
        )

        await session._fire_precompact_timer()

        session.compact.assert_not_awaited()
        assert session._precompact_timer is None
        blocked = [
            content for log_type, content in logs
            if log_type == "status" and content.startswith("auto-compact blocked")
        ]
        assert blocked
        assert "21:00-06:00 Asia/Krasnoyarsk" in blocked[0]
        assert "manual compact remains available" in blocked[0]

    @pytest.mark.asyncio
    async def test_orchestrator_precompact_runs_inside_window(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        session.is_orchestrator = True
        session.backend_type = "claude"
        session.status = AgentStatus.IDLE
        session._last_context["percentage"] = 60
        session._log = MagicMock()
        session.compact = AsyncMock(return_value={"ok": True})
        session._auto_compact_window_state = MagicMock(return_value={
            "allowed": True,
            "local_time": "2026-07-28T22:00+07:00",
            "timezone": "Asia/Krasnoyarsk",
            "window": "21:00-06:00",
        })
        session._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "backend": "claude",
            "context_threshold": 20,
        }
        monkeypatch.setattr(
            "app.bg_jobs.bg_manager",
            MagicMock(has_active_jobs=lambda *_: False),
        )

        await session._fire_precompact_timer()

        session.compact.assert_awaited_once_with()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["worker", "full-cycle", "researcher"])
    async def test_worker_precompact_ignores_orchestrator_window(
        self, session, monkeypatch, role,
    ):
        from app.session import AgentStatus

        session.role = role
        session._is_orchestrator = None
        assert session.is_orchestrator is False
        session.backend_type = "claude"
        session.status = AgentStatus.IDLE
        session._last_context["percentage"] = 60
        session._log = MagicMock()
        session.compact = AsyncMock(return_value={"ok": True})
        session._auto_compact_window_state = MagicMock(side_effect=AssertionError)
        session._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "backend": "claude",
            "context_threshold": 20,
        }
        monkeypatch.setattr(
            "app.bg_jobs.bg_manager",
            MagicMock(has_active_jobs=lambda *_: False),
        )

        await session._fire_precompact_timer()

        session.compact.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_critical_orchestrator_context_warns_once_outside_window(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        logs = []
        launched = []
        session.is_orchestrator = True
        session.backend_type = "claude"
        session.status = AgentStatus.IDLE
        session._last_context["percentage"] = 95
        session._log = lambda log_type, content, **_kwargs: logs.append((log_type, content))
        session.compact = AsyncMock(return_value={"ok": True})
        session._auto_compact_window_state = MagicMock(return_value={
            "allowed": False,
            "local_time": "2026-07-28T15:35+07:00",
            "timezone": "Asia/Krasnoyarsk",
            "window": "21:00-06:00",
        })

        def capture(coro):
            launched.append(coro)
            coro.close()
            return MagicMock(done=lambda: False)

        session._spawn_bg = capture
        monkeypatch.setattr(
            "app.bg_jobs.bg_manager",
            MagicMock(has_active_jobs=lambda *_: False),
        )

        session._schedule_precompact_timer(95)
        await session._fire_precompact_timer()

        assert len(launched) == 1
        warnings = [
            content for log_type, content in logs
            if log_type == "status" and content.startswith("auto-compact deferred")
        ]
        assert len(warnings) == 1
        assert "context 95%" in warnings[0]
        assert not [
            content for log_type, content in logs
            if log_type == "status" and content.startswith("auto-compact blocked")
        ]
        session.compact.assert_not_awaited()

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
        session._log = lambda log_type, content, **_kwargs: logs.append((log_type, content))
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
    async def test_codex_manual_compact_ignores_orchestrator_window(
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
        session.is_orchestrator = True
        session._auto_compact_window_state = MagicMock(side_effect=AssertionError)
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
        session._log = lambda log_type, content, **_kwargs: logs.append((log_type, content))
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
        session._log = lambda log_type, content, **_kwargs: logs.append((log_type, content))
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
        session._log = lambda log_type, content, **_kwargs: logs.append((log_type, content))
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
        session._log = lambda log_type, content, **_kwargs: logs.append((log_type, content))
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
    async def test_turn_end_persists_normalized_structured_usage(
        self, session, monkeypatch
    ):
        from app.events import AgentEvent

        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        add_usage = MagicMock(return_value=True)
        monkeypatch.setattr("app.session_turns.turn_usage_add", add_usage)
        monkeypatch.setattr(
            "app.session_turns._cached_quota_state",
            lambda runtime, model: {
                "quota_five_hour_pct": 12.5,
                "quota_seven_day_pct": 41,
                "quota_primary_pct": None,
                "quota_sampled_at": "2026-07-29T08:00:00+00:00",
            },
        )
        self._capture_coroutines(session)
        session._hibernate.schedule = MagicMock()

        session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
            "event_id": "result-uuid-1",
            "ok": True,
            "stop_reason": "end_turn",
            "num_turns": 1,
            "cost_usd": 2.5,
            "cost_is_delta": True,
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read": 75,
            "cache_create": 5,
        }))
        if session._log_futures:
            await asyncio.gather(*tuple(session._log_futures), return_exceptions=True)
        await session._drain_persist()

        add_usage.assert_called_once_with(
            event_id="result-uuid-1",
            session_id="test-001",
            scope="/test",
            runtime="claude",
            model="claude-sonnet-5[1m]",
            task_id="",
            ok=True,
            stop_reason="end_turn",
            cost_usd=2.5,
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=75,
            cache_create_tokens=5,
            quota_five_hour_pct=12.5,
            quota_seven_day_pct=41,
            quota_primary_pct=None,
            quota_sampled_at="2026-07-29T08:00:00+00:00",
        )

    @pytest.mark.asyncio
    async def test_turn_telemetry_failure_does_not_skip_terminal_lifecycle(
        self, session, monkeypatch, caplog
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus

        monkeypatch.setattr(
            "app.session_turns.turn_usage_add",
            MagicMock(side_effect=RuntimeError("database locked")),
        )
        self._capture_coroutines(session)
        session._hibernate.schedule = MagicMock()

        session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
            "event_id": "result-uuid-1",
            "ok": True,
            "stop_reason": "end_turn",
            "num_turns": 1,
            "cost_usd": 1.0,
            "cost_is_delta": True,
        }))
        if session._log_futures:
            await asyncio.gather(
                *tuple(session._log_futures),
                return_exceptions=True,
            )
        await session._drain_persist()

        assert session.status == AgentStatus.IDLE
        assert "telemetry write failed: database locked" in caplog.text

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


class TestCompactReArmsPromptInjection:
    """#126: a resumed CLI is never given system_prompt (backend_claude.py:165-168).

    compact() switches the session to a NEW native session_id, so every later
    reconnect is a resume — the role would be gone. The injector at
    session.py:680 is gated on `not _prompt_injected`, so compact must re-arm it.
    """

    @staticmethod
    def _compact_backend(summary_text):
        from app.events import AgentEvent

        class CompactBackend:
            session_id = None

            def __init__(self):
                self.sent = []

            async def connect(self): pass
            async def send(self, msg): self.sent.append(msg)
            async def events(self):
                yield AgentEvent(type="text", content=summary_text)
                yield AgentEvent(
                    type="turn_end",
                    metadata={"ok": True, "stop_reason": "end_turn",
                              "num_turns": 1, "session_id": "post-compact-sid"},
                )
            async def interrupt(self): pass
            async def disconnect(self): pass
            async def reconnect(self): pass

        return CompactBackend()

    async def _run_compact(self, session, monkeypatch):
        monkeypatch.setattr("app.bg_jobs.bg_manager", None)
        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active", lambda: False
        )
        backend = self._compact_backend("TASK STATE: shipping #126. " + "x" * 250)
        ack_set = False

        async def fake_ensure_backend(force_fresh=False):
            nonlocal ack_set
            session._backend = backend
            if not ack_set and session._compact_ack_event:
                async def _set_ack():
                    await asyncio.sleep(0.05)
                    if session._compact_ack_event:
                        session._compact_ack_event.set()
                asyncio.create_task(_set_ack())
                ack_set = True
            return backend

        with patch.object(session, "_make_backend", return_value=backend), \
             patch.object(session, "_ensure_backend", side_effect=fake_ensure_backend):
            return await session.compact(), backend

    @pytest.mark.asyncio
    async def test_successful_compact_rearms_prompt_injection(
        self, session, monkeypatch
    ):
        session._log = MagicMock()
        session._prompt_injected = True

        result, _ = await self._run_compact(session, monkeypatch)

        assert result["ok"] is True
        assert session.session_id == "post-compact-sid", (
            "compact must adopt the new native session id"
        )
        assert session._prompt_injected is False, (
            "role must be re-injected on the next turn; a resumed CLI gets no system_prompt"
        )

    @pytest.mark.asyncio
    async def test_failed_compact_leaves_injection_flag_untouched(
        self, session, monkeypatch
    ):
        """Abort restores the pre-compact session, whose prompt is still live.

        Re-arming there would buy a needless full re-inject (~270k input) after
        every failed compact.
        """
        from app.events import AgentEvent

        class LimitBackend:
            async def connect(self): return None
            async def send(self, _message): return None
            async def events(self):
                yield AgentEvent(
                    type="text",
                    content=(
                        "You've hit your monthly spend limit · raise it at "
                        "claude.ai/settings/usage"
                    ),
                )
                yield AgentEvent(
                    type="turn_end", metadata={"session_id": "bad-compact-session"}
                )
            async def disconnect(self): return None

        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active", lambda: False
        )
        session.session_id = "original-session"
        session._prompt_injected = True
        session._log = MagicMock()
        session._make_backend = MagicMock(return_value=LimitBackend())
        session._ensure_backend = AsyncMock()

        result = await session.compact()

        assert result["ok"] is False
        assert session.session_id == "original-session"
        assert session._prompt_injected is True, (
            "failed compact keeps the old session, so its prompt is still injected"
        )

    @pytest.mark.asyncio
    async def test_role_is_back_in_the_prompt_on_the_turn_after_compact(
        self, session, monkeypatch
    ):
        """End-to-end: the requirement is the ROLE returns, not that a flag flipped."""
        from app.events import AgentEvent
        from app.session import AgentStatus

        session._log = MagicMock()
        session._prompt_injected = True
        session._current_prompt = "ROLE: full-cycle worker. STOP at every gate."

        await self._run_compact(session, monkeypatch)

        # Now the first turn after compact, over a RESUMED backend (no system_prompt).
        sent = []
        resumed = AsyncMock()
        resumed.send = AsyncMock(side_effect=lambda m: sent.append(m))

        async def events():
            yield AgentEvent(type="turn_end", content="",
                             metadata={"ok": True, "session_id": "post-compact-sid"})

        resumed.events = lambda: events()
        session._backend = resumed
        session.status = AgentStatus.IDLE
        session._log = MagicMock()
        session._persist = MagicMock()
        monkeypatch.setattr("app.session.get_logs", lambda *_a, **_kw: [])

        with patch.object(session, "_ensure_backend", AsyncMock(return_value=resumed)):
            await session.send("next task")

        assert sent, "the turn after compact must reach the backend"
        assert "[Orchestra platform note:" in sent[0], (
            "role must be re-delivered after compact"
        )
        assert "ROLE: full-cycle worker. STOP at every gate." in sent[0], (
            "the actual role text must be present, not just the wrapper"
        )

    @pytest.mark.asyncio
    async def test_personal_memory_written_mid_session_is_re_read_from_disk(
        self, session, monkeypatch, tmp_path
    ):
        """#137: a lesson the worker writes to its own memory must come back to it.

        Measured before the fix: 11 of 13 live sessions carried a stale <worker-memory>
        block, the worst missing 61% of its own file, because `_current_prompt` was only
        ever assembled in `_load_from_db` — i.e. on server restart.
        """
        from app.events import AgentEvent
        from app.session import AgentStatus

        mem_dir = tmp_path / "docs" / "workers"
        mem_dir.mkdir(parents=True)
        session.scope = str(tmp_path)
        session.role = "worker"
        session._log = MagicMock()
        session._prompt_injected = True
        session._current_prompt = (
            "ROLE: worker.\n\n<worker-memory>\nSTALE: written at spawn\n</worker-memory>"
        )

        # The worker learns something and writes it down mid-session.
        (mem_dir / f"{session.name}.md").write_text("FRESH: learned this mid-session")

        await self._run_compact(session, monkeypatch)

        sent = []
        resumed = AsyncMock()
        resumed.send = AsyncMock(side_effect=lambda m: sent.append(m))

        async def events():
            yield AgentEvent(type="turn_end", content="",
                             metadata={"ok": True, "session_id": "post-compact-sid"})

        resumed.events = lambda: events()
        session._backend = resumed
        session.status = AgentStatus.IDLE
        session._log = MagicMock()
        session._persist = MagicMock()
        monkeypatch.setattr("app.session.get_logs", lambda *_a, **_kw: [])

        with patch.object(session, "_ensure_backend", AsyncMock(return_value=resumed)):
            await session.send("next task")

        assert sent, "the turn after compact must reach the backend"
        assert "FRESH: learned this mid-session" in sent[0], (
            "memory written during the session must be re-read from disk, "
            "not served from the string cached at the last server restart"
        )
        assert "STALE: written at spawn" not in sent[0], (
            "the superseded memory block must be replaced, not appended to"
        )


class TestCompactPromptContract:
    """#106 Q6: properties the measured GO rests on. Changing these invalidates the experiment."""

    async def _captured_prompt(self, session, monkeypatch):
        from app.events import AgentEvent

        sent = []
        backend = AsyncMock()
        backend.send = AsyncMock(side_effect=lambda m: sent.append(m))

        async def events():
            yield AgentEvent(type="text", content="x" * 300)
            yield AgentEvent(type="turn_end", content="", metadata={"session_id": "s2"})

        backend.events = lambda: events()
        session._backend = backend
        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active", lambda: False
        )
        await session.compact()
        return sent[0] if sent else ""

    @pytest.mark.asyncio
    async def test_prompt_forbids_creating_notes_for_compaction(
        self, session, monkeypatch
    ):
        prompt = await self._captured_prompt(session, monkeypatch)
        assert "Never create CLAUDE.md, TODO.md, BUGS.md" in prompt
        # the old unconditional presave drove 218 unrelated writes in 63 outputs
        assert "Use Edit/Write tools NOW" not in prompt

    @pytest.mark.asyncio
    async def test_prompt_forbids_both_polarities_of_file_action_claims(
        self, session, monkeypatch
    ):
        prompt = await self._captured_prompt(session, monkeypatch)
        assert "Do not assert the negative either" in prompt
        assert "never supports `not read`" in prompt

    @pytest.mark.asyncio
    async def test_prompt_preserves_recent_user_messages_verbatim(
        self, session, monkeypatch
    ):
        prompt = await self._captured_prompt(session, monkeypatch)
        assert "last three user messages verbatim" in prompt

    @pytest.mark.asyncio
    async def test_prompt_is_identical_for_orchestrator_and_worker(
        self, session, monkeypatch
    ):
        session.is_orchestrator = False
        worker_prompt = await self._captured_prompt(session, monkeypatch)
        session.is_orchestrator = True
        orch_prompt = await self._captured_prompt(session, monkeypatch)
        assert worker_prompt == orch_prompt


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

    @pytest.mark.asyncio
    async def test_connect_failure_retains_backend_that_still_owns_processes(
        self, session,
    ):
        backend = SimpleNamespace(
            connect=AsyncMock(side_effect=RuntimeError("scope still populated")),
            has_owned_processes=True,
        )
        with patch.object(session, "_make_backend", return_value=backend):
            with pytest.raises(RuntimeError, match="scope still populated"):
                await session._ensure_backend()

        assert session._backend is backend

    @pytest.mark.asyncio
    async def test_connect_failure_releases_backend_without_owned_processes(
        self, session,
    ):
        backend = SimpleNamespace(
            connect=AsyncMock(side_effect=RuntimeError("no process")),
            has_owned_processes=False,
        )
        with patch.object(session, "_make_backend", return_value=backend):
            with pytest.raises(RuntimeError, match="no process"):
                await session._ensure_backend()

        assert session._backend is None

    @pytest.mark.asyncio
    async def test_disconnect_failure_retains_backend_and_lifecycle_tasks(
        self, session,
    ):
        backend = SimpleNamespace(
            disconnect=AsyncMock(side_effect=PermissionError("scope denied")),
        )
        heartbeat = asyncio.create_task(asyncio.Event().wait())
        listener = asyncio.create_task(asyncio.Event().wait())
        session._backend = backend
        session._heartbeat_task = heartbeat
        session._listen_task = listener

        try:
            with pytest.raises(PermissionError, match="scope denied"):
                await session._disconnect_backend()

            assert session._backend is backend
            assert heartbeat.cancelled() is False
            assert listener.cancelled() is False
        finally:
            heartbeat.cancel()
            listener.cancel()
            await asyncio.gather(heartbeat, listener, return_exceptions=True)


class TestHibernateDeliveryRaces:
    @pytest.mark.asyncio
    async def test_failed_steer_queues_before_hibernate_can_observe_state(
        self, session,
    ):
        from app.session import AgentStatus

        steer_started = asyncio.Event()
        finish_steer = asyncio.Event()

        async def fail_steer(_message):
            steer_started.set()
            await finish_steer.wait()
            raise RuntimeError("turn already ended")

        backend = SimpleNamespace(send=AsyncMock(side_effect=fail_steer))
        session.backend_type = "codex"
        session.status = AgentStatus.RUNNING
        session._backend = backend
        spawned = []

        def capture(coro):
            spawned.append(coro.cr_code.co_name)
            coro.close()
            return MagicMock()

        session._spawn_bg = capture
        send_task = asyncio.create_task(session.send("late message"))
        await steer_started.wait()
        session.status = AgentStatus.IDLE
        hibernate_task = asyncio.create_task(session.hibernate_now())
        finish_steer.set()

        await send_task
        result = await hibernate_task

        assert session._pending_messages == ["late message"]
        assert result["reason"] == "pending_delivery"
        assert "_flush_pending" in spawned
        assert session._hibernated is False

    @pytest.mark.asyncio
    async def test_flush_holds_delivery_ownership_until_send_finishes(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        send_started = asyncio.Event()
        finish_send = asyncio.Event()

        async def send(_message):
            send_started.set()
            await finish_send.wait()

        monkeypatch.setattr("app.session.asyncio.sleep", AsyncMock())
        monkeypatch.setattr(
            "app.session.get_runtime",
            lambda _runtime: SimpleNamespace(
                capabilities=SimpleNamespace(event_stream="persistent"),
            ),
        )
        backend = SimpleNamespace(
            send=AsyncMock(side_effect=send),
            hibernate_safe=True,
        )
        session.backend_type = "codex"
        session.status = AgentStatus.IDLE
        session._backend = backend
        session._pending_messages = ["queued"]
        session._ensure_backend = AsyncMock(return_value=backend)

        flush_task = asyncio.create_task(session._flush_pending())
        await send_started.wait()
        hibernate_task = asyncio.create_task(session.hibernate_now())
        finish_send.set()

        await flush_task
        result = await hibernate_task

        assert result["reason"] == "not_idle"
        assert session._pending_messages == []
        assert backend.send.await_count == 1
        assert session._hibernated is False

    @pytest.mark.asyncio
    async def test_failed_flush_restores_payload_before_hibernate_check(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        send_started = asyncio.Event()
        fail_send = asyncio.Event()

        async def send(_message):
            send_started.set()
            await fail_send.wait()
            raise RuntimeError("send failed")

        monkeypatch.setattr("app.session.asyncio.sleep", AsyncMock())
        backend = SimpleNamespace(
            send=AsyncMock(side_effect=send),
            hibernate_safe=True,
        )
        session.backend_type = "codex"
        session.status = AgentStatus.IDLE
        session._backend = backend
        session._pending_messages = ["must survive"]
        session._ensure_backend = AsyncMock(return_value=backend)

        flush_task = asyncio.create_task(session._flush_pending())
        await send_started.wait()
        hibernate_task = asyncio.create_task(session.hibernate_now())
        fail_send.set()

        await flush_task
        result = await hibernate_task

        assert result["reason"] == "pending_delivery"
        assert session._pending_messages == ["must survive"]
        assert session._hibernated is False

    @pytest.mark.asyncio
    async def test_send_wakes_without_changing_native_session_id(self, session):
        from app.session import AgentStatus

        backend = SimpleNamespace(send=AsyncMock())
        session.backend_type = "codex"
        session.status = AgentStatus.IDLE
        session.session_id = "thread-preserved"
        session._hibernated = True
        session._ensure_backend = AsyncMock(return_value=backend)

        await session.send("wake")

        assert session._hibernated is False
        assert session.session_id == "thread-preserved"
        backend.send.assert_awaited_once_with("wake")


class TestCodexTurnLifecycle:
    @pytest.mark.asyncio
    async def test_stale_compact_lifecycle_cannot_false_idle_current_turn(
        self, session, monkeypatch
    ):
        from app.backend_codex import CodexBackend
        from app.live_broker import broker
        from app.session import AgentStatus

        published = []
        monkeypatch.setattr(
            broker,
            "publish",
            lambda _session_id, payload: published.append(payload),
        )
        session._hibernate.schedule = MagicMock()

        backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
        backend._proc = MagicMock(returncode=None)
        backend._thread_id = "thread-1"
        backend._active_turn_id = "task-turn"
        session.backend_type = "codex"
        session._backend = backend
        session.status = AgentStatus.RUNNING

        for method in ("turn/started", "turn/completed"):
            await backend._notifications.put({
                "method": method,
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "compact-turn"},
                },
            })

        listener = asyncio.create_task(session._turn_event_loop())
        await asyncio.sleep(0.01)

        assert listener.done() is False
        assert session.status == AgentStatus.RUNNING
        assert backend._active_turn_id == "task-turn"

        for message in (
            {
                "method": "turn/started",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "task-turn"},
                },
            },
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-1",
                    "delta": "FIRST_PROCESSED",
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "task-turn", "status": "completed"},
                },
            },
        ):
            await backend._notifications.put(message)

        await asyncio.wait_for(listener, timeout=0.5)
        assert session.status == AgentStatus.IDLE
        assert any(
            payload.get("type") == "stream"
            and payload.get("content") == "FIRST_PROCESSED"
            for payload in published
        )

    @pytest.mark.asyncio
    async def test_native_compact_cannot_leak_lifecycle_into_next_listener(
        self, session, monkeypatch
    ):
        from app.backend_codex import CodexBackend
        from app.live_broker import broker
        from app.session import AgentStatus

        published = []
        monkeypatch.setattr(
            broker,
            "publish",
            lambda _session_id, payload: published.append(payload),
        )
        session._hibernate.schedule = MagicMock()

        backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
        backend._thread_id = "thread-1"
        stdout = asyncio.StreamReader()
        backend._proc = SimpleNamespace(
            returncode=None,
            stdout=stdout,
            wait=AsyncMock(return_value=0),
        )
        backend._reader_task = asyncio.create_task(backend._read_stdout())

        def feed(message):
            stdout.feed_data((json.dumps(message) + "\n").encode())

        compact_completion_emitted = asyncio.Event()

        async def request(method, _params):
            if method == "thread/compact/start":
                for message in (
                    {
                        "method": "turn/started",
                        "params": {
                            "threadId": "thread-1",
                            "turn": {"id": "compact-turn"},
                        },
                    },
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": "thread-1",
                            "item": {
                                "type": "contextCompaction",
                                "id": "compact-1",
                            },
                        },
                    },
                ):
                    feed(message)
                compact_completion_emitted.set()
                return {}
            if method == "turn/start":
                return {"turn": {"id": "task-turn"}}
            raise AssertionError(f"unexpected request: {method}")

        backend._request = AsyncMock(side_effect=request)
        try:
            compact_task = asyncio.create_task(backend.compact_context())
            await asyncio.wait_for(compact_completion_emitted.wait(), timeout=0.5)
            done, _ = await asyncio.wait({compact_task}, timeout=0.05)
            assert compact_task not in done
            feed({
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {
                        "id": "compact-turn",
                        "status": "completed",
                    },
                },
            })
            await asyncio.wait_for(compact_task, timeout=0.5)
            assert backend._notifications.empty()

            session.backend_type = "codex"
            session._backend = backend
            session.status = AgentStatus.IDLE
            await session.send("FIRST")

            for message in (
                {
                    "method": "turn/started",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {"id": "task-turn"},
                    },
                },
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "thread-1",
                        "delta": "FIRST_PROCESSED",
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {"id": "task-turn", "status": "completed"},
                    },
                },
            ):
                feed(message)

            await asyncio.wait_for(session._listen_task, timeout=0.5)
        finally:
            backend._disconnecting = True
            stdout.feed_eof()
            await asyncio.wait_for(backend._reader_task, timeout=0.5)

        assert session.status == AgentStatus.IDLE
        assert backend._notifications.empty()
        assert any(
            payload.get("type") == "stream"
            and payload.get("content") == "FIRST_PROCESSED"
            for payload in published
        )

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
        session._admission_service = AsyncMock(side_effect=AssertionError("model control read quota"))
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
        session._admission_service.assert_not_awaited()

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


@pytest.mark.asyncio
async def test_image_tool_result_is_logged_verbatim_not_as_a_blob_reference(
    session, tmp_path, monkeypatch,
):
    """Запись картинок в блобы (#78) выключена: клиентской половины нет.

    Первая же картинка после включения перестала бы показываться — фронт не знает типа
    `blob`. Тест держит выключенным именно ПУТЬ ЗАПИСИ: хранилище и чтение оставлены.
    """
    import app.blobs as blobs
    from app.events import AgentEvent

    import base64

    monkeypatch.setattr(blobs, "BLOB_ROOT", tmp_path / "blobs")
    session._log = MagicMock()
    # Форма ровно из живой БД (python-repr, без префикса `data:image`) — иначе
    # `store_images` её не узнаёт и тест зеленеет при ВКЛЮЧЁННОЙ записи.
    image = base64.b64encode(bytes(range(256)) * 40).decode()
    payload = ("{'type': 'image', 'source': {'type': 'base64', 'data': '"
               + image + "', 'media_type': 'image/png'}}")

    session._handle_event(AgentEvent("tool_result", payload, {"tool_use_id": "t-1"}))
    if session._log_futures:
        await asyncio.gather(*tuple(session._log_futures), return_exceptions=True)

    session._log.assert_any_call("tool_result", payload)
    assert not (tmp_path / "blobs").exists()


class TestAutoCompactKillSwitch:
    """`AUTO_COMPACT_ENABLED=0` — выключатель автокомпакта оркестратора (#122).

    Жалоба была буквальной: ночью идёт работа, утром оркестратор приходит с компакта.
    Окно 21:00-06:00 компакт внутри себя РАЗРЕШАЛО, то есть срабатывало ровно в рабочие часы,
    а выключателя не существовало вовсе.
    """

    @staticmethod
    def _orchestrator(session, monkeypatch):
        monkeypatch.delenv("AUTO_COMPACT_WINDOW_START", raising=False)
        monkeypatch.delenv("AUTO_COMPACT_WINDOW_END", raising=False)
        monkeypatch.delenv("AUTO_COMPACT_TIMEZONE", raising=False)
        session._is_orchestrator = True
        session.backend_type = "claude"
        session._last_context = {"percentage": 95, "known": True}
        return session

    def test_disabled_blocks_compaction_inside_the_window(self, session, monkeypatch):
        """Внутри окна компакт разрешён, значит проверять флаг надо именно здесь."""
        s = self._orchestrator(session, monkeypatch)
        logs = []
        s._log = lambda kind, content, **_kw: logs.append(content)
        inside_window = datetime(2026, 7, 28, 23, 0, tzinfo=timezone.utc)  # 06:00 Krasnoyarsk
        assert s._auto_compact_window_state(inside_window)["allowed"] is False

        monkeypatch.setenv("AUTO_COMPACT_ENABLED", "0")
        assert s._auto_compact_window_blocked(95, inside_window) is True
        assert any("AUTO_COMPACT_ENABLED=0" in line for line in logs)
        assert any("manual compact remains available" in line for line in logs)

    def test_disabled_does_not_arm_the_precompact_timer(self, session, monkeypatch):
        s = self._orchestrator(session, monkeypatch)
        logs = []
        s._log = lambda kind, content, **_kw: logs.append(content)
        monkeypatch.setenv("AUTO_COMPACT_ENABLED", "0")

        s._schedule_precompact_timer(95)
        s._schedule_precompact_timer(95)  # решение принимается каждый ход

        assert s._precompact_timer is None
        assert sum("AUTO_COMPACT_ENABLED=0" in line for line in logs) == 1, \
            "причина не меняется — в журнал она попадает один раз за сессию"

    def test_enabled_is_the_current_behaviour(self, session, monkeypatch):
        """Дефолт — как было: переменной нет, таймер взводится, гейт решает по окну."""
        s = self._orchestrator(session, monkeypatch)
        s._log = lambda *_a, **_kw: None
        # взведённый таймер уходит в фон, а лупа в синхронном тесте нет
        s._spawn_bg = lambda coro: (coro.close(), MagicMock())[1]
        monkeypatch.delenv("AUTO_COMPACT_ENABLED", raising=False)

        s._schedule_precompact_timer(95)

        assert s._precompact_timer is not None
        allowed_hour = datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc)  # 21:00 Krasnoyarsk
        assert s._auto_compact_window_blocked(95, allowed_hour, log_status=False) is False

    def test_worker_path_is_untouched_by_the_switch(self, session, monkeypatch):
        """Воркерский автокомпакт защищает от упора в лимит — флаг его не касается."""
        monkeypatch.setenv("AUTO_COMPACT_ENABLED", "0")
        session._is_orchestrator = False
        assert session._auto_compact_window_blocked(95) is False

    @pytest.mark.parametrize(
        ("raw", "enabled"),
        [("0", False), ("false", False), ("no", False), ("1", True), ("true", True), ("", False)],
    )
    def test_value_is_read_on_every_decision(self, monkeypatch, raw, enabled):
        from app.session import auto_compact_enabled
        monkeypatch.setenv("AUTO_COMPACT_ENABLED", raw)
        assert auto_compact_enabled() is enabled


class TestSafeguardRefusal:
    """#155: отказ фильтра провайдера — отдельный класс, с автооткатом отравленной истории.

    Замер на живой стенограмме seedon: забракованный текст остаётся в JSONL CLI и едет в
    КАЖДЫЙ следующий запрос — второй ход на постороннюю тему получил тот же отказ дословно.
    """

    VERBATIM = (
        "API Error: claude-opus-5[1m]'s safeguards flagged this message for a "
        "cybersecurity topic. If your work requires this access, you can apply for an "
        "exemption: https://claude.com/form/cyber-use-case\n"
        "Try rephrasing the request in a new session or change your model.\n"
        "Request ID: req_011CdnzxjQByYxoRQweVSmGK"
    )
    # Ход 07.08 16:27:01: агент объясняет инцидент и цитирует фразу отказа внутри
    # собственного длинного ответа. Ход при этом УСПЕШНЫЙ.
    AGENT_QUOTING_IT = (
        "**Пнул. Состояние: все свободны, ничего не потеряно.**\n\n"
        "Теперь про ту ошибку, которая тебя удивила.\n\n"
        "`safeguards flagged this message for a cybersecurity topic` — это фильтр на "
        "стороне Anthropic, он смотрит на формулировку, а не на намерение."
    )

    def test_verbatim_refusal_is_recognised(self):
        from app.session import _is_safeguard_refusal

        assert _is_safeguard_refusal(self.VERBATIM) is True

    def test_ordinary_invalid_request_is_not_recognised(self):
        """Fail-open: по коду ошибки эти случаи неразличимы, значит опора только на текст."""
        from app.session import _is_safeguard_refusal

        assert _is_safeguard_refusal(
            "API Error: invalid_request: max_tokens: must be greater than 0"
        ) is False
        assert _is_safeguard_refusal("model error: invalid_request") is False
        assert _is_safeguard_refusal(
            "I cannot help with that request — it involves cybersecurity harm."
        ) is False

    def test_guidance_names_three_signs_keeps_the_link_and_carries_no_flagged_text(self):
        """#161 AC: объяснение не должно содержать того, что фильтр забраковал."""
        from app.session import safeguard_guidance, safeguard_request_id

        text = safeguard_guidance(safeguard_request_id(self.VERBATIM), "/tmp/dump.txt")
        assert "https://claude.com/form/cyber-use-case" in text
        assert "СВОЯ" in text
        assert "убедиться / проверить" in text
        assert "инструкция к действию" in text
        assert "Смена Claude-модели не поможет" in text
        assert "req_011CdnzxjQByYxoRQweVSmGK" in text
        assert "/tmp/dump.txt" in text
        # Ни маркера, ни дословной цитаты — иначе объяснение само становится ядом.
        assert "safeguards flagged" not in text.lower()
        assert "Try rephrasing" not in text
        assert self.VERBATIM not in text

    def test_text_event_raises_the_flag(self, session):
        from app.events import AgentEvent

        session._log = lambda *a, **k: None
        session._handle_event(AgentEvent("text", self.VERBATIM))

        assert session._safeguard_refusal == self.VERBATIM

    @pytest.mark.asyncio
    async def test_turn_end_rewinds_and_reports(self, session, monkeypatch):
        from app.events import AgentEvent

        logs = []
        spawned = []
        session._spawn_bg = lambda coro: (spawned.append(coro.cr_code.co_name),
                                          coro.close())[0]
        session._log = lambda kind, content, **_kw: logs.append((kind, content))
        session._safeguard_refusal = self.VERBATIM
        monkeypatch.setattr(
            "app.session_turns._rewind_past_safeguard_refusal", lambda _s: "4"
        )

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={"ok": False, "stop_reason": "refusal", "num_turns": 1,
                      "errors": ["invalid_request"], "model_error": "invalid_request"},
        ))

        assert any("отрезан: 4" in c for _, c in logs), logs
        assert any("cyber-use-case" in c for _, c in logs)
        assert session._safeguard_refusal == ""
        # Без разрыва живого клиента CLI откат остался бы записью в журнале.
        assert "_disconnect_backend" in spawned, spawned

    @pytest.mark.asyncio
    async def test_failed_rewind_is_loud_not_silent(self, session, monkeypatch):
        from app.events import AgentEvent

        logs = []
        session._log = lambda kind, content, **_kw: logs.append((kind, content))
        session._safeguard_refusal = self.VERBATIM

        def _boom(_s):
            raise RuntimeError("transcript gone")

        monkeypatch.setattr("app.session_turns._rewind_past_safeguard_refusal", _boom)

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={"ok": False, "stop_reason": "refusal", "num_turns": 1,
                      "errors": ["invalid_request"], "model_error": "invalid_request"},
        ))

        assert any("нужна новая сессия" in c for kind, c in logs if kind == "error"), logs

    @pytest.mark.asyncio
    async def test_ordinary_failed_turn_does_not_rewind(self, session, monkeypatch):
        """Ложная классификация обычной ошибки дороже пропуска — проверяем прямо."""
        from app.events import AgentEvent

        called = []
        monkeypatch.setattr(
            "app.session_turns._rewind_past_safeguard_refusal",
            lambda _s: called.append(1) or "1",
        )
        session._log = lambda *a, **k: None

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={"ok": False, "stop_reason": "error", "num_turns": 1,
                      "errors": ["invalid_request"], "model_error": "invalid_request"},
        ))

        assert called == []

    def test_refusal_class_has_no_auto_retry_path(self):
        """Требование «не повторять» — фактом: ретраи заведены только под другие классы."""
        import inspect

        from app.session_turns import TurnManager

        source = inspect.getsource(TurnManager.handle_turn_end)
        assert 'model_error == "server_error"' in source
        assert "invalid_request" not in source.replace("safeguard", "")

    def test_agent_quoting_the_refusal_is_not_a_refusal(self):
        """#161 дефект 1: маркера мало — цитата стоит ВНУТРИ текста, отказ его открывает."""
        from app.session import _is_safeguard_refusal

        assert _is_safeguard_refusal(self.AGENT_QUOTING_IT) is False
        assert _is_safeguard_refusal(self.VERBATIM) is True

    def test_refusal_recognised_when_it_is_not_the_last_text(self, session):
        """Порядок событий непостоянен: сперва длинный обычный текст, отказ следом."""
        from app.events import AgentEvent

        session._log = lambda *a, **k: None
        session._handle_event(AgentEvent("text", self.AGENT_QUOTING_IT))
        assert session._safeguard_refusal == ""

        session._handle_event(AgentEvent("text", self.VERBATIM))
        assert session._safeguard_refusal == self.VERBATIM

        # …и обратный порядок: отказ первым, обычный текст следом не затирает флаг.
        session._safeguard_refusal = ""
        session._handle_event(AgentEvent("text", self.VERBATIM))
        session._handle_event(AgentEvent("text", self.AGENT_QUOTING_IT))
        assert session._safeguard_refusal == self.VERBATIM

    @pytest.mark.asyncio
    async def test_successful_turn_is_never_rewound(self, session, monkeypatch):
        """Живая регрессия 07.08 16:27:01: `end_turn` + цитата → историю резать нельзя."""
        from app.events import AgentEvent

        called = []
        monkeypatch.setattr("app.session_turns._rewind_past_safeguard_refusal",
                            lambda _s: called.append(1) or "1")
        session._log = lambda *a, **k: None
        session._safeguard_refusal = self.VERBATIM  # флаг стоит, но ход УСПЕШНЫЙ

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={"ok": True, "stop_reason": "end_turn", "num_turns": 8},
        ))

        assert called == []

    @pytest.mark.asyncio
    async def test_nothing_flagged_reaches_the_agent_after_rewind(self, session, monkeypatch):
        """#161 главный AC: после отката ни одна строка наружу не несёт забракованного текста."""
        from app.events import AgentEvent

        logs = []
        session._spawn_bg = lambda coro: coro.close()
        session._log = lambda kind, content, **_kw: logs.append((kind, content))
        session._safeguard_refusal = self.VERBATIM
        monkeypatch.setattr("app.session_turns._rewind_past_safeguard_refusal", lambda _s: "2")

        session._turns.handle_turn_end(AgentEvent(
            "turn_end",
            metadata={"ok": False, "stop_reason": "refusal", "num_turns": 1,
                      "errors": ["invalid_request"], "model_error": "invalid_request"},
        ))

        emitted = "\n".join(c for _, c in logs)
        assert "safeguards flagged" not in emitted.lower(), emitted
        assert "Try rephrasing" not in emitted
        assert self.VERBATIM not in emitted
        # Полезное при этом на месте: класс, признаки, Request ID, путь к сырому тексту.
        assert "req_011CdnzxjQByYxoRQweVSmGK" in emitted
        assert "safeguard-refusals" in emitted

    def test_raw_refusal_is_stored_outside_the_worktree(self, tmp_path, monkeypatch):
        """Хранилище, которое пишется само, не делит рабочее дерево с Git-lifecycle (#114)."""
        from pathlib import Path

        import app.session as session_mod

        monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
        path = session_mod.store_safeguard_refusal("probe", self.VERBATIM)

        assert ".local/state/orchestra/safeguard-refusals" in path
        assert Path(path).read_text(encoding="utf-8") == self.VERBATIM
        assert "docs/tasks" not in path


class TestWeeklyQuotaAdmission:
    @pytest.mark.asyncio
    async def test_idle_worker_is_blocked_before_log_status_or_backend(self, session):
        from app.quota_gate import QuotaGateError
        from app.session import AgentStatus

        session._admission_service = AsyncMock(return_value=_quota_decision("blocked"))
        session._ensure_backend = AsyncMock()
        session._log = MagicMock()

        with pytest.raises(QuotaGateError):
            await session.send("new work")

        session._ensure_backend.assert_not_awaited()
        session._log.assert_not_called()
        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_idle_available_worker_starts_exactly_one_backend_turn(self, session):
        backend = AsyncMock()
        backend.resume_failed = False
        session._admission_service = AsyncMock(return_value=_quota_decision())
        session._ensure_backend = AsyncMock(return_value=backend)

        await session.send("new work")

        session._admission_service.assert_awaited_once_with("claude-sonnet-5[1m]")
        backend.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_running_steering_never_reads_quota(self, session):
        from app.session import AgentStatus

        backend = AsyncMock()
        backend.resume_failed = False
        session.status = AgentStatus.RUNNING
        session._backend = backend
        session._ensure_backend = AsyncMock(return_value=backend)
        session._admission_service = AsyncMock(side_effect=AssertionError("quota read"))

        await session.send("steer current turn")

        session._admission_service.assert_not_awaited()
        backend.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_orchestrator_idle_turn_never_reads_quota(self, session):
        backend = AsyncMock()
        backend.resume_failed = False
        session.is_orchestrator = True
        session._admission_service = AsyncMock(side_effect=AssertionError("quota read"))
        session._ensure_backend = AsyncMock(return_value=backend)

        await session.send("root chat")

        session._admission_service.assert_not_awaited()
        backend.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_during_refresh_cancels_delayed_start(self, session):
        from app.session import AgentStatus

        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow(_model):
            entered.set()
            await release.wait()
            return _quota_decision()

        session._admission_service = slow
        session._ensure_backend = AsyncMock()
        task = asyncio.create_task(session.send("new work"))
        await entered.wait()

        await session.interrupt()
        release.set()

        with pytest.raises(RuntimeError, match="cancelled by stop"):
            await task
        session._ensure_backend.assert_not_awaited()
        assert session.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_model_change_during_refresh_rechecks_new_bucket(self, session):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def admission(model):
            calls.append(model)
            if len(calls) == 1:
                entered.set()
                await release.wait()
            return _quota_decision(model=model)

        backend = AsyncMock()
        backend.resume_failed = False
        session._admission_service = admission
        session._ensure_backend = AsyncMock(return_value=backend)
        task = asyncio.create_task(session.send("new work"))
        await entered.wait()
        session.model = "gpt-5.6-sol"
        session.backend_type = "codex"
        release.set()

        await task

        assert calls == ["claude-sonnet-5[1m]", "gpt-5.6-sol"]
        backend.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_decision_expiring_before_lock_reacquire_is_rechecked(self, session):
        first_ready = asyncio.Event()
        allow_return = asyncio.Event()
        calls = []

        async def admission(model):
            calls.append(model)
            if len(calls) == 1:
                first_ready.set()
                await allow_return.wait()
                return _quota_decision(model=model, valid_for=0.02)
            return _quota_decision("blocked", model=model)

        session._admission_service = admission
        session._ensure_backend = AsyncMock()
        await session._lifecycle_lock.acquire()
        task = asyncio.create_task(session.send("new work"))
        session._lifecycle_lock.release()
        await first_ready.wait()
        await session._lifecycle_lock.acquire()
        allow_return.set()
        await asyncio.sleep(0.03)
        session._lifecycle_lock.release()

        from app.quota_gate import QuotaGateError
        with pytest.raises(QuotaGateError):
            await task
        assert calls == ["claude-sonnet-5[1m]", "claude-sonnet-5[1m]"]
        session._ensure_backend.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internal_retry_and_auto_continue_are_new_gated_turns(
        self, session, monkeypatch,
    ):
        session._admission_service = AsyncMock(return_value=_quota_decision("blocked"))
        session._ensure_backend = AsyncMock()
        monkeypatch.setattr("app.session.asyncio.sleep", AsyncMock())

        await session._rate_limit_retry(0)
        await session._auto_continue()

        assert session._admission_service.await_count == 2
        session._ensure_backend.assert_not_awaited()


class TestQuotaGatedDeferredTurns:
    @pytest.mark.asyncio
    async def test_blocked_flush_retains_payload_and_notifies_once(self, session, monkeypatch):
        from app.session import AgentStatus

        session.status = AgentStatus.IDLE
        session._pending_messages = ["first\nbytes", "second bytes"]
        session._admission_service = AsyncMock(return_value=_quota_decision("blocked"))
        session._ensure_backend = AsyncMock()
        session.on_turn_blocked = AsyncMock()
        monkeypatch.setattr("app.session.asyncio.sleep", AsyncMock())

        await session._flush_pending()
        await session._flush_pending()

        assert session._pending_messages == ["first\nbytes", "second bytes"]
        assert session.status == AgentStatus.IDLE
        session._ensure_backend.assert_not_awaited()
        session.on_turn_blocked.assert_awaited_once()
        assert session.on_turn_blocked.await_args.args[2] == 2

    @pytest.mark.asyncio
    async def test_later_available_flush_delivers_once_and_clears_dedupe(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        backend = AsyncMock()
        backend.resume_failed = False
        session.status = AgentStatus.IDLE
        session._pending_messages = ["first", "second"]
        session._quota_block_notice_signature = "old refusal"
        session._admission_service = AsyncMock(return_value=_quota_decision())
        session._ensure_backend = AsyncMock(return_value=backend)
        monkeypatch.setattr("app.session.asyncio.sleep", AsyncMock())

        await session._flush_pending()

        backend.send.assert_awaited_once_with(
            "--- message 1/2 ---\nfirst\n--- message 2/2 ---\nsecond"
        )
        assert session._pending_messages == []
        assert session._quota_block_notice_signature == ""

    @pytest.mark.asyncio
    async def test_native_codex_compact_is_gated_before_backend(self, session):
        from app.quota_gate import QuotaGateError

        session.model = "gpt-5.6-sol"
        session.backend_type = "codex"
        session._admission_service = AsyncMock(return_value=_quota_decision(
            "blocked", model="gpt-5.6-sol",
        ))
        session._ensure_backend = AsyncMock()

        with pytest.raises(QuotaGateError):
            await session.compact()

        session._ensure_backend.assert_not_awaited()
        assert session._compacting is False

    @pytest.mark.asyncio
    async def test_claude_summary_is_gated_before_backend(self, session, monkeypatch):
        from app.quota_gate import QuotaGateError

        monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
        session._admission_service = AsyncMock(return_value=_quota_decision("blocked"))
        session._make_backend = MagicMock(side_effect=AssertionError("backend started"))

        with pytest.raises(QuotaGateError):
            await session.compact()

        session._make_backend.assert_not_called()
        assert session._compacting is False

    @pytest.mark.asyncio
    async def test_stop_interrupts_active_claude_summary_without_starting_ack(
        self, session, monkeypatch,
    ):
        from app.events import AgentEvent

        class BlockingSummaryBackend:
            def __init__(self):
                self.sent = asyncio.Event()
                self.release = asyncio.Event()
                self.interrupt_calls = 0

            async def connect(self):
                return None

            async def send(self, _message):
                self.sent.set()

            async def events(self):
                await self.release.wait()
                yield AgentEvent("text", "summary " + "x" * 260)
                yield AgentEvent("turn_end", metadata={"session_id": "stopped-summary"})

            async def interrupt(self):
                self.interrupt_calls += 1
                self.release.set()
                return True

            async def disconnect(self):
                self.release.set()

        backend = BlockingSummaryBackend()
        monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
        session._admission_service = AsyncMock(return_value=_quota_decision())
        session._make_backend = MagicMock(return_value=backend)

        compact_task = asyncio.create_task(session.compact())
        await backend.sent.wait()
        await asyncio.wait_for(session.interrupt(), timeout=1)
        result = await asyncio.wait_for(compact_task, timeout=1)

        assert result["ok"] is False
        assert result["error"] == "compaction cancelled by stop"
        assert backend.interrupt_calls == 1
        assert session._admission_service.await_count == 1
        assert session._compacting is False

    @pytest.mark.asyncio
    async def test_ack_quota_cross_retains_summary_then_later_commits_once(
        self, session, monkeypatch,
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus

        summary = "TASK STATE: retained compaction summary. " + "x" * 260

        class SummaryBackend:
            def __init__(self, session_id):
                self.session_id = session_id
                self.sent = []

            async def connect(self):
                return None

            async def send(self, message):
                self.sent.append(message)

            async def events(self):
                yield AgentEvent("text", summary)
                yield AgentEvent("turn_end", metadata={
                    "session_id": self.session_id,
                    "ok": True,
                    "stop_reason": "end_turn",
                    "num_turns": 1,
                })

            async def disconnect(self):
                return None

        first_summary = SummaryBackend("summary-one")
        second_summary = SummaryBackend("summary-two")
        ack_backend = AsyncMock()
        ack_backend.resume_failed = False

        async def ensure_ack(force_fresh=False):
            async def complete_ack():
                await asyncio.sleep(0)
                session.session_id = "committed-session"
                session.status = AgentStatus.IDLE
                session._compact_ack_event.set()

            asyncio.create_task(complete_ack())
            return ack_backend

        monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
        session.session_id = "old-session"
        session.session_id_history = []
        session._prompt_injected = True
        session._pending_messages = ["retained pending"]
        session._make_backend = MagicMock(side_effect=[first_summary, second_summary])
        session._ensure_backend = ensure_ack
        spawned = []

        def discard_background(coroutine):
            spawned.append(coroutine)
            coroutine.close()

        session._spawn_bg = discard_background
        session._admission_service = AsyncMock(side_effect=[
            _quota_decision(), _quota_decision("blocked"),
        ])

        deferred = await session.compact()

        assert deferred["phase"] == "ack_deferred"
        assert deferred["summary_retained"] is True
        assert session.last_summary == summary
        assert session.session_id == "old-session"
        assert session.session_id_history == []
        assert session._prompt_injected is True
        assert session._pending_messages == ["retained pending"]
        assert session._compacting is False
        assert spawned == []

        session._pending_messages = []
        session._admission_service = AsyncMock(side_effect=[
            _quota_decision(), _quota_decision(),
        ])
        completed = await session.compact()

        assert completed["ok"] is True
        assert session.session_id == "committed-session"
        assert [item["session_id"] for item in session.session_id_history] == ["old-session"]
        assert session._prompt_injected is False
        assert len(first_summary.sent) == 1
        assert len(second_summary.sent) == 1
        ack_backend.send.assert_awaited_once()
