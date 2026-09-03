import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, types

from app import tg_bridge as tb


_BOT_TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"


def _message(**content) -> types.Message:
    return types.Message.model_validate(
        {
            "message_id": 42,
            "date": 1_700_000_000,
            "chat": {
                "id": -100123456,
                "type": "supergroup",
                "title": "Orchestra",
            },
            "message_thread_id": 7,
            "from": {
                "id": 99,
                "is_bot": False,
                "first_name": "Sender",
            },
            **content,
        }
    )


async def _feed(message: types.Message) -> None:
    bot = Bot(_BOT_TOKEN)
    try:
        await tb.dp.feed_update(
            bot,
            types.Update(update_id=message.message_id, message=message),
        )
    finally:
        await bot.session.close()


@pytest.mark.asyncio
async def test_unknown_rich_message_is_serialized_logged_and_delivered(
    monkeypatch, caplog,
):
    rich_message = {
        "blocks": [
            {"type": "paragraph", "text": "A channel post"},
        ]
    }
    message = _message(rich_message=rich_message)
    session = SimpleNamespace(id="session-508")
    deliver = AsyncMock()
    monkeypatch.setattr(tb, "_resolve_orch", AsyncMock(return_value=("orch", session)))
    monkeypatch.setattr(tb, "_send_to_agent", deliver)

    with caplog.at_level(logging.WARNING, logger="tg-bridge"):
        await _feed(message)

    deliver.assert_awaited_once()
    delivered_message, delivered_session, content = deliver.await_args.args
    assert delivered_message.message_id == message.message_id
    assert delivered_session is session
    marker, serialized = content.split("] ", 1)
    assert marker == "[rich_message"
    assert json.loads(serialized) == rich_message
    assert any(
        record.getMessage().startswith("TG ingress fallback:")
        and "type=rich_message" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_any_unhandled_message_uses_its_actual_type(monkeypatch):
    message = _message(
        contact={
            "phone_number": "+12025550123",
            "first_name": "Contact",
            "user_id": 123,
        }
    )
    session = SimpleNamespace(id="session-508")
    deliver = AsyncMock()
    monkeypatch.setattr(tb, "_resolve_orch", AsyncMock(return_value=("orch", session)))
    monkeypatch.setattr(tb, "_send_to_agent", deliver)

    await _feed(message)

    deliver.assert_awaited_once()
    marker, serialized = deliver.await_args.args[2].split("] ", 1)
    assert marker == "[contact"
    assert json.loads(serialized)["phone_number"] == "+12025550123"


@pytest.mark.asyncio
async def test_rich_message_photo_keeps_file_ids_without_downloading(monkeypatch):
    photo = {
        "file_id": "telegram-file-id",
        "file_unique_id": "stable-file-id",
        "width": 1280,
        "height": 720,
        "file_size": 12345,
    }
    message = _message(
        rich_message={"blocks": [{"type": "photo", "photo": [photo]}]}
    )
    session = SimpleNamespace(id="session-508")
    deliver = AsyncMock()
    download = AsyncMock()
    monkeypatch.setattr(tb, "_resolve_orch", AsyncMock(return_value=("orch", session)))
    monkeypatch.setattr(tb, "_send_to_agent", deliver)
    monkeypatch.setattr(tb, "_download_file", download)

    await _feed(message)

    deliver.assert_awaited_once()
    payload = json.loads(deliver.await_args.args[2].split("] ", 1)[1])
    assert payload["blocks"][0]["photo"] == [photo]
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_top_level_photo_still_downloads_before_fallback(monkeypatch):
    message = _message(
        photo=[
            {
                "file_id": "small-file",
                "file_unique_id": "small-stable",
                "width": 320,
                "height": 180,
            },
            {
                "file_id": "large-file",
                "file_unique_id": "large-stable",
                "width": 1280,
                "height": 720,
            },
        ]
    )
    session = SimpleNamespace(id="session-508")
    deliver = AsyncMock()
    download = AsyncMock(return_value="/data/uploads/photo.jpg")
    monkeypatch.setattr(tb, "_resolve_orch", AsyncMock(return_value=("orch", session)))
    monkeypatch.setattr(tb, "_send_to_agent", deliver)
    monkeypatch.setattr(tb, "_download_file", download)

    await _feed(message)

    download.assert_awaited_once()
    assert download.await_args.args[0] == "large-file"
    deliver.assert_awaited_once()
    assert deliver.await_args.args[2] == "[photo: /data/uploads/photo.jpg]"


@pytest.mark.asyncio
async def test_forwarded_rich_message_delivers_source_metadata(monkeypatch):
    message = _message(
        rich_message={"blocks": []},
        forward_origin={
            "type": "channel",
            "date": 1_700_000_000,
            "chat": {
                "id": -100987654321,
                "type": "channel",
                "title": "Example News",
                "username": "example_news",
            },
            "message_id": 77,
        },
    )
    session = SimpleNamespace(id="session-508")
    deliver = AsyncMock()
    monkeypatch.setattr(tb, "_resolve_orch", AsyncMock(return_value=("orch", session)))
    monkeypatch.setattr(tb, "_send_to_agent", deliver)

    await _feed(message)

    deliver.assert_awaited_once()
    assert deliver.await_args.args[2].startswith(
        "[Forwarded from Example News | https://t.me/example_news/77] "
        "[rich_message] "
    )


def test_forward_origin_user_preserves_legacy_marker():
    sender = {
        "id": 7,
        "is_bot": False,
        "first_name": "Alice",
        "last_name": "Smith",
    }
    modern = _message(
        forward_origin={
            "type": "user",
            "date": 1_700_000_000,
            "sender_user": sender,
        }
    )
    legacy = _message(forward_date=1_700_000_000, forward_from=sender)

    assert tb._forward_meta(modern) == tb._forward_meta(legacy) == (
        "[Forwarded from Alice Smith] "
    )


def test_forward_origin_channel_includes_title_and_post_link():
    message = _message(
        forward_origin={
            "type": "channel",
            "date": 1_700_000_000,
            "chat": {
                "id": -100987654321,
                "type": "channel",
                "title": "Example News",
                "username": "example_news",
            },
            "message_id": 77,
        }
    )

    assert tb._forward_meta(message) == (
        "[Forwarded from Example News | https://t.me/example_news/77] "
    )
