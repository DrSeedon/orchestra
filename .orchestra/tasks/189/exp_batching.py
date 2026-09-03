"""#189, эксперимент: что происходит с пачкой тул-сообщений в очереди доставки.

Гипотеза H2: при всплеске тулов тела склеиваются в одно сообщение и ТЕРЯЮТ
expandable-разметку → юзер видит стену сырого JSON вместо свёрнутых блоков.
Гипотеза H3: сообщение, дропнутое по TTL косметики, не теряет тела — они
остаются в bucket и уезжают ПОЗЖЕ, приклеившись к следующему туду.

Живой Telegram не трогается: bot — заглушка. Запуск:
    /home/kesha/orchestra/.venv/bin/python -m pytest docs/tasks/189/exp_batching.py -q -s
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def tb(tmp_path, monkeypatch):
    monkeypatch.setattr("app.tg_bridge.CONFIG_PATH", tmp_path / "tg_bridge.json")
    from app import tg_bridge as t

    t.config = {"group_id": -100123, "topics": {}, "token": "test"}
    t.bot = AsyncMock()
    for attr, val in [
        ("_tg_delivery_states", {}), ("_tg_dispatch_tasks", {}),
        ("_tg_queue_loops", {}), ("_tg_result_tasks", set()),
        ("_tg_result_wrappers", {}), ("_tg_flood_until", {}),
        ("_tg_last_send", {}), ("_tg_call_sequence", 0), ("_tg_tool_batches", {}),
    ]:
        monkeypatch.setattr(t, attr, val)
    return t


def _mk_tool_body(i: int) -> str:
    """Тело как в проде: JSON вызова Bash, обрезанный до 1200 знаков."""
    return (
        '{"command": "/bin/bash -lc \\"sed -n \'1,260p\' app/tg_bridge.py\\"", '
        f'"cwd": "/home/kesha/orchestra", "call": {i}, '
        '"command_actions": [{"type": "read", "path": "app/tg_bridge.py"}]}'
    )


@pytest.mark.asyncio
async def test_burst_of_tools(tb, monkeypatch):
    sent = []
    gate = asyncio.Event()

    async def send_message(chat_id, text, **kw):
        # первая отправка «висит», как реальный round-trip к Bot API
        if not sent:
            await gate.wait()
        sent.append({"text": text, "entities": kw.get("entities")})
        return SimpleNamespace(message_id=len(sent))

    tb.bot.send_message.side_effect = send_message
    monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

    futures = []
    for i in range(10):
        futures.append(await tb._send_expandable(
            -100, 42, "🔧 Bash", _mk_tool_body(i),
            telemetry_key=("tool", 42, "orch"),
            batch_bucket=tb._tg_tool_batch(42, "orch"),
        ))
    await asyncio.sleep(0)
    gate.set()
    for f in futures:
        if isinstance(f, asyncio.Future):
            await asyncio.wait_for(f, timeout=5)
    await asyncio.sleep(0.05)

    print(f"\n[H2] 10 тул-вызовов → {len(sent)} сообщений в Telegram")
    for n, m in enumerate(sent):
        ents = m["entities"]
        kind = "свёрнуто (expandable)" if ents else "СЫРОЙ ТЕКСТ, без свёртки"
        print(f"  сообщение {n+1}: {len(m['text']):5} знаков, {kind}, "
              f"тел внутри: {m['text'].count('🔧 Bash')}")
    assert sent


@pytest.mark.asyncio
async def test_dropped_by_ttl_reappears_later(tb, monkeypatch):
    """H3: тело, чья отправка убита по TTL, всплывает позже вместе со следующим тулом."""
    sent = []
    gate = asyncio.Event()

    async def send_message(chat_id, text, **kw):
        if not sent:
            await gate.wait()
        sent.append(text)
        return SimpleNamespace(message_id=len(sent))

    tb.bot.send_message.side_effect = send_message
    monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

    bucket = tb._tg_tool_batch(42, "orch")
    first = await tb._send_expandable(
        -100, 42, "🔧 Bash", "ХОД-1 первый тул",
        telemetry_key=("tool", 42, "orch"), batch_bucket=bucket)
    second = await tb._send_expandable(
        -100, 42, "🔧 Bash", "ХОД-1 второй тул",
        telemetry_key=("tool", 42, "orch"), batch_bucket=bucket)

    # косметика протухла: диспетчер выбросит отправку второго
    monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0.0001)
    await asyncio.sleep(0.01)
    gate.set()
    await asyncio.wait_for(first, timeout=5) if isinstance(first, asyncio.Future) else None
    if isinstance(second, asyncio.Future):
        await asyncio.wait_for(second, timeout=5)
    await asyncio.sleep(0.05)
    state = tb._tg_delivery_states[-100]
    print(f"\n[H3] после дропа: доставлено {len(sent)} сообщ, "
          f"dropped={state.telemetry_dropped}, coalesced={state.telemetry_coalesced}, "
          f"осталось тел в bucket={len(bucket)}")
    for i, s in enumerate(sent):
        print(f"  доставлено {i+1}: {s[:80]!r}")

    # следующий ход, новый тул — что уедет вместе с ним?
    monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 15.0)
    third = await tb._send_expandable(
        -100, 42, "🔧 Bash", "ХОД-2 новый тул",
        telemetry_key=("tool", 42, "orch"), batch_bucket=bucket)
    if isinstance(third, asyncio.Future):
        await asyncio.wait_for(third, timeout=5)
    await asyncio.sleep(0.05)
    print(f"[H3] после следующего хода доставлено {len(sent)} сообщ:")
    for i, s in enumerate(sent):
        print(f"  доставлено {i+1}: {s[:120]!r}")
