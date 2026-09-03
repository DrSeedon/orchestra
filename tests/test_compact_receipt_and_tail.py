"""Компакт: честная квитанция и дословный хвост рядом со сводкой.

Три шва, по одному на дефект:
  T1 — `after_pct` измерен по ack-ходу, а не переписан дореформенным значением;
  T2 — свежий обмен уезжает в новую сессию ДОСЛОВНО, а не только пересказом;
  T3 — компакт сессии со снесённым рабочим каталогом отказывает сразу.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def session(tmp_path, monkeypatch):
    from app.session import AgentSession

    # Боевую базу не трогаем: слой БД сессии подменяется целиком (#418).
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
    return AgentSession(
        id="compact-001", name="w-compact", scope="/test", cwd=str(tmp_path),
        model="claude-opus-5[1m]", system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )


SUMMARY = (
    "TASK STATE\n- Пересказ хода работ.\nDECISIONS\n- Выбран путь A.\n"
    "FILES AND ARTIFACTS\n- app/session.py — правка компакта.\n" + "x" * 220
)


class _CompactBackend:
    """Ход-сводка отдаёт текст, ack-ход отдаёт свой расход токенов."""

    def __init__(self, ack_usage):
        self.sent = []
        self.session_id = None
        self._ack_usage = ack_usage
        self._turns = 0

    async def connect(self): pass
    async def disconnect(self): pass
    async def reconnect(self): pass
    async def interrupt(self): pass

    async def send(self, msg):
        self.sent.append(msg)

    async def events(self):
        from app.events import AgentEvent

        self._turns += 1
        if self._turns == 1:
            yield AgentEvent(type="text", content=SUMMARY)
        yield AgentEvent(type="turn_end", metadata={
            "ok": True, "stop_reason": "end_turn", "num_turns": 1,
            "session_id": "fresh-session",
        })


def _wire(session, backend):
    """ack-событие ставится вручную: настоящий turn-loop в этих тестах не крутится."""
    async def fake_ensure_backend(force_fresh=False):
        session._backend = backend
        if session._compact_ack_event:
            event = session._compact_ack_event

            async def _ack():
                await asyncio.sleep(0.02)
                # ack-ход прожёг ровно столько контекста, сколько заявлено
                session.total_input_tokens += backend._ack_usage["input"]
                session.total_cache_create_tokens += backend._ack_usage["cache_create"]
                event.set()

            asyncio.create_task(_ack())
        return backend

    return fake_ensure_backend


@pytest.mark.asyncio
async def test_t1_after_pct_is_measured_from_the_ack_turn(session):
    """Квитанция обязана назвать РЕАЛЬНЫЙ размер новой сессии, а не старый процент."""
    session._last_context = {
        "percentage": 100, "total_tokens": 1_000_000, "max_tokens": 1_000_000,
        "known": True,
    }
    backend = _CompactBackend({"input": 4_000, "cache_create": 116_000})
    logged = []
    session._log = lambda t, c, **kw: logged.append((t, c))

    with patch.object(session, "_make_backend", return_value=backend), \
         patch.object(session, "_ensure_backend", side_effect=_wire(session, backend)):
        result = await session.compact()

    assert result["ok"] is True
    assert result["before_pct"] == 100
    assert result["after_pct"] == 12, (
        f"after_pct={result['after_pct']}: компакт снова печатает дореформенный процент "
        "вместо измеренного по ack-ходу (120 000 из 1 000 000)"
    )
    assert result["post_tokens"] == 120_000
    assert result["pre_tokens"] == 1_000_000
    assert result["dropped_tokens"] == 880_000
    done = [c for t, c in logged if t == "status" and c.startswith("compact done:")]
    assert done, "строки успеха нет вовсе"
    assert "1000000" in done[0].replace(" ", "") or "1_000_000" in done[0], (
        f"в квитанции нет размера ДО компакта: {done[0]!r}"
    )
    assert "120000" in done[0].replace(" ", ""), (
        f"в квитанции нет размера ПОСЛЕ компакта: {done[0]!r}"
    )


@pytest.mark.asyncio
async def test_t2_preamble_carries_the_verbatim_tail(session, monkeypatch):
    """Свежий обмен переезжает дословно, а не только в пересказе сводки."""
    from app import session as session_mod

    verbatim = "померь ГОЛОВУ очереди, а не первую не-SUBMITTED строку"
    monkeypatch.setattr(session_mod, "get_logs", lambda *a, **k: [
        {"type": "tool_result", "content": "x" * 400_000},
        {"type": "user_message", "content": verbatim},
        {"type": "text", "content": "принял, чиню голову очереди"},
    ])
    session._last_context = {
        "percentage": 90, "total_tokens": 900_000, "max_tokens": 1_000_000,
        "known": True,
    }
    backend = _CompactBackend({"input": 1_000, "cache_create": 99_000})
    session._log = MagicMock()

    with patch.object(session, "_make_backend", return_value=backend), \
         patch.object(session, "_ensure_backend", side_effect=_wire(session, backend)):
        result = await session.compact()

    assert result["ok"] is True
    preamble = [m for m in backend.sent if "Acknowledge briefly." in m]
    assert preamble, "преамбула не отправлена"
    assert SUMMARY in preamble[0], "сводка пропала из преамбулы"
    assert verbatim in preamble[0], (
        "дословного хвоста в преамбуле нет — свежий обмен доехал только пересказом"
    )
    assert "x" * 1000 not in preamble[0], (
        "в хвост уехал tool_result: он и есть основной вес контекста"
    )


@pytest.mark.asyncio
async def test_t3_gone_worktree_is_terminal_not_retried(session, tmp_path):
    """Снесённый worktree — отказ с ПЕРВОЙ попытки, без трёх заходов с бэкоффом."""
    import shutil

    shutil.rmtree(tmp_path)
    attempts = []
    slept = []
    session._log = MagicMock()

    class _DeadBackend:
        session_id = None

        async def connect(self):
            attempts.append(1)
            raise RuntimeError(f"Working directory does not exist: {tmp_path}")

        async def disconnect(self): pass
        async def send(self, msg): pass
        async def events(self):
            yield None

    async def _no_sleep(delay):
        slept.append(delay)

    with patch.object(session, "_make_backend", return_value=_DeadBackend()), \
         patch("asyncio.sleep", side_effect=_no_sleep):
        result = await session.compact()

    assert result["ok"] is False
    assert attempts == [1], f"компакт всё ещё ретраит мёртвый каталог: {len(attempts)} попыток"
    assert not [d for d in slept if d >= 30], f"бэкофф всё ещё отрабатывает: {slept}"
    assert "working directory does not exist" in result["error"].lower(), result["error"]
