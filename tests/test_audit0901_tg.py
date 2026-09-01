"""Аудит 01.09.2026 — четыре тихие потери в TG-мосте.

Каждый тест краснеет по СВОЕЙ причине:
1. поздняя транскрипция (медиа дорезолвилось после MEDIA_WAIT_MAX) не доходит до агента;
2. `_mirror_send(important=True)` уезжает в зеркало по косметической полосе;
3. рестарт зависшего Local Bot API морозит event loop и не проверяет код возврата sudo;
4. разные строки журнала одного топика (веер `subagent_end`) схлопываются по общему
   ключу очереди, и до юзера доезжает только последняя.
5. поздняя доставка отдаёт содержимое ПОВТОРНО, если тот же токен резолвят дважды.
"""

import asyncio
import logging
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest


@pytest.fixture
def tb(tmp_path, monkeypatch):
    """Изолированный модуль tg_bridge — состояние сбрасываем перед каждым тестом."""
    monkeypatch.setattr("app.tg_bridge.CONFIG_PATH", tmp_path / "tg_bridge.json")
    from app import tg_bridge

    monkeypatch.setattr(tg_bridge, "config", {
        "group_id": -100123456, "topics": {}, "mirrors": {}, "token": "test",
    })
    monkeypatch.setattr(tg_bridge, "bot", None)
    monkeypatch.setattr(tg_bridge, "_tasks", [])
    monkeypatch.setattr(tg_bridge, "_stream_tasks", {})
    monkeypatch.setattr(tg_bridge, "_mirror_outboxes", {})
    monkeypatch.setattr(tg_bridge, "_mirror_tasks", {})
    monkeypatch.setattr(tg_bridge, "_mirror_dropped", {})
    monkeypatch.setattr(tg_bridge, "_mirror_stopping", set())
    monkeypatch.setattr(tg_bridge, "_buffers", {})
    monkeypatch.setattr(tg_bridge, "_tg_delivery_states", {})
    monkeypatch.setattr(tg_bridge, "_tg_dispatch_tasks", {})
    monkeypatch.setattr(tg_bridge, "_tg_queue_loops", {})
    monkeypatch.setattr(tg_bridge, "_tg_result_tasks", set())
    monkeypatch.setattr(tg_bridge, "_tg_result_wrappers", {})
    monkeypatch.setattr(tg_bridge, "_tg_flood_until", {})
    monkeypatch.setattr(tg_bridge, "_tg_last_send", {})
    monkeypatch.setattr(tg_bridge, "_tg_call_sequence", 0)
    yield tg_bridge
    for task in list(tg_bridge._tg_dispatch_tasks.values()) + list(tg_bridge._mirror_tasks.values()):
        task.cancel()


class _RecordingManager:
    def __init__(self):
        self.sent = []

    async def send(self, sid, text):
        self.sent.append((sid, text))

    def get(self, sid):
        return SimpleNamespace(name="pilot")


def _tg_message():
    return SimpleNamespace(
        chat=SimpleNamespace(id=-100123456),
        message_thread_id=42,
        from_user=None,
    )


async def _until(predicate, timeout=2.0, sleep=None):
    sleep = sleep or asyncio.sleep
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await sleep(0.01)
    return predicate()


@pytest.mark.asyncio
async def test_late_transcription_still_reaches_the_agent(tb, monkeypatch):
    """Голосовое, дорезолвившееся после MEDIA_WAIT_MAX, обязано доехать до агента."""
    monkeypatch.setattr(tb, "DEBOUNCE_SEC", 0)
    monkeypatch.setattr(tb, "MEDIA_WAIT_MAX", 0)
    manager = _RecordingManager()
    monkeypatch.setattr(tb, "_manager", manager)

    session = SimpleNamespace(id="sess-voice")
    token = await tb._register_media(_tg_message(), session)
    buf = tb._get_buf("sess-voice")

    # Дебаунс сдался и провернул epoch, транскрипция ещё идёт.
    assert await _until(lambda: buf.epoch is not token.epoch), "дебаунс не отпустил батч"
    assert manager.sent == [], "батч ушёл с недоделанным медиа"

    await tb._resolve_media(token, "[voice: /tmp/voice.oga | забери задачу #77]")

    assert any("забери задачу #77" in text for _sid, text in manager.sent), (
        "поздняя транскрипция выброшена молча: агент сообщения юзера так и не получил"
    )

    await tb._resolve_media(token, "[voice: /tmp/voice.oga | забери задачу #77]")

    assert len(manager.sent) == 1, (
        f"поздняя доставка повторилась на втором резолве того же токена: {manager.sent!r}"
    )


@pytest.mark.asyncio
async def test_second_resolve_of_a_live_token_delivers_nothing(tb, monkeypatch):
    """Токен одноразовый: повторный резолв не отдаёт содержимое отдельным сообщением."""
    # Дебаунс не должен вмешаться — проверяем ровно поведение второго резолва.
    monkeypatch.setattr(tb, "DEBOUNCE_SEC", 30)
    manager = _RecordingManager()
    monkeypatch.setattr(tb, "_manager", manager)

    session = SimpleNamespace(id="sess-dup")
    token = await tb._register_media(_tg_message(), session)
    buf = tb._get_buf("sess-dup")
    try:
        await tb._resolve_media(token, "FIRST")
        await tb._resolve_media(token, "SECOND")

        assert [content for _m, content, _r in buf.entries] == ["FIRST"], (
            f"второй резолв переписал батч: {buf.entries!r}"
        )
        assert manager.sent == [], (
            "уже отрезолвленный токен ушёл в позднюю ветку и доставил содержимое "
            f"вторым сообщением: {manager.sent!r}"
        )
    finally:
        if buf.debounce_task and not buf.debounce_task.done():
            buf.debounce_task.cancel()
            await asyncio.gather(buf.debounce_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_mirror_carries_important_flag_to_the_send(tb, monkeypatch):
    """Финальный текст агента в зеркале не должен ехать по косметической полосе."""
    tb.bot = SimpleNamespace()
    tb.config["mirrors"] = {"pilot": {"chat_id": -100999, "topic_id": 7}}
    calls = []

    async def fake_send(chat_id, text, thread_id=None, **kwargs):
        calls.append({"text": text, **kwargs})
        return SimpleNamespace(message_id=1)

    monkeypatch.setattr(tb, "_tg_send_safe", fake_send)

    assert await tb._mirror_send("pilot", "💬 финальный ответ", important=True) is True
    await asyncio.wait_for(tb._mirror_outboxes["pilot"].join(), timeout=2)

    assert calls, "зеркало не отправило ничего"
    assert calls[0].get("important") is True, (
        f"important потерян по дороге в зеркало: {calls[0]!r}"
    )
    assert calls[0].get("best_effort") is not True, (
        "важный текст зеркала уехал best_effort — дропается на занятом rate-слоте"
    )


@pytest.mark.asyncio
async def test_bot_api_restart_does_not_freeze_loop_and_reports_sudo_refusal(
    tb, monkeypatch, caplog,
):
    """Лечение зависшего Local Bot API не морозит процесс и не врёт об успехе."""
    real_sleep = asyncio.sleep
    ticks = {"n": 0}
    observed = {}
    attempted = asyncio.Event()
    refusal = b"sudo: a terminal is required to read the password"

    class _DeadSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, *args, **kwargs):
            raise OSError("connection refused")

    class _FastSleep:
        """Тот же asyncio, но без реальных пауз здоровья — тест не ждёт 120 с."""

        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        async def sleep(self, delay, *args, **kwargs):
            await real_sleep(0)

    def refused_run(cmd, *args, **kwargs):
        """Так ведёт себя настоящий отбитый sudo: ненулевой код и текст в stderr."""
        before = ticks["n"]
        time.sleep(0.05)
        observed["restart"] = {"cmd": list(cmd), "ticks": ticks["n"] - before}
        attempted.set()
        raise subprocess.CalledProcessError(1, cmd, output=b"", stderr=refusal)

    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **kw: _DeadSession())
    monkeypatch.setattr(subprocess, "run", refused_run)
    monkeypatch.setattr(tb, "asyncio", _FastSleep(asyncio))

    async def heartbeat():
        while True:
            ticks["n"] += 1
            await real_sleep(0)

    beat = asyncio.create_task(heartbeat())
    loop_task = asyncio.create_task(tb._bot_api_health_loop("http://127.0.0.1:8081"))
    with caplog.at_level(logging.WARNING, logger="tg-bridge"):
        try:
            await asyncio.wait_for(attempted.wait(), timeout=5)
            # Отказ приходит из потока уже ПОСЛЕ события — даём ходу дописать журнал.
            await _until(lambda: refusal.decode() in caplog.text,
                         timeout=2.0, sleep=real_sleep)
        finally:
            loop_task.cancel()
            beat.cancel()
            await asyncio.gather(loop_task, beat, return_exceptions=True)

    assert observed["restart"]["ticks"] > 0, (
        "event loop заморожен на время рестарта telegram-bot-api: за всю команду "
        f"не прокрутилось ни одного тика ({observed['restart']!r}). Юнит рестартят "
        "потому, что он завис, — systemctl ждёт его до TimeoutStopSec"
    )
    assert refusal.decode() in caplog.text, (
        "sudo отбит, а мост доложил об успешном рестарте: "
        f"код возврата и stderr выброшены. Журнал: {caplog.text!r}"
    )


@pytest.mark.asyncio
async def test_fan_out_subagent_lines_do_not_overwrite_each_other(tb, monkeypatch):
    """Веер из трёх воркеров: три разных subagent_end — три сообщения, а не последнее."""
    real_sleep = asyncio.sleep
    monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
    sent = []
    rows = [
        {"id": 11, "type": "subagent_end",
         "content": "alpha | id=a1 | type=local_agent | status=ok | summary"},
        {"id": 12, "type": "subagent_end",
         "content": "beta | id=a2 | type=local_agent | status=failed | summary"},
        {"id": 13, "type": "subagent_end",
         "content": "gamma | id=a3 | type=local_agent | status=ok | summary"},
    ]
    polls = {"n": 0}

    def get_logs(session_id, after_id=0, conn=None):
        polls["n"] += 1
        if polls["n"] == 1:
            return []
        if polls["n"] == 2:
            return rows
        raise asyncio.CancelledError

    async def send_message(chat_id, text, **kwargs):
        sent.append(text)
        return SimpleNamespace(message_id=len(sent), chat=SimpleNamespace(id=chat_id))

    class _FakeConn:
        def close(self):
            pass

    monkeypatch.setattr("app.db.get_all_sessions",
                        lambda: [{"name": "orch", "scope": "/scope", "role": "orchestrator"}])
    monkeypatch.setattr("app.db.get_session_by_name", lambda name, scope: {"id": "sid"})
    monkeypatch.setattr("app.db.get_logs", get_logs)
    monkeypatch.setattr("app.db._conn", _FakeConn)
    monkeypatch.setattr(tb, "_schedule_topic_status", lambda *a: None)
    monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
    monkeypatch.setattr(tb, "_mirror_send", AsyncMock())
    monkeypatch.setattr(tb.asyncio, "sleep", lambda _delay: real_sleep(0))
    tb.bot = SimpleNamespace(send_message=send_message)

    with pytest.raises(asyncio.CancelledError):
        await tb.stream_logs("orch", 42)

    await _until(lambda: len(sent) >= 3, timeout=2.0, sleep=real_sleep)

    delivered = [text.split("\n")[0] for text in sent]
    assert any("alpha" in text for text in delivered), (
        f"строки веера схлопнулись по общему ключу — выжила последняя: {delivered!r}"
    )
    assert any("beta" in text for text in delivered), (
        f"провал второго воркера не доехал до юзера: {delivered!r}"
    )
    assert any("gamma" in text for text in delivered), (
        f"последняя строка не доехала: {delivered!r}"
    )
