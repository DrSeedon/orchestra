import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, types

from app import tg_bridge as tb


def _message(**content) -> types.Message:
    return types.Message.model_validate(
        {
            "message_id": 509,
            "date": 1_700_000_000,
            "chat": {"id": -100123456, "type": "supergroup"},
            "message_thread_id": 7,
            "from": {"id": 99, "is_bot": False, "first_name": "Sender"},
            **content,
        }
    )


async def _feed(message: types.Message) -> None:
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789")
    try:
        await tb.dp.feed_update(
            bot,
            types.Update(update_id=message.message_id, message=message),
        )
    finally:
        await bot.session.close()


@pytest.mark.asyncio
async def test_forum_topic_edited_is_logged_without_agent_delivery(monkeypatch, caplog):
    message = _message(
        forum_topic_edited={"icon_custom_emoji_id": "5350392020785437399"}
    )
    session = SimpleNamespace(id="session-509")
    resolve = AsyncMock(return_value=("orch", session))
    deliver = AsyncMock()
    monkeypatch.setattr(tb, "_resolve_orch", resolve)
    monkeypatch.setattr(tb, "_send_to_agent", deliver)

    with caplog.at_level(logging.WARNING, logger="tg-bridge"):
        await _feed(message)

    resolve.assert_not_awaited()
    deliver.assert_not_awaited()
    assert any(
        record.getMessage().startswith("TG ingress fallback:")
        and "type=forum_topic_edited" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_unknown_nonservice_type_still_reaches_agent(monkeypatch):
    message = _message(future_user_content={"body": "keep this"})
    session = SimpleNamespace(id="session-509")
    deliver = AsyncMock()
    monkeypatch.setattr(tb, "_resolve_orch", AsyncMock(return_value=("orch", session)))
    monkeypatch.setattr(tb, "_send_to_agent", deliver)

    await _feed(message)

    deliver.assert_awaited_once()
    assert deliver.await_args.args[2] == (
        '[future_user_content] {"body":"keep this"}'
    )
