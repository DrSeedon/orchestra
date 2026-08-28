"""TDD tests for session.py — AgentSession."""

import asyncio
import hashlib
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


class _OversizedResumeBackend(_MockBackend):
    def __init__(self, *, oversized: bool):
        from app.backend_codex import CodexOversizedRecordError

        super().__init__(
            connect_error=(
                CodexOversizedRecordError("oversized thread/resume response")
                if oversized else None
            ),
        )
        self.oversized_reader_failure = oversized
        self.has_owned_processes = False


def _quota_decision(state="available", model="claude-sonnet-5[1m]", *, valid_for=60):
    import time
    from app.quota_gate import QuotaDecision

    provider = "anthropic" if model.startswith("claude-") else "codex"
    return QuotaDecision(
        state=state,
        model=model,
        provider=provider,
        provider_label="Claude" if provider == "anthropic" else "Codex",
        lane="claude" if provider == "anthropic" else "sol",
        gated=True,
        utilization=97 if state == "blocked" else 1,
        progress=0.5,
        tolerance_pp=5.5,
        limit_pct=55.5,
        observed_at=time.time(),
        valid_until=time.time() + valid_for,
        reset_at=None,
        window_starts_at=None,
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
    @pytest.mark.parametrize("runtime_id", ("claude", "codex", "grok", "harness"))
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

    @pytest.mark.asyncio
    async def test_codex_oversized_resume_retries_fresh_once_with_log_handoff(
        self, session, monkeypatch,
    ):
        session.backend_type = "codex"
        session.model = "gpt-5.6-sol"
        session.session_id = "poisoned-thread"
        session.runtime_handoff = ""
        first = _OversizedResumeBackend(oversized=True)
        fresh = _OversizedResumeBackend(oversized=False)
        session._make_backend = MagicMock(side_effect=[first, fresh])
        session._refresh_skills = AsyncMock()
        session._refresh_codex_project_doc = AsyncMock()
        session._build_runtime_handoff = AsyncMock(return_value="bounded handoff")
        session._activate_backend_tasks = MagicMock()
        monkeypatch.setattr("app.manager.publish_backend_fds", MagicMock())

        backend = await session._ensure_backend(
            exclude_history_users=("current message",),
        )

        assert backend is fresh
        assert session._make_backend.call_count == 2
        assert session._make_backend.call_args_list[1].kwargs["force_fresh"] is True
        session._build_runtime_handoff.assert_awaited_once_with(
            exclude_user_messages=("current message",),
        )
        assert session.session_id is None
        assert session.runtime_handoff == "bounded handoff"
        assert session.session_id_history[-1]["session_id"] == "poisoned-thread"
        assert session.session_id_history[-1]["reason"] == "oversized_reader_failure"

    @pytest.mark.asyncio
    async def test_codex_oversized_resume_fallback_is_bounded_to_one_retry(
        self, session, monkeypatch,
    ):
        from app.backend_codex import CodexOversizedRecordError

        session.backend_type = "codex"
        session.model = "gpt-5.6-sol"
        session.session_id = "poisoned-thread"
        session._make_backend = MagicMock(side_effect=[
            _OversizedResumeBackend(oversized=True),
            _OversizedResumeBackend(oversized=True),
        ])
        session._refresh_skills = AsyncMock()
        session._refresh_codex_project_doc = AsyncMock()
        session._build_runtime_handoff = AsyncMock(return_value="bounded handoff")

        with pytest.raises(CodexOversizedRecordError):
            await session._ensure_backend(exclude_history_users=("queued",))

        assert session._make_backend.call_count == 2
        assert session.session_id is None
        assert session._pending_messages == ["queued"]

    @pytest.mark.asyncio
    async def test_active_codex_oversized_turn_retires_backend_before_next_send(
        self, session,
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus

        class TerminalBackend:
            oversized_reader_failure = True
            has_owned_processes = False
            session_id = "poisoned-thread"

            async def events(self):
                yield AgentEvent(
                    "turn_end",
                    metadata={
                        "ok": False,
                        "stop_reason": "process_exit_0",
                        "reader_failure": "oversized JSONL record",
                    },
                )

        backend = TerminalBackend()
        session.backend_type = "codex"
        session.model = "gpt-5.6-sol"
        session.session_id = "poisoned-thread"
        session.status = AgentStatus.RUNNING
        session._backend = backend
        session._build_runtime_handoff = AsyncMock(return_value="bounded handoff")
        session._handle_event = MagicMock(
            side_effect=lambda _event: setattr(session, "status", AgentStatus.IDLE)
        )

        await session._turn_event_loop()

        assert session._backend is None
        assert session.session_id is None
        assert session.runtime_handoff == "bounded handoff"
        assert session.session_id_history[-1]["reason"] == "oversized_reader_failure"

    @pytest.mark.asyncio
    async def test_codex_compact_timeout_log_names_exception_and_stage(self, session):
        session.backend_type = "codex"
        session._backend = SimpleNamespace(
            compact_context=AsyncMock(side_effect=TimeoutError(
                "Codex compact timed out after 120s while waiting for completion notification"
            )),
        )
        session._log = MagicMock()
        session._hibernate.schedule = MagicMock()

        result = await session._compact_codex_context()

        assert result["ok"] is False
        assert result["error"] == (
            "TimeoutError: Codex compact timed out after 120s while waiting for "
            "completion notification"
        )
        assert any(
            call.args[0] == "error"
            and "native Codex compact failed: TimeoutError:" in call.args[1]
            for call in session._log.call_args_list
        )


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
    async def test_codex_listener_without_active_turn_fails_idle_and_flushes_queue(
        self, session, monkeypatch,
    ):
        from app.session import AgentStatus

        class BrokenCodexBackend:
            active_turn_id = None

            async def events(self):
                if False:
                    yield None

        backend = BrokenCodexBackend()
        session.backend_type = "codex"
        session._backend = backend
        session.status = AgentStatus.RUNNING
        session._pending_messages = ["queued after reader failure"]
        session._log = lambda *_args, **_kwargs: None
        session._flush_pending = AsyncMock()
        session._hibernate.schedule = MagicMock()
        monkeypatch.setattr("app.bg_jobs.bg_manager", None)

        await session._persistent_event_loop()
        await asyncio.sleep(0)

        assert session.status == AgentStatus.IDLE
        session._flush_pending.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_imported_claude_listener_reconnect_refreshes_history_from_logs(
        self, session, monkeypatch, tmp_path,
    ):
        from app import db as dbmod
        from app.events import AgentEvent
        from app.runtime_history import CLAUDE_HISTORY_SOURCE
        from app.session import AgentStatus

        db_path = tmp_path / "listener-reconnect.db"
        monkeypatch.setattr(dbmod, "DB_PATH", db_path)
        dbmod.init_db()
        session.model = "claude-sonnet-5[1m]"
        session.backend_type = "claude"
        session.session_id = "11111111-2222-4333-8444-555555555555"
        session.history_import_source = CLAUDE_HISTORY_SOURCE
        dbmod.save_session(session._to_db_dict())
        dbmod.add_log(
            session.id,
            datetime.now(timezone.utc),
            "user_message",
            "initial durable message",
        )
        initial = await session._build_claude_history_import(
            session.session_id,
            session.model,
        )

        class ReconnectingBackend:
            def __init__(self):
                self.event_calls = 0
                self.history = initial
                self.sent = []

            async def events(self):
                self.event_calls += 1
                if self.event_calls == 1:
                    raise RuntimeError("stream dropped")
                yield AgentEvent("turn_end", metadata={
                    "ok": True,
                    "stop_reason": "end_turn",
                    "num_turns": 1,
                })

            def replace_history_import(self, history):
                self.history = history

            async def reconnect(self):
                return None

            async def send(self, message):
                self.sent.append(message)

        dbmod.add_log(
            session.id,
            datetime.now(timezone.utc),
            "text",
            "answer added after first connect",
        )
        backend = ReconnectingBackend()
        session._backend = backend
        session.status = AgentStatus.RUNNING
        session._log = lambda *_args, **_kwargs: None
        session._admission_service = AsyncMock(
            side_effect=AssertionError("reconnect read quota")
        )
        monkeypatch.setattr("app.bg_jobs.bg_manager", None)

        await session._persistent_event_loop()

        assert backend.history.report.snapshot_id > initial.report.snapshot_id
        assert "answer added after first connect" in repr(backend.history.entries)
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
async def test_auto_report_skips_exact_silent_marker(monkeypatch):
    s = _mk_session(monkeypatch)
    s.on_idle = AsyncMock()
    s.last_task_sender = "parent"
    s._turn_logs = ["[[ORCHESTRA:SILENT_TURN]]"]
    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"

    s._turns.fire_auto_report()
    await asyncio.sleep(0)

    s.on_idle.assert_not_awaited()
    assert s._auto_report_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        " [[ORCHESTRA:SILENT_TURN]]",
        "[[ORCHESTRA:SILENT_TURN]] ",
        "prefix [[ORCHESTRA:SILENT_TURN]]",
        "[[ORCHESTRA:SILENT_TURN]] suffix",
    ],
)
async def test_auto_report_keeps_silent_marker_near_misses(monkeypatch, content):
    s = _mk_session(monkeypatch)
    fired = []

    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append(texts)

    s.on_idle = on_idle
    s.last_task_sender = "parent"
    s._turn_logs = [content]
    s._last_text_output = content

    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)

    assert fired == [[content]]


@pytest.mark.asyncio
async def test_failed_turn_with_silent_marker_is_reported(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []

    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append((texts, turn_ok))

    s.on_idle = on_idle
    s.last_task_sender = "parent"
    s._last_turn_ok = False
    s._turn_logs = ["[[ORCHESTRA:SILENT_TURN]]"]
    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"

    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)

    assert fired == [(["[[ORCHESTRA:SILENT_TURN]]"], False)]


@pytest.mark.asyncio
async def test_unparented_silent_marker_does_not_wake_anyone(monkeypatch):
    s = _mk_session(monkeypatch)
    s.on_idle = AsyncMock()
    s.parent_name = ""
    s.last_task_sender = ""
    s._turn_logs = ["[[ORCHESTRA:SILENT_TURN]]"]
    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"

    s._turns.fire_auto_report()
    await asyncio.sleep(0)

    s.on_idle.assert_not_awaited()
    assert s._auto_report_task is None


@pytest.mark.asyncio
async def test_auto_report_ignores_tool_logs_before_exact_final_marker(monkeypatch):
    s = _mk_session(monkeypatch)
    s.on_idle = AsyncMock()
    s.last_task_sender = "parent"
    s._turn_logs = ["[tool] inspect", "[[ORCHESTRA:SILENT_TURN]]"]
    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"

    s._turns.fire_auto_report()
    await asyncio.sleep(0)

    s.on_idle.assert_not_awaited()
    assert s._auto_report_task is None


@pytest.mark.asyncio
async def test_auto_report_uses_typed_final_text_after_tool_event(monkeypatch):
    from app.events import AgentEvent

    s = _mk_session(monkeypatch)
    s.on_idle = AsyncMock()
    s.last_task_sender = "parent"
    s._log = lambda *args, **kwargs: None
    s._handle_event(AgentEvent("tool_use", "inspect"))
    s._handle_event(AgentEvent("text", "[[ORCHESTRA:SILENT_TURN]]"))

    s._turns.fire_auto_report()
    await asyncio.sleep(0)

    s.on_idle.assert_not_awaited()
    assert s._turn_logs == ["[tool] inspect", "[[ORCHESTRA:SILENT_TURN]]"]


@pytest.mark.asyncio
async def test_auto_report_reports_tool_logs_before_marker_variant(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []

    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append(texts)

    s.on_idle = on_idle
    s.last_task_sender = "parent"
    s._turn_logs = ["[tool] inspect", "[[ORCHESTRA:SILENT_TURN]] "]
    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]] "

    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)

    assert fired == [["[tool] inspect", "[[ORCHESTRA:SILENT_TURN]] "]]


@pytest.mark.asyncio
async def test_failed_turn_with_tool_logs_and_marker_is_reported(monkeypatch):
    s = _mk_session(monkeypatch)
    fired = []

    async def on_idle(name, scope, texts, stop_reason="", turn_ok=True):
        fired.append((texts, turn_ok))

    s.on_idle = on_idle
    s.last_task_sender = "parent"
    s._last_turn_ok = False
    s._turn_logs = ["[tool] inspect", "[[ORCHESTRA:SILENT_TURN]]"]
    s._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"

    s._turns.fire_auto_report()
    await asyncio.sleep(0.05)

    assert fired == [(["[tool] inspect", "[[ORCHESTRA:SILENT_TURN]]"], False)]


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

    def _merged_servers(self, **kw):
        """Слитый набор MCP-серверов — из ФАЙЛА конфига, куда он уезжает с #224.

        Носитель сменился: `options.mcp_servers` теперь ПУТЬ, а не словарь, потому что dict
        SDK сериализует прямо в argv, а `/proc/<pid>/cmdline` читает процесс любого uid.
        Проверяемое свойство осталось прежним — порядок слияния user < scope < instance.
        """
        import json
        import stat
        from pathlib import Path

        value = self._opts(**kw).mcp_servers
        assert isinstance(value, (str, Path)), (
            f"ожидался путь к файлу конфига, получен {type(value).__name__} — "
            "значения секретов снова уедут в argv"
        )
        path = Path(value)
        assert path.is_file(), f"файл конфига не создан: {path}"
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"права {oct(mode)}, ожидалось 0o600"
        return json.loads(path.read_text())["mcpServers"]

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
        servers = self._merged_servers(user_mcp_servers={"foo": {"command": "x"}})
        assert "foo" in servers
        assert servers["foo"]["command"] == "x"

    def test_f2_orchestra_not_overridden_by_user(self):
        # user-MCP — базовый слой; серверный orchestra (в mcp_servers) выигрывает.
        servers = self._merged_servers(
            user_mcp_servers={"orchestra": {"command": "USER"}},
            mcp_servers={"orchestra": {"command": "SERVER"}},
        )
        assert servers["orchestra"]["command"] == "SERVER"

    def test_f2_user_and_server_coexist(self):
        servers = self._merged_servers(
            user_mcp_servers={"foo": {"command": "f"}},
            mcp_servers={"orchestra": {"command": "o"}},
        )
        assert "foo" in servers
        assert "orchestra" in servers
        assert servers["foo"]["command"] == "f"
        assert servers["orchestra"]["command"] == "o"


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

    @pytest.mark.parametrize("backend", ["claude", "codex", "grok", "harness"])
    @pytest.mark.parametrize("is_orchestrator", [False, True])
    def test_critical_99_compacts_immediately_for_every_runtime_and_role(
        self, session, monkeypatch, backend, is_orchestrator,
    ):
        logs = []
        spawned = []
        session.backend_type = backend
        session._is_orchestrator = is_orchestrator
        session._compacting = False
        session._schedule_precompact_timer = MagicMock()
        session._cancel_precompact_timer = MagicMock()
        session._auto_compact_window_state = MagicMock(side_effect=AssertionError)
        session._auto_compact = MagicMock()
        session._log = lambda kind, content, **_kw: logs.append((kind, content))
        monkeypatch.setenv("AUTO_COMPACT_ENABLED", "0")

        async def immediate_compact():
            return None

        session._auto_compact.return_value = immediate_compact()

        def capture(coro):
            spawned.append(coro)
            coro.close()

        session._spawn_bg = capture
        session._turns.schedule_context_compaction(99)

        session._schedule_precompact_timer.assert_not_called()
        session._cancel_precompact_timer.assert_called_once_with("critical_context")
        session._auto_compact.assert_called_once_with(delay_seconds=0)
        assert len(spawned) == 1
        assert any(
            kind == "status" and "critical auto-compact triggered (99%)" in content
            for kind, content in logs
        )
        session._auto_compact_window_state.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("backend", ["claude", "codex", "grok", "harness"])
    async def test_already_armed_timer_at_99_bypasses_window_and_kill_switch(
        self, session, monkeypatch, backend,
    ):
        from app.session import AgentStatus

        logs = []
        session.backend_type = backend
        session._is_orchestrator = True
        session.status = AgentStatus.IDLE
        session._last_context = {"percentage": 99, "known": True}
        session._log = lambda kind, content, **_kw: logs.append((kind, content))
        session.compact = AsyncMock(return_value={"ok": True})
        session._auto_compact_window_state = MagicMock(side_effect=AssertionError)
        session._precompact_timer = {
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "backend": backend,
            "context_threshold": 20 if backend == "claude" else 60,
        }
        monkeypatch.setenv("AUTO_COMPACT_ENABLED", "0")
        monkeypatch.setattr(
            "app.bg_jobs.bg_manager",
            MagicMock(has_active_jobs=lambda *_: False),
        )

        await session._fire_precompact_timer()

        session.compact.assert_awaited_once_with()
        session._auto_compact_window_state.assert_not_called()
        assert any(
            kind == "status" and "critical auto-compact firing (99%)" in content
            for kind, content in logs
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("backend", ["grok", "harness"])
    async def test_non_claude_critical_compact_ignores_claude_subscription_limit(
        self, session, monkeypatch, backend,
    ):
        from app.session import AgentStatus

        session.backend_type = backend
        session.status = AgentStatus.IDLE
        session._compacting = False
        session._compaction_permit = AsyncMock(
            side_effect=RuntimeError("non-claude permit marker")
        )
        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active", lambda: True,
        )

        result = await session.compact()

        assert result == {"ok": False, "error": "non-claude permit marker"}
        session._compaction_permit.assert_awaited_once_with(reserve=True)

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

    @pytest.mark.asyncio
    async def test_codex_turn_end_uses_only_codex_quota_windows(
        self, session, monkeypatch,
    ):
        from app.events import AgentEvent
        from app.routes import system

        sampled_at = 2_000_000_000.0
        monkeypatch.setattr(system, "_usage_cache", {
            "data": {
                "five_hour": {"utilization": 88},
                "seven_day": {"utilization": 100},
            },
            "ts": sampled_at,
            "token": None,
        })
        monkeypatch.setattr(system, "_codex_usage_cache", {
            "data": {
                "primary": {"utilization": 33, "window_minutes": 300},
                "secondary": {"utilization": 44, "window_minutes": 10080},
            },
            "ts": sampled_at,
        })
        monkeypatch.setattr("app.session_turns.time.time", lambda: sampled_at + 1)
        logs = []
        session.backend_type = "codex"
        session.model = "gpt-5.6-sol"
        session._log = lambda kind, content, **_kwargs: logs.append((kind, content))
        session._spawn_bg = lambda coro: coro.close()
        session._hibernate.schedule = MagicMock()

        session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
            "ok": True, "stop_reason": "end_turn", "num_turns": 1,
        }))
        await session._drain_persist()

        ended = next(content for kind, content in logs if kind == "status" and "turn ended" in content)
        assert "5h:" not in ended
        assert "7d:" not in ended
        assert "88%" not in ended
        assert "100%" not in ended

    @pytest.mark.asyncio
    async def test_turn_end_persists_and_logs_one_selected_quota_snapshot(
        self, session, monkeypatch,
    ):
        from app.events import AgentEvent

        snapshot = {
            "state": {
                "quota_five_hour_pct": None,
                "quota_seven_day_pct": None,
                "quota_primary_pct": 33,
                "quota_sampled_at": "2033-05-18T03:33:20+00:00",
            },
            "display": (("Codex 5h", {"utilization": 33}),),
        }
        selected = MagicMock(return_value=snapshot)
        add_usage = MagicMock(return_value=True)
        monkeypatch.setattr("app.session_turns._cached_quota_snapshot", selected)
        monkeypatch.setattr("app.session_turns.turn_usage_add", add_usage)
        logs = []
        session.backend_type = "codex"
        session.model = "gpt-5.6-sol"
        session._log = lambda kind, content, **_kwargs: logs.append((kind, content))
        session._spawn_bg = lambda coro: coro.close()
        session._hibernate.schedule = MagicMock()

        session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
            "event_id": "quota-snapshot-turn",
            "ok": True, "stop_reason": "end_turn", "num_turns": 1,
        }))
        if session._log_futures:
            await asyncio.gather(*tuple(session._log_futures), return_exceptions=True)
        await session._drain_persist()

        selected.assert_called_once_with("codex", "gpt-5.6-sol")
        assert add_usage.call_args.kwargs["quota_primary_pct"] == 33
        ended = next(content for kind, content in logs if kind == "status" and "turn ended" in content)
        assert "5h:" not in ended
        assert "7d:" not in ended

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
            "app.session_turns._cached_quota_snapshot",
            lambda runtime, model: {
                "state": {
                    "quota_five_hour_pct": 12.5,
                    "quota_seven_day_pct": 41,
                    "quota_primary_pct": None,
                    "quota_sampled_at": "2026-07-29T08:00:00+00:00",
                },
                "display": (),
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

    @pytest.mark.asyncio
    async def test_prompt_reinjection_reads_worktree_memory_not_parent_copy(
        self, session, monkeypatch, tmp_path
    ):
        from app.events import AgentEvent
        from app.session import AgentStatus

        parent_scope = tmp_path / "parent"
        worktree = tmp_path / "subrepo-worktree"
        for root, content in (
            (parent_scope, "STALE: copied into parent scope"),
            (worktree, "FRESH: canonical worktree memory"),
        ):
            memory_dir = root / "docs" / "workers"
            memory_dir.mkdir(parents=True)
            (memory_dir / f"{session.name}.md").write_text(content)

        session.scope = str(parent_scope)
        session.worktree_path = str(worktree)
        session.role = "worker"
        session.session_id = "resumed-session"
        session._prompt_injected = False
        session.prompt_overlay = None
        session._current_prompt = (
            "ROLE: worker.\n\n<worker-memory>\nOLD\n</worker-memory>"
        )

        sent = []
        resumed = AsyncMock()
        resumed.send = AsyncMock(side_effect=lambda message: sent.append(message))

        async def events():
            yield AgentEvent(
                type="turn_end", content="",
                metadata={"ok": True, "session_id": "resumed-session"},
            )

        resumed.events = lambda: events()
        session._backend = resumed
        session.status = AgentStatus.IDLE
        session._log = MagicMock()
        session._persist = MagicMock()
        monkeypatch.setattr("app.session.get_logs", lambda *_a, **_kw: [])

        with patch.object(session, "_ensure_backend", AsyncMock(return_value=resumed)):
            await session.send("next task")

        assert "FRESH: canonical worktree memory" in sent[0]
        assert "STALE: copied into parent scope" not in sent[0]


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
        backend.active_turn_id = None
        backend.context_usage = AsyncMock(return_value=None)
        session._backend = backend

        async def ensure_backend(*, force_fresh):
            session._backend = backend
            session._listen_task = asyncio.create_task(session._persistent_event_loop())
            return backend

        ensure_backend = AsyncMock(side_effect=ensure_backend)
        session._ensure_backend = ensure_backend
        monkeypatch.setattr(
            "app.session._claude_subscription_limit_active", lambda: False
        )
        await session.compact()
        ensure_backend.assert_awaited_once_with(force_fresh=True)
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


class TestManifestEffortAtTurnBoundary:
    """#214: эффорт перечитывается из манифеста на границе КАЖДОГО хода.

    Правка `pipeline.yaml` при живом сервере доезжает до уже работающих агентов на их
    следующем ходе — без рестарта, без `UPDATE` в БД и без обрыва текущего хода.
    Файл манифеста в тестах правится НА ДИСКЕ: кэш инвалидируется по mtime, поэтому
    подмена кеша изнутри доказывала бы не тот механизм.
    """

    @pytest.fixture
    def manifest(self, tmp_path, monkeypatch):
        """Реальный манифест на диске + writer, меняющий значение эффорта."""
        import app.pipeline as P
        root = tmp_path / "pipelines"
        (root / "eff").mkdir(parents=True)
        monkeypatch.setattr(P, "PIPELINES_DIR", root)
        P.load_pipeline.cache_clear()
        path = root / "eff" / "pipeline.yaml"

        def write(body: str):
            path.write_text(body)
            # mtime_ns различает правки внутри одной секунды, но одинаковое содержимое
            # с тем же mtime кэш обязан переиспользовать — поэтому пишем как есть.
            return path

        write(
            "name: eff\n"
            "roles:\n"
            "  hand: {kind: worker, label: Hand, "
            "effort: {\"claude-sonnet-5[1m]\": medium, gpt-5.6-sol: xhigh, default: low}}\n"
        )
        yield write
        P.load_pipeline.cache_clear()

    def _session(self, effort="medium", role="hand", model="claude-sonnet-5[1m]"):
        from app.session import AgentSession
        s = AgentSession(
            id="eff-001", name="w-eff", scope="/test", cwd="/tmp",
            model=model, system_prompt="test", pipeline="eff", role=role,
            effort=effort, created_at=datetime.now(timezone.utc),
        )
        s._admission_service = AsyncMock(return_value=_quota_decision())
        return s

    async def _turn(self, session, backend, message):
        send_task = asyncio.create_task(session.send(message))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if backend.sent and message in backend.sent[-1]:
                break
        backend.finish()
        await send_task
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_unchanged_manifest_rebuilds_nothing(self, mock_db, manifest):
        """Требование: одинаковое значение → ноль дисконнектов, ноль пересборок."""
        session = self._session(effort="medium")
        backend = _MockBackend()
        builds = 0

        def build(*a, **kw):
            nonlocal builds
            builds += 1
            return backend

        disconnects = 0
        orig_disconnect = session._disconnect_backend

        async def counting_disconnect():
            nonlocal disconnects
            disconnects += 1
            await orig_disconnect()

        session._disconnect_backend = counting_disconnect
        with patch.object(session, "_make_backend", side_effect=build):
            await self._turn(session, backend, "first")
            await self._turn(session, backend, "second")

        assert session.effort == "medium"
        assert disconnects == 0
        assert builds == 1  # бэкенд собран один раз на два хода

    @pytest.mark.asyncio
    async def test_manifest_edit_applies_on_next_turn(self, mock_db, manifest):
        """Правка файла между ходами → следующий ход идёт на новом эффорте."""
        session = self._session(effort="medium")
        backend = _MockBackend()
        builds = 0

        def build(*a, **kw):
            nonlocal builds
            builds += 1
            return backend

        with patch.object(session, "_make_backend", side_effect=build):
            await self._turn(session, backend, "first")
            assert session.effort == "medium" and builds == 1

            manifest(
                "name: eff\n"
                "roles:\n"
                "  hand: {kind: worker, label: Hand, "
                "effort: {\"claude-sonnet-5[1m]\": high, default: low}}\n"
            )

            await self._turn(session, backend, "second")

        assert session.effort == "high"
        assert builds == 2  # бэкенд пересобран → новое значение уехало в рантайм

    @pytest.mark.asyncio
    async def test_running_turn_is_not_interrupted(self, mock_db, manifest):
        """Требование юзера: значение принимается, но живой ход не прерывается."""
        session = self._session(effort="medium")
        backend = _MockBackend()
        disconnects = 0
        orig_disconnect = session._disconnect_backend

        async def counting_disconnect():
            nonlocal disconnects
            disconnects += 1
            await orig_disconnect()

        session._disconnect_backend = counting_disconnect
        with patch.object(session, "_make_backend", return_value=backend):
            from app.session import AgentStatus
            send_task = asyncio.create_task(session.send("first"))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if session.status == AgentStatus.RUNNING:
                    break
            assert session.status == AgentStatus.RUNNING

            manifest(
                "name: eff\n"
                "roles:\n"
                "  hand: {kind: worker, label: Hand, "
                "effort: {\"claude-sonnet-5[1m]\": high, default: low}}\n"
            )
            # сообщение в живой ход: инжект, а не смена эффорта и не дисконнект
            await session.send("steer")
            assert session.effort == "medium"
            assert disconnects == 0

            backend.finish()
            await send_task
            await asyncio.sleep(0.05)

            # ход закончился — новое значение вступает в силу со следующего
            await self._turn(session, backend, "second")

        assert session.effort == "high"

    @pytest.mark.asyncio
    async def test_broken_manifest_keeps_current_effort(self, mock_db, manifest):
        """Требование: отказ тихий и безопасный — битый yaml ничего не пересобирает."""
        session = self._session(effort="medium")
        backend = _MockBackend()
        disconnects = 0
        orig_disconnect = session._disconnect_backend

        async def counting_disconnect():
            nonlocal disconnects
            disconnects += 1
            await orig_disconnect()

        session._disconnect_backend = counting_disconnect
        manifest("name: eff\nroles: {hand: {kind: worker, label: Hand, bogus_field: 1}}\n")
        with patch.object(session, "_make_backend", return_value=backend):
            await self._turn(session, backend, "first")

        assert session.effort == "medium"
        assert disconnects == 0

    @pytest.mark.asyncio
    async def test_typo_in_level_keeps_live_agent_on_current_effort(self, mock_db, manifest):
        """Отказ манифеста по опечатке в ступени НЕ трогает живого агента.

        Манифест с неизвестной ступенью теперь отвергается целиком (fail-closed), и цена
        этого — падающий спавн. Живые агенты платить не должны: сбой резолва оставляет
        текущее значение и не пересобирает бэкенд. Проверяем именно ветку `raise`, а не
        только ветку с warning.
        """
        session = self._session(effort="medium")
        backend = _MockBackend()
        disconnects = 0
        orig_disconnect = session._disconnect_backend

        async def counting_disconnect():
            nonlocal disconnects
            disconnects += 1
            await orig_disconnect()

        session._disconnect_backend = counting_disconnect
        manifest(
            "name: eff\nroles:\n  hand: {kind: worker, label: Hand, "
            "effort: {\"claude-sonnet-5[1m]\": hgih, default: high}}\n"
        )
        with patch.object(session, "_make_backend", return_value=backend):
            await self._turn(session, backend, "first")

        assert session.effort == "medium"  # не сползли на default: high
        assert disconnects == 0

    @pytest.mark.asyncio
    async def test_role_without_effort_keeps_db_value(self, mock_db, manifest):
        """Роль без эффорта → остаёмся на значении из БД, а не обнуляем его."""
        session = self._session(effort="medium")
        backend = _MockBackend()
        manifest("name: eff\nroles: {hand: {kind: worker, label: Hand}}\n")
        with patch.object(session, "_make_backend", return_value=backend):
            await self._turn(session, backend, "first")
        assert session.effort == "medium"

    @pytest.mark.asyncio
    async def test_legacy_session_without_role_is_untouched(self, mock_db, manifest):
        """Legacy-сессия (role='') манифеста не имеет — живёт на значении из БД."""
        session = self._session(effort="xhigh", role="")
        backend = _MockBackend()
        with patch.object(session, "_make_backend", return_value=backend):
            await self._turn(session, backend, "first")
        assert session.effort == "xhigh"

    @pytest.mark.asyncio
    async def test_failed_disconnect_leaves_change_pending(self, mock_db, manifest):
        """Сбой дисконнекта НЕ должен съедать смену: следующий ход обязан повторить.

        Порядок «зафиксировать значение → дисконнект» делает такой сбой невосстановимым:
        расхождения с манифестом больше нет, повторять нечего, и агент навсегда остаётся
        на бэкенде со старой ступенью. Поэтому дисконнект идёт ПЕРВЫМ.
        """
        session = self._session(effort="medium")
        backend = _MockBackend()
        manifest(
            "name: eff\nroles:\n  hand: {kind: worker, label: Hand, "
            "effort: {\"claude-sonnet-5[1m]\": high, default: low}}\n"
        )
        attempts = 0
        orig_disconnect = session._disconnect_backend

        async def flaky_disconnect():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("disconnect failed")
            await orig_disconnect()

        session._disconnect_backend = flaky_disconnect
        with patch.object(session, "_make_backend", return_value=backend):
            with pytest.raises(RuntimeError):
                await session._apply_manifest_effort()
            assert session.effort == "medium"  # не зафиксировано — расхождение живо

            assert await session._apply_manifest_effort() is True
        assert session.effort == "high"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_effort_follows_model_switch_without_manifest_edit(self, mock_db, manifest):
        """Тот же манифест, другая модель сессии → другая ступень (ключ — модель)."""
        session = self._session(effort="medium", model="gpt-5.6-sol")
        session.backend_type = "codex"
        backend = _MockBackend()
        with patch.object(session, "_make_backend", return_value=backend):
            await self._turn(session, backend, "first")
        assert session.effort == "xhigh"


class TestEnsureBackendForceFresh:
    @pytest.mark.asyncio
    async def test_codex_preflights_finish_before_backend_is_built_and_connected(
        self, session,
    ):
        order = []
        backend = SimpleNamespace(
            connect=AsyncMock(side_effect=lambda: order.append("connect")),
            has_owned_processes=False,
        )
        session.backend_type = "codex"
        session._refresh_skills = AsyncMock(side_effect=lambda: order.append("skills"))
        session._refresh_codex_project_doc = AsyncMock(
            side_effect=lambda: order.append("project-doc"),
        )
        session._make_backend = MagicMock(
            side_effect=lambda **_kwargs: order.append("build") or backend,
        )
        session._hibernate.heartbeat_loop = AsyncMock()

        with patch(
            "app.workspace.sync_agents_md",
            side_effect=lambda path: order.append(("agents", path)),
        ) as sync_agents:
            result = await session._ensure_backend()

        assert result is backend
        sync_agents.assert_called_once_with(session.cwd)
        assert order == [
            ("agents", session.cwd), "skills", "project-doc", "build", "connect",
        ]

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
    async def test_codex_connect_failure_clears_running_status(self, session):
        from app.session import AgentStatus

        backend = SimpleNamespace(
            connect=AsyncMock(side_effect=RuntimeError("app-server exited 0")),
            has_owned_processes=False,
        )
        session.backend_type = "codex"
        session.status = AgentStatus.RUNNING
        session._log = MagicMock()
        session._refresh_skills = AsyncMock()
        session._refresh_codex_project_doc = AsyncMock()
        session._make_backend = MagicMock(return_value=backend)
        with patch("app.workspace.sync_agents_md"):
            with pytest.raises(RuntimeError, match="app-server exited 0"):
                await session._ensure_backend()

        assert session.status == AgentStatus.IDLE
        assert any(
            call.args and call.args[0] == "error"
            for call in session._log.call_args_list
        )

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
    async def test_codex_to_claude_uses_text_tail_without_fresh_or_target_canary(
            self, session, monkeypatch):
        from app.session import AgentStatus

        session.model = "gpt-5.6-sol"
        session.backend_type = "codex"
        session.session_id = "source-codex-thread"
        session.status = AgentStatus.IDLE
        source = AsyncMock()
        session._backend = source
        session._log = MagicMock()
        session._build_runtime_handoff = AsyncMock(
            return_value="User:\nlast question\n\nAssistant:\nlast answer",
        )
        session._prepare_runtime_handoff = AsyncMock(
            side_effect=AssertionError("text tail must bypass complex canary handoff"),
        )
        session._make_backend = MagicMock(
            side_effect=AssertionError("Opus starts lazily on the next user turn"),
        )
        save = MagicMock()
        monkeypatch.setattr("app.session.save_session", save)

        result = await session.change_model("claude-opus-5[1m]")

        assert result["ok"] is True
        assert result["runtime_changed"] is True
        assert result["native_session_reset"] is True
        assert result["history_transfer"] == {
            "mode": "text_tail_v1",
            "chars": 43,
            "max_user_messages": 10,
        }
        assert session.model == "claude-opus-5[1m]"
        assert session.backend_type == "claude"
        assert session.session_id == ""
        assert session.runtime_handoff.endswith("Assistant:\nlast answer")
        assert session.session_id_history[-1]["session_id"] == "source-codex-thread"
        assert session.session_id_history[-1]["handoff_mode"] == "text_tail_v1"
        assert session._backend is None
        source.disconnect.assert_awaited_once()
        session._prepare_runtime_handoff.assert_not_awaited()
        session._make_backend.assert_not_called()
        save.assert_called_once()

    @pytest.mark.asyncio
    async def test_text_tail_v1_keeps_last_ten_users_and_assistant_text_only(
            self, session, monkeypatch):
        rows = []
        row_id = 0
        for index in range(12):
            row_id += 1
            rows.append({
                "id": row_id,
                "ts": f"2026-08-25T00:{index:02d}:00+00:00",
                "type": "user_message",
                "content": f"user-{index}",
            })
            row_id += 1
            rows.append({
                "id": row_id,
                "ts": f"2026-08-25T00:{index:02d}:01+00:00",
                "type": "text",
                "content": f"assistant-{index}",
            })
            row_id += 1
            rows.append({
                "id": row_id,
                "ts": f"2026-08-25T00:{index:02d}:02+00:00",
                "type": "tool_result",
                "content": f"SECRET-TOOL-PAYLOAD-{index}",
            })
        rows.append({
            "id": row_id + 1,
            "ts": "2026-08-25T00:59:00+00:00",
            "type": "user_message",
            "content": "[Orchestra platform note: hidden]",
        })
        monkeypatch.setattr(
            "app.session.get_logs",
            lambda _session_id, **_kwargs: rows,
        )

        tail = await session._build_runtime_handoff()

        assert "User:\nuser-0\n" not in tail
        assert "User:\nuser-1\n" not in tail
        assert "Assistant:\nassistant-0\n" not in tail
        assert "Assistant:\nassistant-1\n" not in tail
        for index in range(2, 12):
            assert f"user-{index}" in tail
            assert f"assistant-{index}" in tail
        assert "SECRET-TOOL-PAYLOAD" not in tail
        assert "Orchestra platform note" not in tail
        assert len(tail) <= 64_000

    @pytest.mark.asyncio
    async def test_non_steering_runtime_queues_mid_turn_message(self, session):
        from app.session import AgentStatus

        backend = AsyncMock()
        backend.send = AsyncMock()
        session.backend_type = "grok"
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
    async def test_codex_cross_runtime_target_is_disabled_without_empty_tools_proof(
            self, session):
        from app.runtime_registry import get_runtime

        backend = AsyncMock()
        staged = SimpleNamespace(
            runtime="codex", backend=backend,
            configuration_sha256="b" * 64,
        )

        receipt = await session._run_handoff_ingress_canary(
            staged,
            packet={"schema_version": 1},
            expected_packet_sha256="a" * 64,
        )

        assert get_runtime("codex").capabilities.validated_handoff is False
        assert receipt["ok"] is False
        assert receipt["failure"]["kind"] == "capability_unsupported"
        backend.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fresh_model_switch_discards_source_context_without_handoff(
            self, session, monkeypatch):
        from app.session import AgentStatus

        session.model = "claude-opus-5[1m]"
        session.backend_type = "claude"
        session.session_id = "quota-exhausted-claude-session"
        session.status = AgentStatus.IDLE
        session.runtime_handoff = "old packet"
        session.history_import_source = "native_claude_jsonl"
        session.last_summary = "old summary"
        session._last_context = {
            "percentage": 38, "total_tokens": 98_192, "max_tokens": 258_400,
        }
        session._session_limit_hit = True
        source = AsyncMock()
        session._backend = source
        session._log = MagicMock()
        session._prepare_runtime_handoff = AsyncMock(
            side_effect=AssertionError("fresh switch must not build a handoff"),
        )
        session._make_backend = MagicMock(
            side_effect=AssertionError("target starts on the next user turn"),
        )
        save = MagicMock()
        monkeypatch.setattr("app.session.save_session", save)

        result = await session.change_model("gpt-5.6-sol", fresh=True)

        assert result["ok"] is True
        assert result["runtime_changed"] is True
        assert result["native_session_reset"] is True
        assert result["history_transfer"] == {
            "mode": "fresh", "previous_dialog_discarded": True,
        }
        assert session.model == "gpt-5.6-sol"
        assert session.backend_type == "codex"
        assert session.session_id == ""
        assert session.runtime_handoff == ""
        assert session.history_import_source is None
        assert session.last_summary == ""
        assert session._last_context == {
            "percentage": 0, "total_tokens": 0, "max_tokens": 0,
        }
        assert session._session_limit_hit is False
        assert session._backend is None
        assert session.session_id_history[-1]["session_id"] == (
            "quota-exhausted-claude-session"
        )
        source.disconnect.assert_awaited_once()
        session._prepare_runtime_handoff.assert_not_awaited()
        save.assert_called_once()

    @pytest.mark.asyncio
    async def test_codex_model_switch_preserves_native_thread(
            self, session, monkeypatch):
        from app.session import AgentStatus

        session.model = "gpt-5.5"
        session.backend_type = "codex"
        session.session_id = "codex-native-session"
        session.status = AgentStatus.IDLE
        source = SimpleNamespace(
            active_turn_id=None,
            _events_active=False,
            retarget_model=MagicMock(),
        )
        session._backend = source
        session._log = lambda *_args, **_kwargs: None
        session._last_context = {
            "percentage": 1, "total_tokens": 1_000, "max_tokens": 258_400,
        }
        session._prepare_runtime_handoff = AsyncMock(
            side_effect=AssertionError("same Codex thread needs no handoff"),
        )
        session._make_backend = MagicMock(
            side_effect=AssertionError("same Codex thread needs no replacement backend"),
        )
        save = MagicMock()
        monkeypatch.setattr("app.session.save_session", save)

        result = await session.change_model("gpt-5.6-sol")

        assert result["runtime_changed"] is False
        assert result["native_session_reset"] is False
        assert session.session_id == "codex-native-session"
        assert session.runtime_handoff == ""
        assert session.session_id_history == []
        assert session._backend is source
        assert session.model == "gpt-5.6-sol"
        assert result["history_transfer"] == {"mode": "native_in_place"}
        source.retarget_model.assert_called_once_with("gpt-5.6-sol")
        session._prepare_runtime_handoff.assert_not_awaited()
        session._make_backend.assert_not_called()
        save.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("runtime", "old_model", "new_model"), [
        ("claude", "claude-sonnet-5[1m]", "claude-opus-5[1m]"),
        ("grok", "grok-4.5", "grok-4.6"),
        ("harness", "nvidia/nemotron-3-ultra-550b-a55b:free", "z-ai/glm-5.2:free"),
    ])
    async def test_other_builtin_model_switches_retarget_in_place(
            self, session, monkeypatch, runtime, old_model, new_model):
        from app.session import AgentStatus

        session.model = old_model
        session.backend_type = runtime
        session.session_id = f"native-{runtime}-session"
        session.status = AgentStatus.IDLE
        source = SimpleNamespace(
            active_turn_id=None,
            _events_active=False,
            _turn_active=False,
            retarget_model=AsyncMock(),
        )
        session._backend = source
        session._log = MagicMock()
        session._last_context = {
            "percentage": 1, "total_tokens": 1_000, "max_tokens": 1_000_000,
        }
        session._prepare_runtime_handoff = AsyncMock(
            side_effect=AssertionError("same native session needs no handoff"),
        )
        session._make_backend = MagicMock(
            side_effect=AssertionError("same native session needs no replacement backend"),
        )
        save = MagicMock()
        monkeypatch.setattr("app.session.save_session", save)

        result = await session.change_model(new_model)

        assert result["ok"] is True
        assert result["runtime_changed"] is False
        assert result["native_session_reset"] is False
        assert result["history_transfer"] == {"mode": "native_in_place"}
        assert session.model == new_model
        assert session.session_id == f"native-{runtime}-session"
        assert session._backend is source
        source.retarget_model.assert_awaited_once_with(new_model)
        session._prepare_runtime_handoff.assert_not_awaited()
        session._make_backend.assert_not_called()
        save.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("runtime", "old_model", "new_model"), [
        ("claude", "claude-opus-5[1m]", "claude-haiku-4-5"),
        ("harness", "nvidia/nemotron-3-ultra-550b-a55b:free", "z-ai/glm-5.2:free"),
    ])
    async def test_in_place_switch_refuses_context_that_target_cannot_fit(
            self, session, monkeypatch, runtime, old_model, new_model):
        from app.session import AgentStatus

        session.model = old_model
        session.backend_type = runtime
        session.session_id = f"native-{runtime}-session"
        session.status = AgentStatus.IDLE
        session._last_context = {
            "percentage": 30,
            "total_tokens": 300_000,
            "max_tokens": 1_000_000,
        }
        source = SimpleNamespace(
            active_turn_id=None,
            _events_active=False,
            _turn_active=False,
            retarget_model=AsyncMock(),
        )
        session._backend = source
        save = MagicMock()
        monkeypatch.setattr("app.session.save_session", save)

        result = await session.change_model(new_model)

        assert result["ok"] is False
        assert result["error_code"] == "handoff_context_overflow"
        assert session.model == old_model
        assert session.session_id == f"native-{runtime}-session"
        source.retarget_model.assert_not_awaited()
        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_claude_same_runtime_retarget_failure_keeps_source(
            self, session, monkeypatch):
        from app.session import AgentStatus

        session.model = "claude-sonnet-5[1m]"
        session.backend_type = "claude"
        session.session_id = "claude-native-session"
        session.status = AgentStatus.IDLE
        session._last_context = {
            "percentage": 1, "total_tokens": 1_000, "max_tokens": 258_400,
        }
        source = SimpleNamespace(
            session_id="claude-native-session",
            active_turn_id=None,
            _events_active=False,
            _turn_active=False,
            retarget_model=AsyncMock(side_effect=RuntimeError("set_model failed")),
        )
        session._backend = source
        save = MagicMock()
        monkeypatch.setattr("app.session.save_session", save)

        result = await session.change_model("claude-opus-5[1m]")

        assert result["ok"] is False
        assert result["error_code"] == "claude_in_place_switch_failed"
        assert session.model == "claude-sonnet-5[1m]"
        assert session._backend is source
        assert session._handoff_recovery_required is False
        save.assert_not_called()
        source.retarget_model.assert_awaited_once_with("claude-opus-5[1m]")

    @pytest.mark.asyncio
    async def test_claude_same_runtime_persistence_failure_rolls_model_back(
            self, session, monkeypatch):
        from app.session import AgentStatus

        session.model = "claude-sonnet-5[1m]"
        session.backend_type = "claude"
        session.session_id = "claude-native-session"
        session.status = AgentStatus.IDLE
        session._last_context = {
            "percentage": 1, "total_tokens": 1_000, "max_tokens": 258_400,
        }
        source = SimpleNamespace(
            session_id="claude-native-session",
            active_turn_id=None,
            _events_active=False,
            _turn_active=False,
            retarget_model=AsyncMock(),
        )
        session._backend = source
        save = MagicMock(side_effect=RuntimeError("database unavailable"))
        monkeypatch.setattr("app.session.save_session", save)

        result = await session.change_model("claude-opus-5[1m]")

        assert result["ok"] is False
        assert result["error_code"] == "claude_in_place_switch_persistence_failed"
        assert session.model == "claude-sonnet-5[1m]"
        assert session._backend is source
        assert session._handoff_recovery_required is False
        assert source.retarget_model.await_args_list == [
            (("claude-opus-5[1m]",), {}),
            (("claude-sonnet-5[1m]",), {}),
        ]

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
    session,
):
    """Base64 tool results stay self-contained so the frontend can restore images."""
    from app.events import AgentEvent

    import base64

    session._log = MagicMock()
    image = base64.b64encode(bytes(range(256)) * 40).decode()
    payload = ("{'type': 'image', 'source': {'type': 'base64', 'data': '"
               + image + "', 'media_type': 'image/png'}}")

    session._handle_event(AgentEvent("tool_result", payload, {"tool_use_id": "t-1"}))
    if session._log_futures:
        await asyncio.gather(*tuple(session._log_futures), return_exceptions=True)

    assert session._log.call_args.args == ("tool_result", payload)


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

        summaries = [first_summary, second_summary]

        async def ensure_backend(force_fresh=False, activate=True):
            if not force_fresh:
                backend = summaries.pop(0)
                session._backend = backend
                return backend

            async def complete_ack():
                await asyncio.sleep(0)
                session.session_id = "committed-session"
                session.status = AgentStatus.IDLE
                session._compact_ack_event.set()

            asyncio.create_task(complete_ack())
            return ack_backend

        monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
        session.session_id = "old-session"
        session.history_import_source = "logs:claude"
        session.session_id_history = []
        session._prompt_injected = True
        session._pending_messages = ["retained pending"]
        session._make_backend = MagicMock()
        session._ensure_backend = ensure_backend
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
        assert session.history_import_source == "logs:claude"
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
        assert session.history_import_source is None
        assert len(first_summary.sent) == 1
        assert len(second_summary.sent) == 1
        session._make_backend.assert_not_called()
        ack_backend.send.assert_awaited_once()


def _history_for_switch(session_id, model="claude-sonnet-5[1m]"):
    from app.runtime_history import render_claude_history

    return render_claude_history(
        [{
            "id": 1,
            "ts": "2026-08-11T10:00:00+00:00",
            "type": "user_message",
            "content": "old fact",
        }],
        snapshot_id=1,
        session_id=session_id,
        cwd="/tmp",
        model=model,
    )


def _codex_history_for_switch(thread_id):
    from app.runtime_history import render_codex_history

    return render_codex_history(
        [{
            "id": 1,
            "ts": "2026-08-11T10:00:00+00:00",
            "type": "user_message",
            "content": "old fact",
        }],
        snapshot_id=1,
        thread_id=thread_id,
    )



@pytest.mark.asyncio
async def test_two_db_backed_claude_connects_render_identical_history(
    session, monkeypatch, tmp_path,
):
    from app import db as dbmod
    from app.runtime_history import CLAUDE_HISTORY_SOURCE

    session.session_id = "11111111-2222-4333-8444-555555555555"
    session.history_import_source = CLAUDE_HISTORY_SOURCE
    session.backend_type = "claude"
    db_path = tmp_path / "reconnect.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    dbmod.save_session(session._to_db_dict())
    dbmod.add_log(
        session.id,
        datetime.now(timezone.utc),
        "user_message",
        "same history",
    )
    dbmod.add_log(
        session.id,
        datetime.now(timezone.utc),
        "text",
        "same answer",
    )
    rendered = []

    class Backend:
        def __init__(self, history_import):
            self.session_id = history_import.session_id
            rendered.append(history_import)

        async def connect(self):
            return None

        async def disconnect(self):
            return None

    monkeypatch.setattr(
        session,
        "_make_backend",
        lambda force_fresh=False, history_import=None: Backend(history_import),
    )
    monkeypatch.setattr(session, "_refresh_skills", AsyncMock())
    monkeypatch.setattr(session, "_refresh_codex_project_doc", AsyncMock())
    session._activate_backend_tasks = MagicMock()

    await session._ensure_backend()
    await session._disconnect_backend()
    await session._ensure_backend()

    assert len(rendered) == 2
    assert rendered[0].entries == rendered[1].entries
    assert rendered[0].report == rendered[1].report


@pytest.mark.asyncio
async def test_tool_metadata_is_persisted_with_log(session, monkeypatch):
    from app.events import AgentEvent

    add_log = MagicMock(return_value=1)
    monkeypatch.setattr("app.session.add_log", add_log)
    monkeypatch.setattr("app.session.tool_error_add", MagicMock(return_value=True))

    session._handle_event(AgentEvent(
        "tool_use",
        "Read: path",
        {"tool_use_id": "tool-1", "tool_name": "Read"},
    ))
    session._handle_event(AgentEvent(
        "tool_result",
        "denied",
        {"tool_use_id": "tool-1", "is_error": True},
    ))
    await asyncio.gather(*tuple(session._log_futures))

    assert add_log.call_args_list[0].kwargs == {
        "tool_use_id": "tool-1",
        "tool_name": "Read",
        "tool_is_error": False,
    }
    assert add_log.call_args_list[1].kwargs == {
        "tool_use_id": "tool-1",
        "tool_name": "Read",
        "tool_is_error": True,
    }


@pytest.mark.asyncio
async def test_handoff_ingress_requires_terminal_turn_receipt(session, monkeypatch):
    from app.events import AgentEvent
    import app.session as sessionmod

    monkeypatch.setattr(
        sessionmod, "get_runtime",
        lambda _runtime: SimpleNamespace(
            capabilities=SimpleNamespace(validated_handoff=True),
        ),
    )

    class Backend:
        _validation_profile = True
        session_id = "target-session"

        async def connect(self):
            return None

        async def send(self, _message):
            return None

        async def events(self):
            yield AgentEvent("text", "ORCHESTRA_HANDOFF_ACK 1 " + "a" * 64)

    staged = SimpleNamespace(
        backend=Backend(), runtime="claude", configuration_sha256="b" * 64,
        session_id="target-session",
    )

    receipt = await session._run_handoff_ingress_canary(
        staged,
        packet={"schema_version": 1},
        expected_packet_sha256="a" * 64,
    )

    assert receipt["ok"] is False
    assert receipt["failure"] == {
        "kind": "ingress_incomplete", "structured": False,
    }


@pytest.mark.asyncio
async def test_handoff_ingress_rejects_tool_use_event(session, monkeypatch):
    from app.events import AgentEvent
    import app.session as sessionmod

    monkeypatch.setattr(
        sessionmod, "get_runtime",
        lambda _runtime: SimpleNamespace(
            capabilities=SimpleNamespace(validated_handoff=True),
        ),
    )

    class Backend:
        _validation_profile = True
        session_id = "target-session"

        async def connect(self):
            return None

        async def send(self, _message):
            return None

        async def events(self):
            yield AgentEvent("tool_use", "Bash: forbidden")
            yield AgentEvent("text", "ORCHESTRA_HANDOFF_ACK 1 " + "a" * 64)
            yield AgentEvent("turn_end", metadata={"ok": True})

    staged = SimpleNamespace(
        backend=Backend(), runtime="claude", configuration_sha256="b" * 64,
        session_id="target-session",
    )

    receipt = await session._run_handoff_ingress_canary(
        staged,
        packet={"schema_version": 1},
        expected_packet_sha256="a" * 64,
    )

    assert receipt["ok"] is False
    assert receipt["tools_enabled"] is True
    assert receipt["failure"] == {
        "kind": "capability_unsupported", "structured": True,
    }


@pytest.mark.asyncio
async def test_handoff_capability_rejects_normal_manifest_configuration_drift(
    session,
):
    expected = {
        "runtime": "claude",
        "model": "claude-sonnet-5[1m]",
        "cli_version": "2.1.197",
        "sdk_version": "0.2.114",
        "raw_ref_runtime_tool": False,
    }
    fingerprint = hashlib.sha256(json.dumps(
        expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()

    class ValidationBackend:
        async def verify_handoff_validation_surface(self):
            return {
                "ok": True,
                "validation_tools_empty": True,
                "raw_ref_runtime_tool": False,
                "cli_version": "2.1.197",
                "sdk_version": "0.2.114",
            }

    class NormalBackend:
        def handoff_expected_capabilities(self):
            return expected

        def build_handoff_manifest(self, _prepared, *, validation_profile):
            assert validation_profile is False
            return SimpleNamespace(configuration_sha256="changed-configuration")

    session._make_backend = MagicMock(return_value=NormalBackend())
    staged = SimpleNamespace(
        backend=ValidationBackend(),
        runtime="claude",
        model="claude-sonnet-5[1m]",
        packet={"expected_target_capability": expected},
        prepared=SimpleNamespace(packet={}),
        cleanup_locator="/isolated",
        configuration_sha256="preflighted-configuration",
        session_id="target-session",
    )

    receipt = await session._verify_handoff_capabilities(
        staged, expected_fingerprint=fingerprint,
    )

    assert receipt["ok"] is False
    assert receipt["fingerprint"] == fingerprint
    assert receipt["configuration_sha256"] == "changed-configuration"


@pytest.mark.asyncio
async def test_handoff_packet_integrity_fails_before_target_factory(session):
    packet = {
        "schema_version": 1,
        "recent_messages": [{"role": "user", "content": "tampered"}],
        "integrity": {"canonical_sha256": "a" * 64},
    }
    prepared = SimpleNamespace(
        handoff_id="h1",
        packet=packet,
        packet_sha256="a" * 64,
        expected_capability_sha256="b" * 64,
        expected_capability={},
        pending_effects=0,
        project_docs=(),
    )
    session._make_backend = MagicMock(
        side_effect=AssertionError("target factory must not run")
    )

    outcome = await session._stage_runtime_handoff_target(
        prepared, target_model="claude-sonnet-5[1m]", mode="packet",
    )

    assert outcome == {
        "ok": False,
        "failure": {"kind": "packet_integrity_mismatch", "structured": False},
    }
    session._make_backend.assert_not_called()


@pytest.mark.asyncio
async def test_idempotent_handoff_reuses_frozen_project_bytes(
    session, tmp_path, monkeypatch,
):
    from app import db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "handoff.db")
    dbmod.init_db()
    session.id = "frozen-project-docs"
    session.backend_type = "claude"
    session.model = "claude-sonnet-5[1m]"
    session.session_id = "source-session"
    dbmod.save_session(session._to_db_dict())
    dbmod.add_log(
        session.id, datetime.now(timezone.utc), "user_message", "old fact",
    )
    session._drain_handoff_log_writes = AsyncMock()
    session._expected_handoff_capability = MagicMock(return_value={
        "runtime": "codex", "model": "gpt-5.6-sol", "supported": False,
    })

    first = await session._prepare_runtime_handoff(
        "gpt-5.6-sol",
        idempotency_key="same-operator-request",
        project_docs=[{"path": "AGENTS.md", "content": "frozen policy"}],
    )
    second = await session._prepare_runtime_handoff(
        "gpt-5.6-sol",
        idempotency_key="same-operator-request",
        project_docs=[{"path": "AGENTS.md", "content": "changed later"}],
    )

    assert first.handoff_id == second.handoff_id
    assert second.packet == first.packet
    assert second.project_docs == (
        {"path": "AGENTS.md", "content": "frozen policy"},
    )


@pytest.mark.asyncio
async def test_t1_385_deferred_interrupt_waits_for_native_terminal_and_accounts_once(
    session, monkeypatch,
):
    """RED #385 R4: deferred control is native accounting, not manual stop/end_turn."""
    from app.backend_codex import CodexBackend
    from app.session import AgentStatus
    from app import bg_jobs

    provenance = {
        "kind": "deferred_job",
        "origin": "orchestra.bg_jobs",
        "job_id": "bg-session-385",
        "event_id": "bgjob:v1:bg-session-385:completed",
        "turn_control": "interrupt",
    }
    result = {
        "content": [{"type": "text", "text": "END YOUR TURN NOW"}],
        "structuredContent": {"result": provenance, "error": None},
        "isError": False,
    }
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/fake")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-session-385"
    backend._active_turn_id = "turn-session-385"
    backend._request = AsyncMock(return_value={})
    backend._usage_baseline = {
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "cache_write_input_tokens": 0,
        "output_tokens": 10,
    }
    backend._thread_usage_total = {
        "input_tokens": 160,
        "cached_input_tokens": 50,
        "cache_write_input_tokens": 0,
        "output_tokens": 15,
    }
    backend._last_call_usage = {
        "input_tokens": 90,
        "model_context_window": 258_400,
    }

    session.model = "gpt-5.6-sol"
    session.backend_type = "codex"
    session._backend = backend
    session.status = AgentStatus.RUNNING
    session._turn_start = 1.0
    session._manually_interrupted = False
    persisted_statuses = []
    session._persist = MagicMock(side_effect=lambda: persisted_statuses.append(session.status))
    session._log = MagicMock()
    session._submit_db_write = MagicMock()
    session._cancel_precompact_timer = MagicMock()
    session._hibernate.schedule = MagicMock()

    def discard_background(coro):
        coro.close()
        return MagicMock()

    session._spawn_bg = MagicMock(side_effect=discard_background)
    monkeypatch.setattr(
        bg_jobs,
        "bg_manager",
        SimpleNamespace(has_active_jobs=lambda session_id: session_id == session.id),
    )

    for message in (
        {
            "method": "item/completed",
            "params": {
                "threadId": "thread-session-385", "turnId": "turn-session-385",
                "item": {
                    "id": "tool-session-385", "type": "mcpToolCall",
                    "server": "orchestra", "tool": "codex_review",
                    "arguments": {}, "result": result,
                },
            },
        },
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-session-385",
                "turn": {
                    "id": "turn-session-385", "status": "interrupted", "items": [],
                },
            },
        },
    ):
        await backend._notifications.put(message)

    await asyncio.wait_for(session._turn_event_loop(), timeout=0.5)

    backend._request.assert_awaited_once_with("turn/interrupt", {
        "threadId": "thread-session-385",
        "turnId": "turn-session-385",
    })
    assert session.status == AgentStatus.WAITING
    assert AgentStatus.IDLE not in persisted_statuses
    assert session._manually_interrupted is False
    usage_calls = [
        call for call in session._submit_db_write.call_args_list
        if call.args and getattr(call.args[0], "__name__", "") == "turn_usage_add"
    ]
    assert len(usage_calls) == 1
    assert usage_calls[0].kwargs["event_id"] == "turn-session-385"
    assert usage_calls[0].kwargs["stop_reason"] == "interrupted"
    assert usage_calls[0].kwargs["input_tokens"] == 60
    assert usage_calls[0].kwargs["output_tokens"] == 5
    logged = [(call.args[0], call.args[1]) for call in session._log.call_args_list]
    assert ("status", "waiting for bg jobs") in logged
    assert not [content for _kind, content in logged if content.startswith("turn FAILED")]


@pytest.mark.asyncio
async def test_t1_385_message_during_deferred_interrupt_queues_until_native_terminal(
    session, monkeypatch,
):
    """RED #385 R4: a real wake racing the interrupt cannot steer the dying turn."""
    from app.backend_codex import CodexBackend
    from app.session import AgentStatus
    from app import bg_jobs

    interrupt_seen = asyncio.Event()
    release_interrupt = asyncio.Event()

    async def request(method, params):
        assert method == "turn/interrupt"
        assert params == {
            "threadId": "thread-race-385",
            "turnId": "turn-race-385",
        }
        interrupt_seen.set()
        await release_interrupt.wait()
        return {}

    backend = CodexBackend(model="gpt-5.6-sol", cwd="/fake")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-race-385"
    backend._active_turn_id = "turn-race-385"
    backend._request = AsyncMock(side_effect=request)

    session.model = "gpt-5.6-sol"
    session.backend_type = "codex"
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session.status = AgentStatus.RUNNING
    session._turn_start = 1.0
    session._log = MagicMock()
    session._persist = MagicMock()
    session._submit_db_write = MagicMock()
    session._cancel_precompact_timer = MagicMock()
    session._hibernate.schedule = MagicMock()

    def discard_background(coro):
        coro.close()
        return MagicMock()

    session._spawn_bg = MagicMock(side_effect=discard_background)
    monkeypatch.setattr(
        bg_jobs,
        "bg_manager",
        SimpleNamespace(has_active_jobs=lambda session_id: session_id == session.id),
    )

    control = {
        "kind": "deferred_job",
        "origin": "orchestra.bg_jobs",
        "job_id": "bg-race-385",
        "event_id": "bgjob:v1:bg-race-385:completed",
        "turn_control": "interrupt",
    }
    await backend._notifications.put({
        "method": "item/completed",
        "params": {
            "threadId": "thread-race-385", "turnId": "turn-race-385",
            "item": {
                "id": "tool-race-385", "type": "mcpToolCall",
                "server": "orchestra", "tool": "codex_review", "arguments": {},
                "result": {
                    "content": [{"type": "text", "text": "END YOUR TURN NOW"}],
                    "structuredContent": {"result": control, "error": None},
                    "isError": False,
                },
            },
        },
    })

    listener = asyncio.create_task(session._turn_event_loop())
    try:
        try:
            await asyncio.wait_for(interrupt_seen.wait(), timeout=0.2)
        except asyncio.TimeoutError:
            pytest.fail("structured deferred control did not request turn/interrupt")

        assert session.status == AgentStatus.RUNNING
        wake = "[Background job completed] Codex review NEEDS WORK"
        await session.send(wake)
        assert session._pending_messages == [wake]
        assert backend._request.await_count == 1
        assert session._manually_interrupted is False
        assert session.status == AgentStatus.RUNNING

        await backend._notifications.put({
            "method": "turn/completed",
            "params": {
                "threadId": "thread-race-385",
                "turn": {
                    "id": "turn-race-385", "status": "interrupted", "items": [],
                },
            },
        })
        release_interrupt.set()
        await asyncio.wait_for(listener, timeout=0.5)

        methods = [call.args[0] for call in backend._request.await_args_list]
        assert methods == ["turn/interrupt"]
        assert session.status == AgentStatus.WAITING
    finally:
        release_interrupt.set()
        if not listener.done():
            listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)
