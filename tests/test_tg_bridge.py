"""TDD-тесты для tg_bridge.py — инкремент имён топиков и cleanup при delete.

Покрытие:
- ``_short_name`` — нормализация имени оркестратора в имя топика.
- ``_pick_unique_topic_name`` — выбор свободного имени с инкрементом ``-2``, ``-3`` при коллизиях.
- ``remove_topics_for_orchs`` — удаление топиков из TG и записей из ``config["topics"]`` /
  ``config["topic_names"]``. Mirrors не трогаем. Ошибки Bot API не должны валить процесс.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from inspect import getsource
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import LinkPreviewOptions
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage
from app.tg_bridge import stop_bridge as _real_stop_bridge


@pytest.mark.asyncio
async def test_t2_artifact_text_disables_link_preview_at_the_bot_call(tb, monkeypatch):
    message = SimpleNamespace(message_id=77, chat=SimpleNamespace(id=-100123456))
    tb.bot = AsyncMock()
    tb.bot.send_message.return_value = message
    monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

    result = await tb._tg_send_safe(
        -100123456,
        "https://artifacts.example.test/api/artifacts/open/locator#capability",
        42,
        important=True,
        disable_link_preview=True,
    )

    assert result is message
    options = tb.bot.send_message.await_args.kwargs["link_preview_options"]
    assert isinstance(options, LinkPreviewOptions)
    assert options.is_disabled is True


@pytest.mark.asyncio
async def test_t2_text_helper_threads_preview_disable_without_changing_document_fallback(
    tb, tmp_path, monkeypatch,
):
    captured = {}
    message = SimpleNamespace(message_id=77, chat=SimpleNamespace(id=-100123456))

    async def send_safe(*args, **kwargs):
        captured.update(kwargs)
        return message

    tb.bot = object()
    tb.config["topics"] = {"publisher": 42}
    monkeypatch.setattr(tb, "_tg_send_safe", send_safe)
    text_result = await tb.send_text_to_tg(
        "https://artifacts.example.test/open/id#cap",
        scope="/scope",
        sender="publisher",
        disable_link_preview=True,
    )
    assert text_result["ok"] is True
    assert captured["disable_link_preview"] is True

    path = tmp_path / "fallback.html"
    path.write_text("<!doctype html><p>fallback</p>")
    file_calls = []

    async def send_file(*args, **kwargs):
        file_calls.append((args, kwargs))
        return message

    monkeypatch.setattr(tb, "_tg_send_file_safe", send_file)
    file_result = await tb.send_file_to_tg(
        str(path), "fallback", "/scope", "publisher", as_document=True,
    )
    assert file_result["ok"] is True
    assert file_calls[0][1]["is_photo"] is False


@pytest.fixture
def tb(tmp_path, monkeypatch):
    """Изолированный модуль tg_bridge: путь к конфигу — во временной папке,
    состояние модуля сбрасываем перед каждым тестом."""
    cfg_path = tmp_path / "tg_bridge.json"
    monkeypatch.setattr("app.tg_bridge.CONFIG_PATH", cfg_path)
    from app import tg_bridge

    tg_bridge.config = {"group_id": -100123456, "topics": {}, "token": "test"}
    tg_bridge._topic_status = {}
    tg_bridge.bot = None
    tg_bridge._pil_available = None
    monkeypatch.setattr(tg_bridge, "_tasks", [])
    monkeypatch.setattr(tg_bridge, "_stream_tasks", {})
    monkeypatch.setattr(tg_bridge, "_topic_status_tasks", {})
    monkeypatch.setattr(tg_bridge, "_topic_status_desired", {})
    monkeypatch.setattr(tg_bridge, "_topic_create_tasks", {})
    monkeypatch.setattr(tg_bridge, "_bridge_tasks", {})
    monkeypatch.setattr(tg_bridge, "_mirror_outboxes", {}, raising=False)
    monkeypatch.setattr(tg_bridge, "_mirror_tasks", {}, raising=False)
    monkeypatch.setattr(tg_bridge, "_mirror_dropped", {}, raising=False)
    monkeypatch.setattr(tg_bridge, "_mirror_stopping", set(), raising=False)
    monkeypatch.setattr(tg_bridge, "_buffers", {})
    monkeypatch.setattr(tg_bridge, "_tg_delivery_states", {})
    monkeypatch.setattr(tg_bridge, "_tg_dispatch_tasks", {})
    monkeypatch.setattr(tg_bridge, "_tg_queue_loops", {})
    monkeypatch.setattr(tg_bridge, "_tg_result_tasks", set())
    monkeypatch.setattr(tg_bridge, "_tg_result_wrappers", {})
    monkeypatch.setattr(tg_bridge, "_tg_flood_until", {})
    monkeypatch.setattr(tg_bridge, "_tg_last_send", {})
    monkeypatch.setattr(tg_bridge, "_tg_call_sequence", 0)
    return tg_bridge


@pytest.mark.asyncio
async def test_polling_does_not_override_uvicorn_signal_handlers(tb, monkeypatch):
    dispatcher = AsyncMock()
    dispatcher.start_polling.side_effect = asyncio.CancelledError
    bot = object()
    monkeypatch.setattr(tb, "dp", dispatcher)
    tb.bot = bot

    with pytest.raises(asyncio.CancelledError):
        await tb._safe_polling()

    dispatcher.start_polling.assert_awaited_once_with(bot, handle_signals=False)


@pytest.mark.asyncio
async def test_transcribe_audio_persists_voice_cost(tb, tmp_path, monkeypatch):
    from app import transcription

    db_path = tmp_path / "voice-cost.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import _conn, init_db
    init_db()

    audio_path = tmp_path / "voice.oga"
    audio_path.write_bytes(b"audio")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    transcription._transcription_cache = {}
    monkeypatch.setattr(transcription, "_save_transcription_cache", lambda cache: None)

    payload = {
        "metadata": {"duration": 90.0},
        "results": {"channels": [{"alternatives": [{"transcript": "hello"}]}]},
    }

    class FakeResponse:
        status_code = 200
        content = json.dumps(payload).encode()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: FakeClient())

    text, err = await tb._transcribe_audio(
        str(audio_path),
        "tg-file-1",
        session_name="orch",
        scope="/scope",
    )

    assert (text, err) == ("hello", None)
    with _conn() as c:
        row = c.execute("SELECT * FROM voice_costs").fetchone()
    assert row["duration_sec"] == 90.0
    assert row["cost_usd"] == pytest.approx(90 / 60 * 0.0052)
    assert row["session_name"] == "orch"
    assert row["scope"] == "/scope"
    assert row["file_id"] == "tg-file-1"
    assert tb._transcribe_audio is transcription.transcribe_audio


# ── _short_name ────────────────────────────────────────────────────────────


class TestShortName:
    def test_strips_orchestrator_suffix(self, tb):
        assert tb._short_name("pm-taksa-orchestrator") == "pm-taksa"

    def test_returns_as_is_when_no_suffix(self, tb):
        assert tb._short_name("pm-taksa") == "pm-taksa"


# ── _pick_unique_topic_name ────────────────────────────────────────────────


class TestPickUniqueTopicName:
    def test_returns_base_when_config_empty(self, tb):
        assert tb._pick_unique_topic_name("pm-taksa-orchestrator") == "pm-taksa"

    def test_increments_when_short_collides_with_existing_orch(self, tb):
        tb.config["topics"]["pm-taksa-orchestrator"] = 100
        # для нового orch с тем же базовым именем — должен дать "-2"
        assert tb._pick_unique_topic_name("pm-taksa") == "pm-taksa-2"

    def test_returns_existing_mapping_for_self(self, tb):
        """Если orch уже есть в topic_names — возвращаем сохранённое имя без инкремента."""
        tb.config["topics"]["pm-taksa-orchestrator"] = 100
        tb.config["topic_names"] = {"pm-taksa-orchestrator": "pm-taksa"}
        assert tb._pick_unique_topic_name("pm-taksa-orchestrator") == "pm-taksa"

    def test_increments_past_two_when_two_taken(self, tb):
        tb.config["topics"] = {"a": 100, "b": 101}
        tb.config["topic_names"] = {"a": "pm-taksa", "b": "pm-taksa-2"}
        # short("pm-taksa-orchestrator") == "pm-taksa" — занято, "-2" занято → "-3"
        assert tb._pick_unique_topic_name("pm-taksa-orchestrator") == "pm-taksa-3"

    def test_uses_short_of_unmapped_orch_as_fallback(self, tb):
        """Старые записи без topic_names — short от ключа должен считаться использованным."""
        tb.config["topics"]["pm-taksa-orchestrator"] = 100  # нет topic_names → fallback short = "pm-taksa"
        # другое имя — свободно
        assert tb._pick_unique_topic_name("other-orchestrator") == "other"
        # коллизия с unmapped → инкремент
        assert tb._pick_unique_topic_name("pm-taksa") == "pm-taksa-2"

    def test_persists_topic_names_dict_existence(self, tb):
        """Вызов должен инициализировать config['topic_names'] если его нет."""
        tb._pick_unique_topic_name("foo")
        assert "topic_names" in tb.config


# ── remove_topics_for_orchs ────────────────────────────────────────────────


class TestRemoveTopicsForOrchs:
    @pytest.mark.asyncio
    async def test_deletes_main_topic_and_cleans_config(self, tb):
        tb.config["topics"] = {"orch1": 100, "orch2": 101}
        tb.config["topic_names"] = {"orch1": "pm-taksa", "orch2": "other"}
        tb.bot = AsyncMock()

        result = await tb.remove_topics_for_orchs(["orch1"])

        tb.bot.delete_forum_topic.assert_called_once_with(
            chat_id=tb.config["group_id"], message_thread_id=100
        )
        assert "orch1" not in tb.config["topics"]
        assert "orch1" not in tb.config["topic_names"]
        # другие записи не тронуты
        assert tb.config["topics"]["orch2"] == 101
        assert tb.config["topic_names"]["orch2"] == "other"
        assert result["deleted"] == ["orch1"]
        assert result["failed"] == []

    @pytest.mark.asyncio
    async def test_does_not_touch_mirrors(self, tb):
        tb.config["topics"] = {"orch1": 100}
        tb.config["mirrors"] = {"orch1": {"chat_id": -1001, "topic_id": 50}}
        tb.bot = AsyncMock()

        await tb.remove_topics_for_orchs(["orch1"])

        # mirror остаётся в config полностью
        assert tb.config["mirrors"]["orch1"]["chat_id"] == -1001
        assert tb.config["mirrors"]["orch1"]["topic_id"] == 50
        # delete_forum_topic вызван ровно один раз — для main, не для mirror
        tb.bot.delete_forum_topic.assert_called_once_with(
            chat_id=tb.config["group_id"], message_thread_id=100
        )

    @pytest.mark.asyncio
    async def test_handles_bot_api_error_gracefully(self, tb):
        """Ошибка delete_forum_topic (топик уже удалён) — warning, но запись из config убираем."""
        tb.config["topics"] = {"orch1": 100}
        tb.bot = AsyncMock()
        tb.bot.delete_forum_topic.side_effect = Exception("Topic not found")

        result = await tb.remove_topics_for_orchs(["orch1"])

        assert "orch1" not in tb.config["topics"]
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "orch1"
        assert "Topic not found" in result["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_skips_orch_without_topic(self, tb):
        """Если у orch вообще нет записи в config['topics'] — мирно пропускаем."""
        tb.config["topics"] = {}
        tb.bot = AsyncMock()

        result = await tb.remove_topics_for_orchs(["orch1"])

        tb.bot.delete_forum_topic.assert_not_called()
        assert "orch1" in result["skipped"]

    @pytest.mark.asyncio
    async def test_returns_error_when_bridge_inactive(self, tb):
        """Без bot/group_id — отказываем без побочных эффектов."""
        tb.bot = None
        tb.config["group_id"] = 0
        tb.config["topics"] = {"orch1": 100}

        result = await tb.remove_topics_for_orchs(["orch1"])

        assert "error" in result
        # запись осталась — мы НЕ чистили config когда bridge не активен
        assert tb.config["topics"]["orch1"] == 100

    @pytest.mark.asyncio
    async def test_cleans_topic_status_cache(self, tb):
        """_topic_status (кэш running/idle) тоже чистим, чтобы новый orch с тем же именем не унаследовал старое состояние."""
        tb.config["topics"] = {"orch1": 100}
        tb._topic_status["orch1"] = True
        tb.bot = AsyncMock()

        await tb.remove_topics_for_orchs(["orch1"])

        assert "orch1" not in tb._topic_status

    @pytest.mark.asyncio
    async def test_multiple_orchs_one_failure_does_not_block_others(self, tb):
        tb.config["topics"] = {"orch1": 100, "orch2": 101, "orch3": 102}
        tb.bot = AsyncMock()

        # вторая попытка падает, остальные ок
        def delete(chat_id, message_thread_id):
            if message_thread_id == 101:
                raise Exception("boom")

        tb.bot.delete_forum_topic.side_effect = delete

        result = await tb.remove_topics_for_orchs(["orch1", "orch2", "orch3"])

        # все три записи убраны из config (даже та, для которой API кинул)
        assert tb.config["topics"] == {}
        assert set(result["deleted"]) == {"orch1", "orch3"}
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "orch2"


# ── _find_orch_for_scope ───────────────────────────────────────────────────


class TestFindOrchForScope:
    def test_prefers_top_level_over_sub_orchestrator(self, tb, monkeypatch):
        """Возвращает top-level orchestrator (без parent_name), а не sub-orchestrator."""
        sessions = [
            {"name": "sub-orch", "scope": "/s", "role": "sub-orchestrator", "parent_name": "orch1", "status": "idle"},
            {"name": "orch1", "scope": "/s", "role": "orchestrator", "parent_name": "", "status": "idle"},
        ]
        monkeypatch.setattr("app.db.get_all_sessions", lambda: sessions)
        result = tb._find_orch_for_scope("/s")
        assert result == "orch1"

    def test_falls_back_to_sub_orchestrator_when_no_top_level(self, tb, monkeypatch):
        """Если top-level не найден — возвращает sub-orchestrator."""
        sessions = [
            {"name": "sub-orch", "scope": "/s", "role": "sub-orchestrator", "parent_name": "someone", "status": "idle"},
        ]
        monkeypatch.setattr("app.db.get_all_sessions", lambda: sessions)
        result = tb._find_orch_for_scope("/s")
        assert result == "sub-orch"

    def test_scope_mismatch_returns_none(self, tb, monkeypatch):
        """Оркестратор в другом scope не возвращается."""
        sessions = [
            {"name": "orch1", "scope": "/other", "role": "orchestrator", "parent_name": "", "status": "idle"},
        ]
        monkeypatch.setattr("app.db.get_all_sessions", lambda: sessions)
        result = tb._find_orch_for_scope("/s")
        assert result is None

    def test_worker_ignored(self, tb, monkeypatch):
        """Workers не возвращаются."""
        sessions = [
            {"name": "worker1", "scope": "/s", "role": "worker", "parent_name": "", "status": "idle"},
        ]
        monkeypatch.setattr("app.db.get_all_sessions", lambda: sessions)
        result = tb._find_orch_for_scope("/s")
        assert result is None


class TestRenameOrchTopic:
    @pytest.mark.asyncio
    async def test_moves_uncertain_mirror_marker_with_config_key(
        self, tb, monkeypatch,
    ):
        tb.bot = AsyncMock()
        tb.bot.create_forum_topic.return_value = type(
            "Topic",
            (),
            {"message_thread_id": 99},
        )()
        tb.config["topics"] = {"old": 42}
        tb.config["topic_names"] = {"old": "old"}
        tb.config["mirrors"] = {
            "old": {"chat_id": -200, "topic_id": None},
        }
        tb.config["topic_create_uncertain"] = {
            "mirror:old": "2026-07-25T00:00:00+00:00",
        }
        monkeypatch.setattr(tb, "_ensure_stream", lambda *args: None)
        monkeypatch.setattr(tb, "_manager", object())
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "new", "role": "orchestrator"}],
        )

        result = await tb.rename_orch_topic("old", "new")
        await tb.ensure_topics()

        assert result["ok"] is True
        assert "mirror:old" not in tb.config["topic_create_uncertain"]
        assert "mirror:new" in tb.config["topic_create_uncertain"]
        tb.bot.create_forum_topic.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_waits_for_inflight_mirror_create_before_renaming(
        self, tb, monkeypatch,
    ):
        create_started = asyncio.Event()
        release_create = asyncio.Event()

        async def create_forum_topic(**kwargs):
            create_started.set()
            await release_create.wait()
            return type("Topic", (), {"message_thread_id": 99})()

        tb.bot = AsyncMock()
        tb.bot.create_forum_topic.side_effect = create_forum_topic
        tb.config["topics"] = {"old": 42}
        tb.config["topic_names"] = {"old": "old"}
        mirror = {"chat_id": -200, "topic_id": None}
        tb.config["mirrors"] = {"old": mirror}
        monkeypatch.setattr(tb, "_ensure_stream", lambda *args: None)

        creating = asyncio.create_task(tb._ensure_mirror_topic("old", mirror))
        await asyncio.wait_for(create_started.wait(), timeout=5)
        renaming = asyncio.create_task(tb.rename_orch_topic("old", "new"))
        await asyncio.sleep(0)

        try:
            assert not renaming.done()
        finally:
            release_create.set()
            await asyncio.gather(creating, renaming, return_exceptions=True)

        assert tb.bot.create_forum_topic.await_count == 1
        assert tb.config["mirrors"]["new"]["topic_id"] == 99






# ── _check_pil ──────────────────────────────────────────────────────────────




class TestTgImageLane:
    @pytest.mark.asyncio
    async def test_slow_photo_edit_keeps_order_without_holding_later_text(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "source.png"
        source.write_bytes(b"original")
        positions = []
        edit_started = asyncio.Event()
        release_edit = asyncio.Event()

        tb.bot = AsyncMock()

        async def send_message(_chat_id, text, **_kwargs):
            message = SimpleNamespace(message_id=len(positions) + 1)
            positions.append({"id": message.message_id, "kind": text})
            return message

        async def edit_message_media(*, message_id, **_kwargs):
            edit_started.set()
            await release_edit.wait()
            positions[message_id - 1]["kind"] = "PHOTO"
            return SimpleNamespace(message_id=message_id)

        tb.bot.send_message.side_effect = send_message
        tb.bot.edit_message_media.side_effect = edit_message_media
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        first_text = await tb._tg_send_safe(
            -100,
            "TEXT-1",
            42,
            telemetry_key=("test", 1),
        )
        completion = await tb._tg_send_file_safe(
            -100,
            str(source),
            "photo",
            42,
            is_photo=True,
            important=False,
            placeholder_text="IMAGE-POSITION",
        )
        await asyncio.wait_for(edit_started.wait(), timeout=5)
        assert await first_text is not None
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)
        later_text = await tb._tg_send_safe(
            -100,
            "TEXT-2",
            42,
            telemetry_key=("test", 2),
        )
        assert await later_text is not None

        assert [item["kind"] for item in positions] == [
            "TEXT-1",
            "IMAGE-POSITION",
            "TEXT-2",
        ]
        assert not completion.done()

        release_edit.set()
        assert await asyncio.wait_for(completion, timeout=5) is not None
        await asyncio.sleep(0)
        assert [item["kind"] for item in positions] == [
            "TEXT-1",
            "PHOTO",
            "TEXT-2",
        ]
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_failed_photo_edit_leaves_marker_and_counts_loss(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "failed.png"
        source.write_bytes(b"image")
        method = SendMessage(chat_id=-100, text="image placeholder")
        tb.bot = AsyncMock()
        tb.bot.send_message.return_value = SimpleNamespace(message_id=1)
        tb.bot.edit_message_media.side_effect = TelegramNetworkError(
            method=method,
            message="timeout",
        )
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        completion = await tb._tg_send_file_safe(
            -100,
            str(source),
            "failed",
            42,
            is_photo=True,
            important=False,
        )

        assert isinstance(completion, asyncio.Future)
        assert await completion is None
        snapshot = tb._tg_delivery_snapshot(-100)
        assert snapshot["image_lost"] == 1
        assert snapshot["image_reserved"] == 0
        assert tb.bot.send_message.await_count == 1
        await asyncio.sleep(0)
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_image_capacity_rejects_before_third_marker(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "bounded.png"
        source.write_bytes(b"image")
        release_edit = asyncio.Event()
        edit_started = asyncio.Event()
        marker_count = 0
        tb.bot = AsyncMock()

        async def send_message(*_args, **_kwargs):
            nonlocal marker_count
            marker_count += 1
            return SimpleNamespace(message_id=marker_count)

        async def edit_message_media(**_kwargs):
            edit_started.set()
            await release_edit.wait()
            return object()

        tb.bot.send_message.side_effect = send_message
        tb.bot.edit_message_media.side_effect = edit_message_media
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_IMAGE_QUEUE_MAX", 2)

        first = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True, important=False, placeholder_text="first",
        )
        await asyncio.wait_for(edit_started.wait(), timeout=5)
        second = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True, important=False, placeholder_text="second",
        )
        third = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True, important=False, placeholder_text="third",
        )

        snapshot = tb._tg_delivery_snapshot(-100)
        assert third is None
        assert marker_count == 2
        assert snapshot["image_reserved"] == 2
        assert snapshot["image_in_flight"] == 1
        assert snapshot["image_queued"] == 1
        assert snapshot["image_dropped"] == 1

        release_edit.set()
        await asyncio.gather(first, second)
        await asyncio.sleep(0)
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_important_preview_handoff_does_not_wait_for_marker_or_edit(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "important.png"
        source.write_bytes(b"image")
        marker_started = asyncio.Event()
        release_marker = asyncio.Event()
        edit_started = asyncio.Event()
        release_edit = asyncio.Event()
        reply_sent = asyncio.Event()
        tb.bot = AsyncMock()

        async def send_message(_chat_id, text, **_kwargs):
            if text == "IMAGE":
                marker_started.set()
                await release_marker.wait()
                return SimpleNamespace(message_id=1)
            reply_sent.set()
            return object()

        async def edit_message_media(**_kwargs):
            edit_started.set()
            await release_edit.wait()
            return object()

        tb.bot.send_message.side_effect = send_message
        tb.bot.edit_message_media.side_effect = edit_message_media
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True,
            important=True,
            placeholder_text="IMAGE",
            isolated_preview=True,
        )
        await asyncio.wait_for(marker_started.wait(), timeout=5)
        state = tb._tg_delivery_states[-100]

        assert isinstance(completion, asyncio.Future)
        assert not completion.done()
        assert len(state.image_admission_tasks) == 1
        reply = asyncio.create_task(
            tb._tg_send_safe(-100, "reply", 42, important=True),
        )
        await asyncio.sleep(0)
        assert not reply_sent.is_set()

        release_marker.set()
        await asyncio.wait_for(edit_started.wait(), timeout=5)
        await asyncio.wait_for(reply_sent.wait(), timeout=5)
        assert await reply is not None
        assert not completion.done()

        release_edit.set()
        assert await completion is not None
        await asyncio.sleep(0)
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_important_preview_bypasses_optional_image_capacity(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "important.png"
        source.write_bytes(b"image")
        tb.bot = AsyncMock()
        tb.bot.send_message.return_value = SimpleNamespace(message_id=1)
        tb.bot.edit_message_media.return_value = object()
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_IMAGE_QUEUE_MAX", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True,
            important=True,
            isolated_preview=True,
        )

        assert isinstance(completion, asyncio.Future)
        assert await completion is not None
        assert tb._tg_delivery_snapshot(-100)["image_dropped"] == 0

    @pytest.mark.asyncio
    async def test_important_media_edit_retries_ambiguous_failure(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "retry.png"
        source.write_bytes(b"image")
        method = SendMessage(chat_id=-100, text="image")
        tb.bot = AsyncMock()
        tb.bot.send_message.return_value = SimpleNamespace(message_id=1)
        tb.bot.edit_message_media.side_effect = [
            TelegramNetworkError(method=method, message="timeout"),
            object(),
        ]
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True,
            important=True,
            isolated_preview=True,
        )

        assert await completion is not None
        assert tb.bot.edit_message_media.await_count == 2
        assert tb._tg_delivery_snapshot(-100)["image_lost"] == 0

    @pytest.mark.asyncio
    async def test_important_media_not_modified_is_success(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "already-edited.png"
        source.write_bytes(b"image")
        method = SendMessage(chat_id=-100, text="image")
        tb.bot = AsyncMock()
        tb.bot.send_message.return_value = SimpleNamespace(message_id=1)
        tb.bot.edit_message_media.side_effect = TelegramBadRequest(
            method=method,
            message="Bad Request: message is not modified",
        )
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True,
            important=True,
            isolated_preview=True,
        )

        assert await completion is True
        assert tb._tg_delivery_snapshot(-100)["image_lost"] == 0

    @pytest.mark.asyncio
    async def test_important_marker_ambiguous_failure_is_not_retried(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "marker.png"
        source.write_bytes(b"image")
        method = SendMessage(chat_id=-100, text="image")
        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = TelegramNetworkError(
            method=method,
            message="response lost",
        )
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True,
            important=True,
            isolated_preview=True,
        )

        assert await completion is None
        assert tb.bot.send_message.await_count == 1
        assert tb.bot.edit_message_media.await_count == 0
        assert tb._tg_delivery_snapshot(-100)["image_lost"] == 1

    @pytest.mark.asyncio
    async def test_important_marker_retries_explicit_flood_rejection(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "marker-flood.png"
        source.write_bytes(b"image")
        method = SendMessage(chat_id=-100, text="image")
        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = [
            TelegramRetryAfter(
                method=method,
                message="flood",
                retry_after=0,
            ),
            SimpleNamespace(message_id=1),
        ]
        tb.bot.edit_message_media.return_value = object()
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_RETRY_AFTER_MARGIN", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True,
            important=True,
            isolated_preview=True,
        )

        assert await completion is not None
        assert tb.bot.send_message.await_count == 2
        assert tb._tg_delivery_snapshot(-100)["image_lost"] == 0

    @pytest.mark.asyncio
    async def test_important_preview_admission_failure_propagates(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "overloaded.png"
        source.write_bytes(b"image")
        tb.bot = AsyncMock()
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_RELIABLE_QUEUE_MAX", 0)
        monkeypatch.setattr(tb, "_TG_RELIABLE_ADMISSION_MAX", 0)

        with pytest.raises(tb._TgDeliveryOverloaded):
            await tb._tg_send_file_safe(
                -100, str(source), None, 42,
                is_photo=True,
                important=True,
                isolated_preview=True,
            )

        assert tb.bot.send_message.await_count == 0
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_marker_admission_failure_is_unaccepted_and_lost_once(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "overloaded.png"
        source.write_bytes(b"image")
        tb.bot = AsyncMock()
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_RELIABLE_QUEUE_MAX", 0)
        monkeypatch.setattr(tb, "_TG_RELIABLE_ADMISSION_MAX", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True, important=False,
        )

        snapshot = tb._tg_delivery_snapshot(-100)
        assert completion is None
        assert snapshot["image_reserved"] == 0
        assert snapshot["image_lost"] == 1
        assert snapshot["image_dropped"] == 0
        tb.bot.send_message.assert_not_awaited()
        tb.bot.edit_message_media.assert_not_awaited()
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_ambiguous_marker_is_not_retried(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "ambiguous.png"
        source.write_bytes(b"image")
        method = SendMessage(chat_id=-100, text="image placeholder")
        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = TelegramNetworkError(
            method=method,
            message="response lost",
        )
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True, important=False,
        )

        snapshot = tb._tg_delivery_snapshot(-100)
        assert completion is None
        assert tb.bot.send_message.await_count == 1
        assert snapshot["image_lost"] == 1
        assert snapshot["image_reserved"] == 0
        tb.bot.edit_message_media.assert_not_awaited()
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_read_source_is_snapshotted_before_async_edit(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "mutable.png"
        source.write_bytes(b"before")
        release_edit = asyncio.Event()
        uploaded = []
        tb.bot = AsyncMock()
        tb.bot.send_message.return_value = SimpleNamespace(message_id=1)

        async def edit_message_media(*, media, **_kwargs):
            await release_edit.wait()
            uploaded.append(media.media.path.read_bytes())
            return object()

        tb.bot.edit_message_media.side_effect = edit_message_media
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True, important=False,
        )
        source.write_bytes(b"after")
        release_edit.set()

        assert await completion is not None
        assert uploaded == [b"before"]
        await asyncio.sleep(0)
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_old_marker_continuation_cannot_mutate_replacement_state(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "identity.png"
        source.write_bytes(b"image")
        old_marker_started = asyncio.Event()
        old_marker_result = asyncio.get_running_loop().create_future()
        release_new_edit = asyncio.Event()
        real_call_safe = tb._tg_call_safe
        ordered_calls = 0
        tb.bot = AsyncMock()
        tb.bot.send_message.return_value = SimpleNamespace(message_id=2)

        async def edit_message_media(**_kwargs):
            await release_new_edit.wait()
            return object()

        async def call_safe(*args, **kwargs):
            nonlocal ordered_calls
            if kwargs.get("ordered"):
                ordered_calls += 1
                if ordered_calls == 1:
                    old_marker_started.set()
                    return await old_marker_result
            return await real_call_safe(*args, **kwargs)

        tb.bot.edit_message_media.side_effect = edit_message_media
        monkeypatch.setattr(tb, "_tg_call_safe", call_safe)
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        old_submission = asyncio.create_task(
            tb._tg_send_file_safe(
                -100, str(source), None, 42,
                is_photo=True, important=False, placeholder_text="old",
            ),
        )
        await asyncio.wait_for(old_marker_started.wait(), timeout=5)
        await tb._reset_tg_delivery_state()

        new_completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True, important=False, placeholder_text="new",
        )
        replacement = tb._tg_delivery_states[-100]
        assert len(replacement.image_reservations) == 1

        old_marker_result.set_result(None)
        assert await old_submission is None
        assert tb._tg_delivery_states[-100] is replacement
        assert len(replacement.image_reservations) == 1
        assert replacement.image_lost == 0

        release_new_edit.set()
        await new_completion
        await asyncio.sleep(0)
        assert not list(tmp_path.glob("tg-image-*"))

    @pytest.mark.asyncio
    async def test_cross_worker_rate_slots_are_atomic_without_wall_clock(
        self, tb, monkeypatch,
    ):
        class FakeLoop:
            now = 100.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()
        state = tb._TgDeliveryState(loop=fake_loop)
        second_waiting = asyncio.Event()
        release_second = asyncio.Event()
        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)
            second_waiting.set()
            await release_second.wait()
            fake_loop.now += delay

        monkeypatch.setattr(tb.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 1.0)
        tb._tg_last_send.pop(-100, None)

        first = asyncio.create_task(tb._tg_reserve_rate_slot(-100, state))
        second = asyncio.create_task(tb._tg_reserve_rate_slot(-100, state))
        await first
        await asyncio.wait_for(second_waiting.wait(), timeout=5)

        assert not second.done()
        assert sleeps == [1.0]
        release_second.set()
        await second

    @pytest.mark.asyncio
    async def test_cancelled_consumer_does_not_delete_in_flight_snapshot(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        source = tmp_path / "cancelled.png"
        source.write_bytes(b"image")
        edit_started = asyncio.Event()
        release_edit = asyncio.Event()
        snapshot_path = None
        tb.bot = AsyncMock()
        tb.bot.send_message.return_value = SimpleNamespace(message_id=1)

        async def edit_message_media(*, media, **_kwargs):
            nonlocal snapshot_path
            snapshot_path = media.media.path
            edit_started.set()
            await release_edit.wait()
            assert snapshot_path.exists()
            return object()

        tb.bot.edit_message_media.side_effect = edit_message_media
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        completion = await tb._tg_send_file_safe(
            -100, str(source), None, 42,
            is_photo=True, important=False,
        )
        await asyncio.wait_for(edit_started.wait(), timeout=5)
        completion.cancel()
        await asyncio.gather(completion, return_exceptions=True)

        assert snapshot_path.exists()
        release_edit.set()
        while tb._tg_delivery_snapshot(-100)["image_in_flight"]:
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not snapshot_path.exists()

    @pytest.mark.asyncio
    async def test_concurrent_stale_state_replacement_is_singleton(self, tb):
        release_clear = asyncio.Event()

        async def admission_waiter():
            await release_clear.wait()

        waiter = asyncio.create_task(admission_waiter())
        await asyncio.sleep(0)
        stale = tb._TgDeliveryState(loop=object())
        stale.admission_tasks.add(waiter)
        tb._tg_delivery_states[-100] = stale

        first = asyncio.create_task(tb._tg_delivery_state_for(-100))
        second = asyncio.create_task(tb._tg_delivery_state_for(-100))
        await asyncio.sleep(0)
        assert stale.stopped

        release_clear.set()
        first_state, second_state = await asyncio.gather(first, second)

        assert first_state is second_state
        assert tb._tg_delivery_states[-100] is first_state
        assert first_state.loop is asyncio.get_running_loop()

    @pytest.mark.asyncio
    async def test_later_telemetry_cannot_pass_queued_marker(
        self, tb, monkeypatch,
    ):
        loop = asyncio.get_running_loop()
        state = tb._TgDeliveryState(loop=loop)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        def item(label, sequence, *, ordered=False):
            return tb._TgCallItem(
                call_factory=None,
                important=True,
                label=label,
                future=loop.create_future(),
                enqueued_at=loop.time(),
                sequence=sequence,
                ordered=ordered,
            )

        state.reliable.extend([
            item("R1", 1),
            item("R2", 2),
            item("R3", 3),
            item("R4", 4),
            item("MARKER", 5, ordered=True),
        ])
        later = item("TEXT-2", 6)
        later.important = False
        later.key = "later"
        state.telemetry[later.key] = later

        selected = [tb._tg_pick_next(state)[1].label for _ in range(5)]

        assert selected == ["R1", "R2", "R3", "R4", "MARKER"]

    @pytest.mark.asyncio
    async def test_cancelled_queued_marker_does_not_make_cosmetic_preempt_reliable(
        self, tb, monkeypatch,
    ):
        loop = asyncio.get_running_loop()
        state = tb._TgDeliveryState(loop=loop)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        def item(label, sequence, *, ordered=False, important=True):
            return tb._TgCallItem(
                call_factory=None,
                important=important,
                label=label,
                future=loop.create_future(),
                enqueued_at=loop.time(),
                key=label,
                sequence=sequence,
                ordered=ordered,
            )

        marker = item("CANCELLED-MARKER", 5, ordered=True)
        marker.future.cancel()
        text = item("TEXT", 6, important=False)
        state.reliable.extend([
            item("R1", 1),
            item("R2", 2),
            item("R3", 3),
            item("R4", 4),
            marker,
        ])
        state.telemetry[text.key] = text

        selected = [tb._tg_pick_next(state)[1].label for _ in range(4)]

        assert selected == ["R1", "R2", "R3", "R4"]
        state.in_flight = marker
        assert tb._tg_first_ordered_sequence(state) == 5

    @pytest.mark.asyncio
    async def test_pending_marker_splits_and_blocks_later_telemetry(
        self, tb, monkeypatch,
    ):
        loop = asyncio.get_running_loop()
        state = tb._TgDeliveryState(loop=loop)
        tb._tg_delivery_states[-100] = state
        tb._tg_call_sequence = 1
        monkeypatch.setattr(tb, "_TG_RELIABLE_QUEUE_MAX", 1)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)
        monkeypatch.setattr(tb, "_tg_start_dispatcher", lambda *_args: None)

        async def noop(_count=1):
            return object()

        backlog = tb._TgCallItem(
            call_factory=noop,
            important=True,
            label="backlog",
            future=loop.create_future(),
            enqueued_at=loop.time(),
            sequence=0,
        )
        earlier = tb._TgCallItem(
            call_factory=noop,
            important=False,
            label="TEXT-1",
            future=loop.create_future(),
            enqueued_at=loop.time(),
            key="same",
            sequence=1,
        )
        state.reliable.append(backlog)
        state.telemetry["same"] = earlier

        marker = asyncio.create_task(
            tb._tg_call_safe(
                -100,
                noop,
                ordered=True,
                label="MARKER",
            ),
        )
        await asyncio.sleep(0)
        assert state.ordered_admissions == {2}

        later_future = await tb._tg_call_safe(
            -100,
            noop,
            telemetry_key="same",
            call_factory=noop,
        )
        telemetry = sorted(state.telemetry.values(), key=lambda queued: queued.sequence)

        assert [queued.sequence for queued in telemetry] == [1, 3]
        assert [queued.count for queued in telemetry] == [1, 1]

        state.reliable.clear()
        tb._settle_tg_item(backlog)
        state.telemetry.pop(earlier.key)
        tb._settle_tg_item(earlier)
        assert tb._tg_pick_next(state) is None
        assert tb._tg_next_telemetry_wait(state, loop.time()) is None

        marker.cancel()
        await asyncio.gather(marker, return_exceptions=True)
        assert not state.ordered_admissions
        tb._settle_tg_item(telemetry[1])
        assert await later_future is None

    @pytest.mark.asyncio
    async def test_completed_marker_releases_barrier_before_next_marker(
        self, tb, monkeypatch,
    ):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        calls = []

        async def first_marker(_count=1):
            calls.append("MARKER-1")
            first_started.set()
            await release_first.wait()
            return object()

        async def text(_count=1):
            calls.append("TEXT")
            return object()

        async def second_marker(_count=1):
            calls.append("MARKER-2")
            return object()

        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        first = asyncio.create_task(
            tb._tg_call_safe(
                -100,
                first_marker,
                call_factory=first_marker,
                ordered=True,
                label="MARKER-1",
            ),
        )
        await first_started.wait()
        text_result = await tb._tg_call_safe(
            -100,
            text,
            telemetry_key="between",
            call_factory=text,
        )
        second = asyncio.create_task(
            tb._tg_call_safe(
                -100,
                second_marker,
                call_factory=second_marker,
                ordered=True,
                label="MARKER-2",
            ),
        )
        await asyncio.sleep(0)

        release_first.set()
        await asyncio.gather(first, text_result, second)

        assert calls == ["MARKER-1", "TEXT", "MARKER-2"]

class TestTgDeliveryStats:
    @pytest.mark.asyncio
    async def test_endpoint_returns_empty_chat_list(self, tb):
        from app.routes import tg as tg_routes

        assert await tg_routes.tg_delivery_stats() == {"chats": []}

    @pytest.mark.asyncio
    async def test_endpoint_returns_sorted_complete_read_only_snapshots(self, tb):
        from app.routes import tg as tg_routes

        class FakeLoop:
            def time(self):
                return 10.0

        running_loop = asyncio.get_running_loop()
        first = tb._TgDeliveryState(loop=FakeLoop())
        second = tb._TgDeliveryState(loop=FakeLoop())
        first.optional_dropped = 7
        first.reliable_lost = 2
        first.image_dropped = 3
        first.image_timeouts = 4
        first.image_lost = 5
        first.image_last_latency = 6.0
        first.image_max_latency = 7.0
        first.image_reservations.update({object(), object()})
        first.optional.append(tb._TgCallItem(
            call_factory=None,
            important=False,
            label="optional",
            future=running_loop.create_future(),
            enqueued_at=5.0,
        ))
        first.images.append(tb._TgCallItem(
            call_factory=None,
            important=False,
            label="image",
            future=running_loop.create_future(),
            enqueued_at=3.0,
        ))
        first.image_in_flight = tb._TgCallItem(
            call_factory=None,
            important=False,
            label="in-flight",
            future=running_loop.create_future(),
            enqueued_at=2.0,
        )
        tb._tg_delivery_states[-100] = first
        tb._tg_delivery_states[-200] = second

        payload = await tg_routes.tg_delivery_stats()

        assert [chat["chat_id"] for chat in payload["chats"]] == [-200, -100]
        by_chat = {chat["chat_id"]: chat for chat in payload["chats"]}
        assert by_chat[-100]["optional_dropped"] == 7
        assert by_chat[-100]["reliable_lost"] == 2
        assert by_chat[-100]["optional_oldest_age"] == 5.0
        expected_keys = {
            "chat_id",
            "reliable_queued",
            "reliable_admission_waiters",
            "reliable_overflow",
            "reliable_retries",
            "reliable_timeouts",
            "reliable_total_timeouts",
            "reliable_lost",
            "reliable_oldest_age",
            "reliable_last_latency",
            "reliable_max_latency",
            "telemetry_pending",
            "telemetry_coalesced",
            "telemetry_dropped",
            "telemetry_timeouts",
            "telemetry_lost",
            "telemetry_oldest_age",
            "telemetry_last_latency",
            "telemetry_max_latency",
            "optional_queued",
            "optional_images",
            "optional_dropped",
            "optional_timeouts",
            "optional_lost",
            "optional_oldest_age",
            "optional_last_latency",
            "optional_max_latency",
            "image_reserved",
            "image_queued",
            "image_in_flight",
            "image_dropped",
            "image_timeouts",
            "image_lost",
            "image_oldest_age",
            "image_last_latency",
            "image_max_latency",
        }
        assert set(by_chat[-100]) == expected_keys
        assert by_chat[-100]["image_reserved"] == 2
        assert by_chat[-100]["image_queued"] == 1
        assert by_chat[-100]["image_in_flight"] == 1
        assert by_chat[-100]["image_oldest_age"] == 7.0
        assert first.dispatcher is None
        assert first.image_dispatcher is None
        assert first.image_dropped == 3


# ── _bot_api_health_loop ───────────────────────────────────────────────────


class TestBotApiHealthLoop:
    @pytest.mark.asyncio
    async def test_three_consecutive_fails_triggers_restart(self, tb, monkeypatch):
        """3 fail подряд → subprocess.run с restart telegram-bot-api."""
        import asyncio as _asyncio

        restarts = []

        def fake_run(cmd, **kw):
            if "restart" in cmd:
                restarts.append(cmd)

        monkeypatch.setattr("subprocess.run", fake_run)
        # asyncio.sleep(120) → немедленно, asyncio.sleep(30) → немедленно
        monkeypatch.setattr(_asyncio, "sleep", AsyncMock())

        # aiohttp.ClientSession().get() всегда бросает исключение (имитация fail)
        import aiohttp
        class FakeResponse:
            status = 500
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass

        class FakeSession:
            def get(self, *a, **kw): return FakeResponse()
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass

        monkeypatch.setattr(aiohttp, "ClientSession", lambda: FakeSession())

        # Запускаем loop на 4 итерации (3 fail → restart → ещё 1 → выход)
        call_count = {"n": 0}
        original_sleep = _asyncio.sleep

        async def counting_sleep(s):
            call_count["n"] += 1
            if call_count["n"] > 4:
                raise _asyncio.CancelledError()

        monkeypatch.setattr(_asyncio, "sleep", counting_sleep)

        with pytest.raises(_asyncio.CancelledError):
            await tb._bot_api_health_loop("http://localhost:8081/health")

        assert len(restarts) >= 1
        assert any("telegram-bot-api" in str(r) for r in restarts)


# ── send_file_to_tg — routing по sender ─────────────────────────────────────


class TestSendFileRouting:
    @pytest.fixture
    def file_tmp(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("hello")
        return str(f)

    @pytest.mark.asyncio
    async def test_routes_to_caller_own_topic(self, tb, file_tmp, monkeypatch):
        """sender со своим топиком → файл уходит в config['topics'][sender], НЕ в топик оркестратора."""
        tb.bot = AsyncMock()
        tb.bot.send_document.return_value = type("M", (), {"message_id": 1, "chat": type("C", (), {"id": -100123456})(), "message_thread_id": 555})()
        tb.config["topics"] = {"worker-a": 555, "boss-orchestrator": 100}
        # _find_orch_for_scope вернул бы оркестратора — но не должен использоваться
        monkeypatch.setattr(tb, "_find_orch_for_scope", lambda s: "boss-orchestrator")

        result = await tb.send_file_to_tg(file_tmp, "cap", "/s", "worker-a")

        assert result["ok"] is True
        _, kwargs = tb.bot.send_document.call_args
        assert kwargs["message_thread_id"] == 555

    @pytest.mark.asyncio
    async def test_falls_back_to_scope_when_sender_has_no_topic(self, tb, file_tmp, monkeypatch):
        """sender без своего топика → fallback на топик оркестратора скоупа."""
        tb.bot = AsyncMock()
        tb.bot.send_document.return_value = type("M", (), {"message_id": 2, "chat": type("C", (), {"id": -100123456})(), "message_thread_id": 100})()
        tb.config["topics"] = {"boss-orchestrator": 100}
        monkeypatch.setattr(tb, "_find_orch_for_scope", lambda s: "boss-orchestrator")

        result = await tb.send_file_to_tg(file_tmp, "cap", "/s", "worker-no-topic", as_document=True)

        assert result["ok"] is True
        _, kwargs = tb.bot.send_document.call_args
        assert kwargs["message_thread_id"] == 100

    @pytest.mark.asyncio
    async def test_error_when_no_topic_anywhere(self, tb, file_tmp, monkeypatch):
        """Ни у sender, ни у скоупа нет топика → error."""
        tb.bot = AsyncMock()
        tb.config["topics"] = {}
        monkeypatch.setattr(tb, "_find_orch_for_scope", lambda s: None)

        result = await tb.send_file_to_tg(file_tmp, "cap", "/s", "ghost")

        assert "error" in result


# ── reliable outbound delivery ─────────────────────────────────────────────


class TestFormattedChunks:
    def test_splits_after_markdown_expands_table(self, tb):
        raw = (
            f"| {'A' * 100} | B |\n"
            "| --- | --- |\n"
            + "\n".join("| x | y |" for _ in range(40))
        )

        converted, _ = tb.md_convert(raw)
        chunks = tb._formatted_chunks(raw)

        assert tb._utf16_len(raw) < tb.TG_MSG_LIMIT
        assert tb._utf16_len(converted) > tb.TG_MSG_LIMIT
        assert len(chunks) > 1
        assert all(tb._utf16_len(text) <= tb.TG_MSG_LIMIT for text, _ in chunks)
        assert all(entities is None for _, entities in chunks)

    def test_keeps_entities_for_single_chunk(self, tb):
        chunks = tb._formatted_chunks("hello **world**")

        assert len(chunks) == 1
        text, entities = chunks[0]
        assert text == "hello world"
        assert entities


@pytest.mark.timeout(30)
class TestLimitsCommand:
    @staticmethod
    def _message(user_id=456):
        return SimpleNamespace(
            chat=SimpleNamespace(id=123),
            from_user=SimpleNamespace(id=user_id),
        )

    @staticmethod
    def _authorize_owner(tb):
        tb.bot = AsyncMock()
        tb.bot.get_chat_member.return_value = SimpleNamespace(status="creator")

    def test_format_limits_chat_message_includes_consumed_window_and_pace(self, tb):
        usage = {
            "anthropic": {
                "five_hour": {
                    "utilization": 30,
                    "window_minutes": 300,
                    "resets_at": "2026-08-01T00:50:00Z",
                },
            },
            "codex": {},
        }

        text = tb._format_limits_message_for_chat(
            usage,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

        lines = text.splitlines()
        assert lines[0] == "*Лимиты*"
        assert (
            "• Claude 5h — осталось 70%; израсходовано 30%;"
            " окно (83%); сброс 01.08.2026 07:50 UTC+7, через 50 мин; темп ok"
        ) in lines
        assert "• Claude 7d — нет данных" in lines
        assert "• Codex — нет данных" in lines

    @pytest.mark.asyncio
    async def test_limits_uses_important_file_delivery_path(self, tb, monkeypatch):
        usage = {
            "anthropic": {
                "five_hour": {
                    "utilization": 1,
                    "resets_at": "2026-08-01T11:30:00Z",
                },
                "seven_day": {
                    "utilization": 2,
                    "resets_at": "2026-08-03T08:15:00Z",
                },
            },
            "codex": {
                "primary": {
                    "utilization": 3,
                    "resets_at": "2026-08-01T08:45:00Z",
                },
            },
        }
        self._authorize_owner(tb)
        queued = AsyncMock()
        monkeypatch.setattr(tb, "_get_limits_usage", AsyncMock(return_value=usage))
        monkeypatch.setattr(tb, "_tg_send_file_safe", queued)

        await tb.handle_limits(self._message())

        tb.bot.get_chat_member.assert_awaited_once_with(-100123456, 456)
        queued.assert_awaited_once()
        args, kwargs = queued.await_args
        assert args[0] == 123
        assert args[1].endswith(".png")
        assert "Claude 5h" in args[2]
        assert kwargs["is_photo"] is True
        assert kwargs["important"] is True
        assert "израсходовано" in args[2]

    @pytest.mark.asyncio
    async def test_limits_sends_explicit_error_when_image_delivery_fails(
        self, tb, monkeypatch,
    ):
        usage = {
            "anthropic": {
                "five_hour": {
                    "utilization": 1,
                    "resets_at": "2026-08-01T11:30:00Z",
                },
                "seven_day": {
                    "utilization": 2,
                    "resets_at": "2026-08-03T08:15:00Z",
                },
            },
            "codex": {
                "primary": {
                    "utilization": 3,
                    "resets_at": "2026-08-01T08:45:00Z",
                },
            },
        }
        self._authorize_owner(tb)
        queued = AsyncMock(return_value=None)
        text_call = AsyncMock()
        monkeypatch.setattr(tb, "_get_limits_usage", AsyncMock(return_value=usage))
        monkeypatch.setattr(tb, "_tg_send_file_safe", queued)
        monkeypatch.setattr(tb, "_tg_send_safe", text_call)

        await tb.handle_limits(self._message())

        tb.bot.get_chat_member.assert_awaited_once_with(-100123456, 456)
        text_call.assert_awaited_once()
        assert text_call.await_args.args[1].startswith(
            "❌ /limits: RuntimeError: изображение не доставлено",
        )
        assert "Claude 5h" in text_call.await_args.args[1]

    @pytest.mark.asyncio
    async def test_usage_error_includes_exception_class_and_empty_detail(
        self, tb, monkeypatch,
    ):
        import httpx

        self._authorize_owner(tb)
        queued = AsyncMock()
        monkeypatch.setattr(
            tb,
            "_get_limits_usage",
            AsyncMock(side_effect=httpx.ReadTimeout("")),
        )
        monkeypatch.setattr(tb, "_tg_send_safe", queued)

        await tb.handle_limits(self._message())

        assert queued.await_args.args[1] == (
            "❌ /limits: ReadTimeout: (без сообщения)"
        )

    @pytest.mark.asyncio
    async def test_non_owner_is_denied_without_loading_usage(
        self, tb, monkeypatch,
    ):
        tb.bot = AsyncMock()
        tb.bot.get_chat_member.return_value = SimpleNamespace(
            status="administrator",
        )
        get_usage = AsyncMock()
        queued = AsyncMock()
        monkeypatch.setattr(tb, "_get_limits_usage", get_usage)
        monkeypatch.setattr(tb, "_tg_send_safe", queued)

        await tb.handle_limits(self._message())

        get_usage.assert_not_awaited()
        queued.assert_awaited_once_with(123, "⛔ Нет доступа.", important=False)

    @pytest.mark.asyncio
    async def test_owner_lookup_failure_is_fail_closed(
        self, tb, monkeypatch,
    ):
        tb.bot = AsyncMock()
        tb.bot.get_chat_member.side_effect = TimeoutError()
        get_usage = AsyncMock()
        queued = AsyncMock()
        monkeypatch.setattr(tb, "_get_limits_usage", get_usage)
        monkeypatch.setattr(tb, "_tg_send_safe", queued)

        await tb.handle_limits(self._message())

        get_usage.assert_not_awaited()
        queued.assert_awaited_once_with(123, "⛔ Нет доступа.", important=False)

    def test_handler_is_registered_for_private_chat_only(self, tb):
        source = getsource(tb.handle_limits)

        assert 'F.chat.type == "private"' in source
        assert '"group"' not in source


class TestTgRateAdmission:
    @pytest.mark.asyncio
    async def test_measured_group_burst_reserves_at_exact_1_05_spacing(
        self, tb, monkeypatch,
    ):
        class FakeLoop:
            now = 100.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()
        state = tb._TgDeliveryState(loop=fake_loop)
        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)
            fake_loop.now += delay

        monkeypatch.setattr(tb.asyncio, "sleep", fake_sleep)
        tb._tg_last_send.pop(-100, None)

        for _ in range(3):
            assert await tb._tg_reserve_rate_slot(-100, state)

        assert tb._TG_GROUP_INTERVAL == 1.05
        assert sleeps == pytest.approx([1.05, 1.05])
        assert list(state.rate_history) == pytest.approx(
            [100.0, 101.05, 102.1],
        )

    @pytest.mark.asyncio
    async def test_twenty_first_group_reservation_waits_for_rolling_window(
        self, tb, monkeypatch,
    ):
        class FakeLoop:
            now = 100.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()
        state = tb._TgDeliveryState(loop=fake_loop)
        state.rate_history.extend([100.0] * tb._TG_GROUP_WINDOW_MAX)
        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)
            fake_loop.now += delay

        monkeypatch.setattr(tb.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        assert await tb._tg_reserve_rate_slot(-100, state)

        assert sleeps == [60.0]
        assert list(state.rate_history) == [160.0]

    @pytest.mark.asyncio
    async def test_first_429_defers_retry_until_retry_after_margin(
        self, tb, monkeypatch,
    ):
        class FakeLoop:
            now = 100.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()
        state = tb._TgDeliveryState(loop=fake_loop)
        method = SendMessage(chat_id=-100, text="hello")
        starts = []
        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)
            fake_loop.now += delay

        async def call():
            starts.append(fake_loop.now)
            if len(starts) == 1:
                raise TelegramRetryAfter(
                    method=method,
                    message="flood",
                    retry_after=12,
                )
            return object()

        monkeypatch.setattr(tb.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_RETRY_AFTER_MARGIN", 0.25)

        result = await tb._tg_run_call(
            -100,
            state,
            call,
            True,
            "send_message",
            "reliable",
        )

        assert result is not None
        assert sleeps == [12.25]
        assert starts == [100.0, 112.25]
        assert state.reliable_retries == 1

    @pytest.mark.asyncio
    async def test_different_chats_have_independent_rolling_windows(
        self, tb, monkeypatch,
    ):
        class FakeLoop:
            def time(self):
                return 100.0

        blocked = tb._TgDeliveryState(loop=FakeLoop())
        free = tb._TgDeliveryState(loop=FakeLoop())
        blocked.rate_history.extend([100.0] * tb._TG_GROUP_WINDOW_MAX)
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        assert tb._tg_rate_wait(-100, blocked, 100.0) == 60.0
        assert tb._tg_rate_wait(-200, free, 100.0) == 0

    @pytest.mark.asyncio
    async def test_topic_ids_share_one_chat_rate_history(
        self, tb, monkeypatch,
    ):
        thread_ids = []

        async def send_message(*args, **kwargs):
            thread_ids.append(kwargs["message_thread_id"])
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        await asyncio.gather(
            tb._tg_send_safe(-100, "first", 11, important=True),
            tb._tg_send_safe(-100, "second", 22, important=True),
        )

        state = tb._tg_delivery_states[-100]
        assert thread_ids == [11, 22]
        assert len(state.rate_history) == 2
        assert set(tb._tg_delivery_states) == {-100}


class TestTgSendSafe:
    @pytest.mark.asyncio
    async def test_serializes_concurrent_group_sends(self, tb, monkeypatch):
        sent_at = []

        async def send_message(*args, **kwargs):
            sent_at.append(time.monotonic())
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.02)

        await asyncio.gather(*(
            tb._tg_send_safe(-100, f"m{i}", 42, important=True)
            for i in range(3)
        ))

        assert len(sent_at) == 3
        assert sent_at[1] - sent_at[0] >= 0.018
        assert sent_at[2] - sent_at[1] >= 0.018

    @pytest.mark.asyncio
    async def test_different_chats_do_not_share_lock(self, tb, monkeypatch):
        both_started = asyncio.Event()
        started = []

        async def send_message(chat_id, *args, **kwargs):
            started.append(chat_id)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=5)
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        await asyncio.gather(
            tb._tg_send_safe(-100, "a", 1, important=True),
            tb._tg_send_safe(-200, "b", 2, important=True),
        )

        assert set(started) == {-100, -200}

    @pytest.mark.asyncio
    async def test_retries_rate_limit_with_same_thread(self, tb, monkeypatch):
        method = SendMessage(chat_id=-100, text="hello")
        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = [
            TelegramRetryAfter(method=method, message="flood", retry_after=0),
            object(),
        ]
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_RETRY_AFTER_MARGIN", 0)

        result = await tb._tg_send_safe(-100, "hello", 77, important=True)

        assert result is not None
        assert tb.bot.send_message.await_count == 2
        assert [c.kwargs["message_thread_id"] for c in tb.bot.send_message.await_args_list] == [77, 77]

    @pytest.mark.asyncio
    async def test_nonimportant_flood_drop_counts_final_loss(
        self, tb, monkeypatch,
    ):
        method = SendMessage(chat_id=-100, text="tool")
        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = TelegramRetryAfter(
            method=method,
            message="flood",
            retry_after=0,
        )
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_RETRY_AFTER_MARGIN", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        delivery = await tb._tg_send_safe(
            -100,
            "tool",
            77,
            telemetry_key=("tool", 77),
        )

        assert await delivery is None
        assert tb._tg_delivery_snapshot(-100)["telemetry_lost"] == 1

    @pytest.mark.asyncio
    async def test_retries_ambiguous_network_error(self, tb, monkeypatch, caplog):
        method = SendMessage(chat_id=-100, text="hello")
        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = [
            TelegramNetworkError(method=method, message="timeout"),
            object(),
        ]
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)

        result = await tb._tg_send_safe(-100, "hello", 77, important=True)

        assert result is not None
        assert tb.bot.send_message.await_count == 2
        assert "ambiguous delivery" in caplog.text

    @pytest.mark.asyncio
    async def test_network_retry_counts_failed_request_against_interval(self, tb, monkeypatch):
        method = SendMessage(chat_id=-100, text="hello")
        started = []

        async def send_message(*args, **kwargs):
            started.append(asyncio.get_running_loop().time())
            if len(started) == 1:
                raise TelegramNetworkError(method=method, message="timeout")
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.03)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)

        result = await tb._tg_send_safe(-100, "hello", 77, important=True)

        assert result is not None
        assert started[1] - started[0] >= 0.025

    @pytest.mark.asyncio
    async def test_retries_bad_entities_as_plain_text(self, tb, monkeypatch):
        method = SendMessage(chat_id=-100, text="local path")

        async def send_message(*args, **kwargs):
            if kwargs.get("entities"):
                raise TelegramBadRequest(method=method, message="entity URL is invalid")
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        result = await tb._tg_send_safe(-100, "local path", 77, entities=[object()], important=True)

        assert result is not None
        assert tb.bot.send_message.await_count == 2
        assert tb.bot.send_message.await_args_list[1].kwargs["entities"] is None

    @pytest.mark.asyncio
    async def test_plain_entity_fallback_uses_a_new_rate_slot(self, tb, monkeypatch):
        method = SendMessage(chat_id=-100, text="local path")
        started = []

        async def send_message(*args, **kwargs):
            started.append(asyncio.get_running_loop().time())
            if kwargs.get("entities"):
                raise TelegramBadRequest(method=method, message="entity URL is invalid")
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.03)

        result = await tb._tg_send_safe(
            -100, "local path", 77, entities=[object()], important=True,
        )

        assert result is not None
        assert started[1] - started[0] >= 0.025

    @pytest.mark.asyncio
    async def test_coalesced_entity_fallback_uses_latest_payload(
        self, tb, monkeypatch,
    ):
        method = SendMessage(chat_id=-100, text="invalid entity")
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        plain_payloads = []

        async def send_message(chat_id, text, **kwargs):
            if text == "blocker":
                blocker_started.set()
                await release_blocker.wait()
                return object()
            if kwargs.get("entities"):
                raise TelegramBadRequest(
                    method=method,
                    message="entity URL is invalid",
                )
            plain_payloads.append(text)
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        blocker = asyncio.create_task(
            tb._tg_send_safe(-100, "blocker", 77, important=True),
        )
        await asyncio.wait_for(blocker_started.wait(), timeout=5)
        first = await tb._tg_send_safe(
            -100, "first", 77, entities=[object()], telemetry_key=("tool", 77),
        )
        second = await tb._tg_send_safe(
            -100, "second", 77, entities=[object()], telemetry_key=("tool", 77),
        )
        release_blocker.set()
        await asyncio.gather(blocker, first, second)

        assert plain_payloads == ["second\n\n⏱ 2 events coalesced"]

    @pytest.mark.asyncio
    async def test_optional_entity_fallback_handles_rejected_admission(
        self, tb, monkeypatch,
    ):
        method = SendMessage(chat_id=-100, text="invalid entity")
        entity_started = asyncio.Event()
        release_entity = asyncio.Event()

        async def send_message(*args, **kwargs):
            if kwargs.get("entities"):
                entity_started.set()
                await release_entity.wait()
                raise TelegramBadRequest(
                    method=method,
                    message="entity URL is invalid",
                )
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        delivery = await tb._tg_send_safe(
            -100,
            "mirror",
            77,
            entities=[object()],
            best_effort=True,
        )
        await asyncio.wait_for(entity_started.wait(), timeout=5)

        async def reject_fallback(*args, **kwargs):
            return None

        monkeypatch.setattr(tb, "_tg_call_safe", reject_fallback)
        release_entity.set()

        assert await delivery is None
        await tb._reset_tg_delivery_state()

    @pytest.mark.asyncio
    async def test_logs_lost_after_final_network_failure(self, tb, monkeypatch, caplog):
        method = SendMessage(chat_id=-100, text="hello")
        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = TelegramNetworkError(method=method, message="timeout")
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)

        result = await tb._tg_send_safe(-100, "hello", 77, important=True)

        assert result is None
        assert tb.bot.send_message.await_count == tb._TG_IMPORTANT_ATTEMPTS
        assert "LOST" in caplog.text


class TestTgReliableDeadlines:
    @pytest.mark.asyncio
    async def test_attempt_timeout_retries_then_releases_next_reply(
        self, tb, monkeypatch,
    ):
        never = asyncio.Event()
        slow_attempts = 0

        async def send_message(chat_id, text, **kwargs):
            nonlocal slow_attempts
            if text == "slow":
                slow_attempts += 1
                await never.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)
        monkeypatch.setattr(tb, "_TG_RELIABLE_CALL_TIMEOUT", 0.01, raising=False)
        monkeypatch.setattr(tb, "_TG_RELIABLE_TOTAL_TIMEOUT", 0.1, raising=False)

        slow = asyncio.create_task(
            tb._tg_send_safe(-100, "slow", 7, important=True),
        )
        reply = asyncio.create_task(
            tb._tg_send_safe(-100, "reply", 7, important=True),
        )
        slow_result, reply_result = await asyncio.wait_for(
            asyncio.gather(slow, reply),
            timeout=0.2,
        )
        snapshot = tb._tg_delivery_snapshot(-100)

        assert slow_result is None
        assert reply_result is not None
        assert slow_attempts == tb._TG_IMPORTANT_ATTEMPTS
        assert snapshot["reliable_timeouts"] == tb._TG_IMPORTANT_ATTEMPTS
        assert snapshot["reliable_lost"] == 1

    @pytest.mark.asyncio
    async def test_rate_wait_does_not_consume_attempt_retry_budget(
        self, tb, monkeypatch,
    ):
        class FakeLoop:
            now = 100.0

            def time(self):
                return self.now

        fake_loop = FakeLoop()
        state = tb._TgDeliveryState(loop=fake_loop)
        state.rate_history.extend([80.0] * tb._TG_GROUP_WINDOW_MAX)
        sleeps = []
        attempts = 0

        async def fake_sleep(delay):
            sleeps.append(delay)
            fake_loop.now += delay

        async def call():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError
            return object()

        monkeypatch.setattr(tb.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)

        result = await tb._tg_run_call(
            -100,
            state,
            call,
            True,
            "send_message",
            "reliable",
        )

        assert result is not None
        assert sleeps == [40.0]
        assert attempts == 2
        assert state.reliable_timeouts == 1
        assert state.reliable_total_timeouts == 0
        assert state.reliable_lost == 0

    @pytest.mark.asyncio
    async def test_snapshot_exposes_oldest_queue_age_and_delivery_latency(
        self, tb, monkeypatch,
    ):
        blocker_started = asyncio.Event()
        release = asyncio.Event()

        async def send_message(chat_id, text, **kwargs):
            if text == "blocker":
                blocker_started.set()
                await release.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        blocker = asyncio.create_task(
            tb._tg_send_safe(-100, "blocker", 7, important=True),
        )
        await asyncio.wait_for(blocker_started.wait(), timeout=5)
        queued = asyncio.create_task(
            tb._tg_send_safe(-100, "queued", 7, important=True),
        )
        await asyncio.sleep(0.01)

        waiting = tb._tg_delivery_snapshot(-100)
        assert waiting["reliable_queued"] == 1
        assert waiting["reliable_oldest_age"] >= 0.005

        release.set()
        await asyncio.gather(blocker, queued)
        delivered = tb._tg_delivery_snapshot(-100)

        assert delivered["reliable_last_latency"] >= 0.005
        assert delivered["reliable_max_latency"] >= delivered["reliable_last_latency"]


class TestTgMirrorIsolation:
    @pytest.mark.asyncio
    async def test_stalled_mirror_does_not_stop_primary_log_polling(
        self, tb, monkeypatch,
    ):
        mirror_started = asyncio.Event()
        release_mirror = asyncio.Event()
        second_primary = asyncio.Event()
        primary_texts = []
        log_calls = 0

        class FakeConn:
            def close(self):
                pass

        def get_logs(session_id, after_id=0, conn=None):
            nonlocal log_calls
            log_calls += 1
            if log_calls == 1:
                return []
            if log_calls == 2:
                return [
                    {"id": 1, "type": "text", "content": "first"},
                    {"id": 2, "type": "text", "content": "second"},
                ]
            return []

        async def send_safe(chat_id, text, *args, **kwargs):
            if chat_id == -200:
                mirror_started.set()
                await release_mirror.wait()
                return object()
            primary_texts.append(text)
            if len(primary_texts) == 2:
                second_primary.set()
            return object()

        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "scope": "/scope"}],
        )
        monkeypatch.setattr(
            "app.db.get_session_by_name",
            lambda name, scope: {"id": "sid"},
        )
        monkeypatch.setattr("app.db.get_logs", get_logs)
        monkeypatch.setattr("app.db._conn", FakeConn)
        monkeypatch.setattr(tb, "_schedule_topic_status", lambda *args: None)
        monkeypatch.setattr(tb, "_tg_send_safe", send_safe)
        tb.bot = object()
        tb.config["mirrors"] = {
            "orch": {"chat_id": -200, "topic_id": 99},
        }

        stream = asyncio.create_task(tb.stream_logs("orch", 42))
        try:
            await asyncio.wait_for(mirror_started.wait(), timeout=5)
            await asyncio.wait_for(second_primary.wait(), timeout=0.05)
        finally:
            release_mirror.set()
            stream.cancel()
            await asyncio.gather(stream, return_exceptions=True)
            mirror_task = getattr(tb, "_mirror_tasks", {}).get("orch")
            if mirror_task:
                mirror_task.cancel()
                await asyncio.gather(mirror_task, return_exceptions=True)

        assert len(primary_texts) == 2

    @pytest.mark.asyncio
    async def test_mirror_outbox_rejects_burst_beyond_fixed_capacity(
        self, tb, monkeypatch,
    ):
        release_mirror = asyncio.Event()
        send_started = asyncio.Event()

        async def send_safe(*args, **kwargs):
            send_started.set()
            await release_mirror.wait()
            return object()

        monkeypatch.setattr(tb, "_tg_send_safe", send_safe)
        monkeypatch.setattr(tb, "_TG_MIRROR_OUTBOX_MAX", 64, raising=False)
        tb.bot = object()
        tb.config["mirrors"] = {
            "orch": {"chat_id": -200, "topic_id": 99},
        }

        submissions = [
            asyncio.create_task(tb._mirror_send("orch", f"mirror-{i}"))
            for i in range(1000)
        ]
        try:
            await asyncio.wait_for(
                asyncio.gather(*submissions),
                timeout=5,
            )
            await asyncio.wait_for(send_started.wait(), timeout=5)
            snapshot = tb._mirror_delivery_snapshot("orch")

            assert snapshot["queued"] <= tb._TG_MIRROR_OUTBOX_MAX
            assert snapshot["dropped"] >= 935
        finally:
            release_mirror.set()
            await asyncio.gather(*submissions, return_exceptions=True)
            mirror_task = getattr(tb, "_mirror_tasks", {}).get("orch")
            if mirror_task:
                mirror_task.cancel()
                await asyncio.gather(mirror_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_optional_saturation_cannot_reject_primary_reliable_call(
        self, tb, monkeypatch,
    ):
        never = asyncio.Event()
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_OPTIONAL_QUEUE_MAX", 4)

        optional = [
            await tb._tg_call_safe(
                -200,
                never.wait,
                best_effort=True,
                optional_kind="mirror",
                label=f"mirror-{i}",
            )
            for i in range(20)
        ]

        delivered = await asyncio.wait_for(
            tb._tg_call_safe(
                -200,
                lambda: asyncio.sleep(0, result=object()),
                important=True,
                label="primary",
            ),
            timeout=5,
        )
        snapshot = tb._tg_delivery_snapshot(-200)

        assert delivered is not None
        assert sum(isinstance(item, asyncio.Future) for item in optional) == 4
        assert snapshot["optional_dropped"] == 16
        assert snapshot["reliable_overflow"] == 0
        await tb._reset_tg_delivery_state()

    @pytest.mark.asyncio
    async def test_two_mirrors_share_one_chat_rate_authority(
        self, tb, monkeypatch,
    ):
        async def send_message(*args, **kwargs):
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        tb.config["mirrors"] = {
            "orch-a": {"chat_id": -200, "topic_id": 1},
            "orch-b": {"chat_id": -200, "topic_id": 2},
        }
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.02)

        assert await tb._mirror_send("orch-a", "a") is True
        assert await tb._mirror_send("orch-b", "b") is True
        await asyncio.gather(*(
            outbox.join()
            for outbox in tb._mirror_outboxes.values()
        ))

        assert tb.bot.send_message.await_count == 1
        snapshot = tb._tg_delivery_snapshot(-200)
        assert snapshot["optional_dropped"] == 1
        assert len(tb._tg_delivery_states[-200].rate_history) == 1
        for task in list(tb._mirror_tasks.values()):
            task.cancel()
        await asyncio.gather(*list(tb._mirror_tasks.values()), return_exceptions=True)
        await tb._reset_tg_delivery_state()

    @pytest.mark.asyncio
    async def test_stop_cancels_mirror_owner_and_clears_outbox(
        self, tb, monkeypatch,
    ):
        send_started = asyncio.Event()
        never = asyncio.Event()

        async def send_safe(*args, **kwargs):
            send_started.set()
            await never.wait()

        tb.bot = AsyncMock()
        tb.config["mirrors"] = {
            "orch": {"chat_id": -200, "topic_id": 99},
        }
        monkeypatch.setattr(tb, "_tg_send_safe", send_safe)

        assert await tb._mirror_send("orch", "blocked") is True
        await asyncio.wait_for(send_started.wait(), timeout=5)
        await asyncio.wait_for(_real_stop_bridge(), timeout=5)

        assert tb._mirror_tasks == {}
        assert tb._mirror_outboxes == {}
        assert tb._mirror_stopping == set()

    @pytest.mark.asyncio
    async def test_stop_rejects_first_mirror_submission_during_reset(
        self, tb, monkeypatch,
    ):
        reset_started = asyncio.Event()
        release_reset = asyncio.Event()

        async def reset_delivery():
            reset_started.set()
            await release_reset.wait()

        tb.bot = AsyncMock()
        tb.config["mirrors"] = {
            "orch": {"chat_id": -200, "topic_id": 99},
        }
        monkeypatch.setattr(tb, "_reset_tg_delivery_state", reset_delivery)

        stopping = asyncio.create_task(_real_stop_bridge())
        await asyncio.wait_for(reset_started.wait(), timeout=5)
        accepted = await tb._mirror_send("orch", "late")
        release_reset.set()
        await asyncio.wait_for(stopping, timeout=5)

        try:
            assert accepted is False
            assert tb._mirror_tasks == {}
            assert tb._mirror_outboxes == {}
        finally:
            for task in list(tb._mirror_tasks.values()):
                task.cancel()
            await asyncio.gather(
                *list(tb._mirror_tasks.values()),
                return_exceptions=True,
            )


class TestTopicStatusDelivery:
    @pytest.mark.asyncio
    async def test_slow_topic_status_does_not_block_message_queue(self, tb, monkeypatch):
        edit_started = asyncio.Event()
        never_finishes = asyncio.Event()

        async def edit_forum_topic(*args, **kwargs):
            edit_started.set()
            await never_finishes.wait()

        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.side_effect = edit_forum_topic
        tb.bot.send_message.return_value = object()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_TG_TOPIC_STATUS_TIMEOUT", 0.01)
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        status_task = asyncio.create_task(tb._update_topic_status("orch", True))
        await asyncio.wait_for(edit_started.wait(), timeout=5)

        message = await asyncio.wait_for(
            tb._tg_send_safe(tb.config["group_id"], "reply", 42, important=True),
            timeout=5,
        )
        await status_task

        assert message is not None
        tb.bot.send_message.assert_awaited_once()
        tb.bot.edit_forum_topic.assert_awaited_once()
        assert tb._topic_status == {}

    @pytest.mark.asyncio
    async def test_sync_statuses_iterates_session_snapshot(self, tb, monkeypatch):
        def session(name):
            return type("Session", (), {
                "name": name,
                "role": "orchestrator",
                "is_orchestrator": True,
                "scope": f"/{name}",
            })()

        manager = type("Manager", (), {
            "sessions": {"orch-1": session("orch-1"), "orch-2": session("orch-2")},
        })()
        tb.bot = object()
        tb.config["topics"] = {"orch-1": 1, "orch-2": 2, "orch-3": 3}
        monkeypatch.setattr(tb, "_manager", manager)
        monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
        updated = []

        async def update(name, is_running):
            updated.append((name, is_running))
            if name == "orch-1":
                manager.sessions["orch-3"] = session("orch-3")

        monkeypatch.setattr(tb, "_update_topic_status", update)

        await tb._sync_all_topic_statuses()

        assert updated == [("orch-1", False), ("orch-2", False)]

    @pytest.mark.asyncio
    async def test_deferred_startup_iterates_topic_snapshot(self, tb, monkeypatch):
        streamed = []

        async def stream_logs(name, thread_id):
            streamed.append((name, thread_id))

        async def no_op():
            pass

        class MutatingTasks(list):
            def append(self, task):
                super().append(task)
                if len(self) == 1:
                    tb.config["topics"]["orch-3"] = 3

        tasks = MutatingTasks()
        tb.config["topics"] = {"orch-1": 1, "orch-2": 2}
        monkeypatch.setattr(tb, "_tasks", tasks)
        monkeypatch.setattr(tb, "ensure_topics", no_op)
        monkeypatch.setattr(tb, "_sync_all_topic_statuses", no_op)
        monkeypatch.setattr(tb, "stream_logs", stream_logs)
        monkeypatch.setattr(tb, "topic_sync_loop", no_op)

        await tb._deferred_startup()
        await asyncio.gather(*tasks)

        assert streamed == [("orch-1", 1), ("orch-2", 2)]


class TestTgLifecycleReliability:
    @pytest.mark.asyncio
    async def test_configured_stream_starts_before_blocked_topic_work(
        self, tb, monkeypatch,
    ):
        stream_started = asyncio.Event()
        blocked = asyncio.Event()

        async def stream_logs(name, thread_id):
            stream_started.set()
            await blocked.wait()

        async def blocked_ensure():
            await blocked.wait()

        async def no_op():
            pass

        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_tasks", [])
        monkeypatch.setattr(tb, "_stream_tasks", {}, raising=False)
        monkeypatch.setattr(tb, "stream_logs", stream_logs)
        monkeypatch.setattr(tb, "ensure_topics", blocked_ensure)
        monkeypatch.setattr(tb, "topic_sync_loop", no_op)

        startup = asyncio.create_task(tb._deferred_startup())
        try:
            await asyncio.wait_for(stream_started.wait(), timeout=0.05)
        finally:
            blocked.set()
            await asyncio.gather(startup, return_exceptions=True)
            for task in tb._tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tb._tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_new_topic_gets_one_stream_during_deferred_startup(
        self, tb, monkeypatch,
    ):
        release_stream = asyncio.Event()
        streamed = []
        tb.bot = AsyncMock()
        tb.bot.create_forum_topic.return_value = type(
            "Topic", (), {"message_thread_id": 42},
        )()
        tb.config["topics"] = {}
        monkeypatch.setattr(tb, "_manager", object())
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "role": "orchestrator"}],
        )
        monkeypatch.setattr(tb, "_tasks", [])
        monkeypatch.setattr(tb, "_stream_tasks", {}, raising=False)

        async def stream_logs(name, thread_id):
            streamed.append((name, thread_id))
            await release_stream.wait()

        async def no_op():
            pass

        monkeypatch.setattr(tb, "stream_logs", stream_logs)
        monkeypatch.setattr(tb, "_sync_all_topic_statuses", no_op)
        monkeypatch.setattr(tb, "topic_sync_loop", no_op)

        try:
            await tb._deferred_startup()
            await asyncio.sleep(0)
            assert streamed == [("orch", 42)]
        finally:
            release_stream.set()
            await asyncio.gather(*tb._tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_concurrent_topic_sync_serializes_creation(
        self, tb, monkeypatch,
    ):
        create_started = asyncio.Event()
        release_create = asyncio.Event()
        create_calls = 0

        async def create_forum_topic(**kwargs):
            nonlocal create_calls
            create_calls += 1
            create_started.set()
            await release_create.wait()
            return type("Topic", (), {"message_thread_id": 42})()

        tb.bot = AsyncMock()
        tb.bot.create_forum_topic.side_effect = create_forum_topic
        tb.config["topics"] = {}
        monkeypatch.setattr(tb, "_manager", object())
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "role": "orchestrator"}],
        )
        monkeypatch.setattr(tb, "_topic_create_tasks", {}, raising=False)
        monkeypatch.setattr(tb, "_stream_tasks", {}, raising=False)
        monkeypatch.setattr(tb, "stream_logs", AsyncMock())

        first = asyncio.create_task(tb.ensure_topics())
        second = asyncio.create_task(tb.ensure_topics())
        try:
            await asyncio.wait_for(create_started.wait(), timeout=0.05)
            await asyncio.sleep(0)
            assert create_calls == 1
        finally:
            release_create.set()
            await asyncio.gather(first, second, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_runtime_status_is_background_and_coalesces_latest_state(
        self, tb, monkeypatch,
    ):
        edit_started = asyncio.Event()
        release_edit = asyncio.Event()

        async def edit_forum_topic(**kwargs):
            edit_started.set()
            await release_edit.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.side_effect = edit_forum_topic
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_topic_status_tasks", {}, raising=False)
        monkeypatch.setattr(tb, "_topic_status_desired", {}, raising=False)
        monkeypatch.setattr(tb, "_any_running_in_scope", lambda _scope: False)
        monkeypatch.setattr(
            tb,
            "_wait_for_topic_status_idle_fade",
            AsyncMock(),
        )
        monkeypatch.setattr(
            tb,
            "_topic_status_scope",
            lambda _orch_name: "/scope",
        )

        try:
            await tb.notify_scope_running("orch")
            await edit_started.wait()
            await tb.check_scope_idle("orch", "/scope")
            assert len(tb._topic_status_tasks) == 1
        finally:
            tasks = list(tb._topic_status_tasks.values())
            release_edit.set()
            await asyncio.gather(*tasks, return_exceptions=True)

        assert tb.bot.edit_forum_topic.await_args_list[-1].kwargs[
            "icon_custom_emoji_id"
        ] == tb._ICON_IDLE

    @pytest.mark.asyncio
    async def test_topic_create_timeout_is_not_blindly_retried(
        self, tb, monkeypatch,
    ):
        never = asyncio.Event()

        async def create_forum_topic(**kwargs):
            await never.wait()

        tb.bot = AsyncMock()
        tb.bot.create_forum_topic.side_effect = create_forum_topic
        tb.config["topics"] = {}
        monkeypatch.setattr(tb, "_manager", object())
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "role": "orchestrator"}],
        )
        monkeypatch.setattr(tb, "_TG_TOPIC_CREATE_TIMEOUT", 0.01, raising=False)
        monkeypatch.setattr(tb, "_topic_create_tasks", {}, raising=False)

        await asyncio.wait_for(tb.ensure_topics(), timeout=0.05)
        await tb.ensure_topics()

        assert tb.bot.create_forum_topic.await_count == 1
        assert "primary:orch" in tb.config["topic_create_uncertain"]

    @pytest.mark.asyncio
    async def test_topic_create_network_error_is_not_blindly_retried(
        self, tb, monkeypatch,
    ):
        method = SendMessage(chat_id=-100, text="create placeholder")
        tb.bot = AsyncMock()
        tb.bot.create_forum_topic.side_effect = TelegramNetworkError(
            method=method,
            message="response lost",
        )
        tb.config["topics"] = {}
        monkeypatch.setattr(tb, "_manager", object())
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "role": "orchestrator"}],
        )

        await tb.ensure_topics()
        await tb.ensure_topics()

        assert tb.bot.create_forum_topic.await_count == 1
        assert "primary:orch" in tb.config["topic_create_uncertain"]

    @pytest.mark.asyncio
    async def test_stop_marks_inflight_topic_create_uncertain(
        self, tb, monkeypatch,
    ):
        create_started = asyncio.Event()
        never = asyncio.Event()

        async def create_forum_topic(**kwargs):
            create_started.set()
            await never.wait()

        tb.bot = AsyncMock()
        tb.bot.create_forum_topic.side_effect = create_forum_topic
        tb.config["topics"] = {}
        monkeypatch.setattr(
            tb,
            "_manager",
            type("Manager", (), {"tg_topics_remover": object()})(),
        )
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "role": "orchestrator"}],
        )

        creating = asyncio.create_task(tb.ensure_topics())
        await asyncio.wait_for(create_started.wait(), timeout=5)
        await _real_stop_bridge()
        await asyncio.gather(creating, return_exceptions=True)

        assert "primary:orch" in tb.config["topic_create_uncertain"]

    @pytest.mark.asyncio
    async def test_delete_then_recreate_replaces_owned_stream(
        self, tb, monkeypatch,
    ):
        releases = {42: asyncio.Event(), 43: asyncio.Event()}
        started = []

        async def stream_logs(name, thread_id):
            started.append((name, thread_id))
            await releases[thread_id].wait()

        tb.bot = AsyncMock()
        tb.bot.create_forum_topic.return_value = type(
            "Topic", (), {"message_thread_id": 43},
        )()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", object())
        monkeypatch.setattr(tb, "stream_logs", stream_logs)
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "role": "orchestrator"}],
        )

        old_task = tb._ensure_stream("orch", 42)
        await asyncio.sleep(0)
        await tb.remove_topics_for_orchs(["orch"])
        await tb.ensure_topics()
        await asyncio.sleep(0)

        assert old_task.cancelled()
        assert started == [("orch", 42), ("orch", 43)]
        assert list(tb._stream_tasks) == [("orch", 43)]

        releases[43].set()
        await asyncio.gather(
            *tb._stream_tasks.values(),
            return_exceptions=True,
        )

    @pytest.mark.asyncio
    async def test_stop_cancels_debounce_owner_and_clears_buffers(
        self, tb, monkeypatch,
    ):
        never = asyncio.Event()
        debounce = asyncio.create_task(never.wait())
        buf = tb._get_buf("sid")
        buf.debounce_task = debounce
        assert tb._buffers["sid"].debounce_task is debounce
        tb.bot = AsyncMock()
        tb.bot.session.close = AsyncMock()
        manager = type("Manager", (), {"tg_topics_remover": object()})()
        monkeypatch.setattr(tb, "_manager", manager)
        monkeypatch.setattr(tb, "_tasks", [])
        monkeypatch.setattr(tb, "_stream_tasks", {}, raising=False)
        monkeypatch.setattr(tb, "_topic_status_tasks", {}, raising=False)
        monkeypatch.setattr(tb, "_topic_create_tasks", {}, raising=False)

        try:
            await _real_stop_bridge()
            assert debounce.cancelled()
            assert tb._buffers == {}
        finally:
            if not debounce.done():
                debounce.cancel()
                await asyncio.gather(debounce, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_stop_clears_runtime_refs_when_bot_close_fails(self, tb):
        tb.bot = AsyncMock()
        tb.bot.session.close.side_effect = RuntimeError("close failed")
        tb._mirror_stopping.add("orch")

        with pytest.raises(RuntimeError, match="close failed"):
            await _real_stop_bridge()

        assert tb.bot is None
        assert tb._manager is None
        assert tb._mirror_stopping == set()


class TestMediaGenerationSafety:
    @staticmethod
    async def _resolve(tb, registration, content):
        if (
            isinstance(registration, tuple)
            and len(registration) == 2
            and isinstance(registration[1], int)
        ):
            await tb._resolve_media(*registration, content)
        else:
            await tb._resolve_media(registration, content)

    @staticmethod
    async def _expire_waiting_generation(tb, sid, monkeypatch):
        buf = tb._get_buf(sid)
        if buf.debounce_task and not buf.debounce_task.done():
            buf.debounce_task.cancel()
            await asyncio.gather(buf.debounce_task, return_exceptions=True)
        monkeypatch.setattr(tb, "DEBOUNCE_SEC", 0)
        monkeypatch.setattr(tb, "MEDIA_WAIT_MAX", 0)
        await tb._debounce_elapsed(sid)

    @staticmethod
    async def _cancel_debounce(buf):
        if buf.debounce_task and not buf.debounce_task.done():
            buf.debounce_task.cancel()
            await asyncio.gather(buf.debounce_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_stale_voice_cannot_overwrite_next_text_generation(
        self, tb, monkeypatch,
    ):
        session = type("Session", (), {"id": "sid"})()
        old_msg = type("Message", (), {"from_user": None})()
        new_msg = type("Message", (), {"from_user": None})()

        old = await tb._register_media(old_msg, session)
        await self._expire_waiting_generation(tb, "sid", monkeypatch)
        await tb._send_to_agent(new_msg, session, "new-msg")
        buf = tb._get_buf("sid")

        try:
            await self._resolve(tb, old, "OLD-VOICE")
            assert [entry[1] for entry in buf.entries] == ["new-msg"]
            assert buf.pending_media == 0
        finally:
            await self._cancel_debounce(buf)

    @pytest.mark.asyncio
    async def test_stale_voice_cannot_resolve_next_media_reservation(
        self, tb, monkeypatch,
    ):
        session = type("Session", (), {"id": "sid"})()
        msg = type("Message", (), {"from_user": None})()

        old = await tb._register_media(msg, session)
        await self._expire_waiting_generation(tb, "sid", monkeypatch)
        new = await tb._register_media(msg, session)
        buf = tb._get_buf("sid")

        try:
            await self._resolve(tb, old, "OLD-VOICE")
            assert buf.pending_media == 1
            assert buf.entries[0][1] is None

            await self._resolve(tb, new, "NEW-VOICE")
            assert buf.pending_media == 0
            assert buf.entries[0][1] == "NEW-VOICE"
        finally:
            await self._cancel_debounce(buf)

    @pytest.mark.asyncio
    async def test_stop_restart_buffer_identity_never_reuses_old_token(
        self, tb,
    ):
        session = type("Session", (), {"id": "sid"})()
        msg = type("Message", (), {"from_user": None})()

        old = await tb._register_media(msg, session)
        old_buf = tb._get_buf("sid")
        await self._cancel_debounce(old_buf)
        tb._buffers.clear()
        await self._resolve(tb, old, "OLD-BEFORE-RESTART")
        assert "sid" not in tb._buffers

        new = await tb._register_media(msg, session)
        new_buf = tb._get_buf("sid")
        try:
            await self._resolve(tb, old, "OLD-VOICE")
            assert new_buf.pending_media == 1
            assert new_buf.entries[0][1] is None

            await self._resolve(tb, new, "NEW-VOICE")
            assert new_buf.pending_media == 0
            assert new_buf.entries[0][1] == "NEW-VOICE"
        finally:
            await self._cancel_debounce(new_buf)

    @pytest.mark.asyncio
    async def test_media_token_is_single_use(self, tb):
        session = type("Session", (), {"id": "sid"})()
        msg = type("Message", (), {"from_user": None})()

        token = await tb._register_media(msg, session)
        buf = tb._get_buf("sid")
        try:
            await self._resolve(tb, token, "FIRST")
            await self._resolve(tb, token, "SECOND")

            assert buf.pending_media == 0
            assert buf.entries[0][1] == "FIRST"
        finally:
            await self._cancel_debounce(buf)

    @pytest.mark.asyncio
    async def test_valid_media_resolution_preserves_message_order(self, tb):
        session = type("Session", (), {"id": "sid"})()
        voice_msg = type("Message", (), {"from_user": None})()
        text_msg = type("Message", (), {"from_user": None})()

        voice = await tb._register_media(voice_msg, session)
        await tb._send_to_agent(text_msg, session, "later-text")
        buf = tb._get_buf("sid")
        try:
            await self._resolve(tb, voice, "voice-first")
            assert [entry[1] for entry in buf.entries] == [
                "voice-first",
                "later-text",
            ]
        finally:
            await self._cancel_debounce(buf)


class TestTgCallQueue:
    @pytest.mark.asyncio
    async def test_important_call_overtakes_waiting_nonimportant_call(self, tb, monkeypatch):
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        calls = []

        async def send_message(chat_id, text, **kwargs):
            calls.append(text)
            if text == "blocker":
                blocker_started.set()
                await release_blocker.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        blocker = asyncio.create_task(
            tb._tg_send_safe(-100, "blocker", 77, important=True),
        )
        await asyncio.wait_for(blocker_started.wait(), timeout=5)
        nonimportant = await tb._tg_send_safe(-100, "tool", 77)
        important = asyncio.create_task(
            tb._tg_send_safe(-100, "reply", 77, important=True),
        )
        await asyncio.sleep(0)
        release_blocker.set()

        await asyncio.gather(blocker, important, nonimportant)

        assert calls == ["blocker", "reply", "tool"]

    @pytest.mark.asyncio
    async def test_nonimportant_call_drops_when_rate_slot_would_wait(
        self, tb, monkeypatch,
    ):
        tb.bot = AsyncMock()
        tb.bot.send_message.return_value = object()
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 1.0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        first = await tb._tg_send_safe(
            -100, "tool-1", 77, telemetry_key=(77, "tool-1"),
        )
        assert await first is not None
        second = await tb._tg_send_safe(
            -100, "tool-2", 77, telemetry_key=(77, "tool-2"),
        )

        assert await second is None
        assert tb.bot.send_message.await_count == 1
        assert tb._tg_delivery_snapshot(-100)["telemetry_dropped"] == 1

    @pytest.mark.asyncio
    async def test_queued_edit_does_not_block_caller(self, tb, monkeypatch):
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()

        async def send_message(*args, **kwargs):
            blocker_started.set()
            await release_blocker.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        tb.bot.edit_message_text.return_value = object()
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        blocker = asyncio.create_task(
            tb._tg_send_safe(-100, "blocker", 77, important=True),
        )
        await asyncio.wait_for(blocker_started.wait(), timeout=5)
        edit = await tb._tg_edit_message_safe(-100, 5, "updated")

        assert isinstance(edit, asyncio.Task)
        tb.bot.edit_message_text.assert_not_awaited()
        release_blocker.set()
        await asyncio.gather(blocker, edit)
        tb.bot.edit_message_text.assert_awaited_once()


class TestTgCosmeticExpiry:
    @pytest.mark.asyncio
    async def test_expired_cosmetics_drop_before_reliable_selection_and_stats_show_it(
        self, tb,
    ):
        class FakeLoop:
            def time(self):
                return 30.0

        loop = asyncio.get_running_loop()
        state = tb._TgDeliveryState(loop=FakeLoop())
        reliable = tb._TgCallItem(
            call_factory=None,
            important=True,
            label="reply",
            future=loop.create_future(),
            enqueued_at=29.0,
        )
        telemetry = tb._TgCallItem(
            call_factory=None,
            important=False,
            label="tool",
            future=loop.create_future(),
            enqueued_at=10.0,
            key="tool",
            count=3,
        )
        optional = tb._TgCallItem(
            call_factory=None,
            important=False,
            label="mirror",
            future=loop.create_future(),
            enqueued_at=0.0,
        )
        state.reliable.append(reliable)
        state.telemetry["tool"] = telemetry
        state.optional.append(optional)
        tb._tg_delivery_states[-100] = state

        selected = tb._tg_pick_next(state)
        from app.routes import tg as tg_routes
        payload = await tg_routes.tg_delivery_stats()
        snapshot = payload["chats"][0]

        assert selected == ("reliable", reliable)
        assert await telemetry.future is None
        assert await optional.future is None
        assert snapshot["telemetry_dropped"] == 3
        assert snapshot["optional_dropped"] == 1
        assert snapshot["telemetry_pending"] == 0
        assert snapshot["optional_queued"] == 0

    @pytest.mark.asyncio
    async def test_fresh_cosmetic_never_preempts_reliable_backlog(self, tb):
        loop = asyncio.get_running_loop()
        state = tb._TgDeliveryState(loop=loop)

        def item(label, *, important, key=None):
            return tb._TgCallItem(
                call_factory=None,
                important=important,
                label=label,
                future=loop.create_future(),
                enqueued_at=loop.time(),
                key=key,
            )

        first = item("reply-1", important=True)
        second = item("reply-2", important=True)
        tool = item("tool", important=False, key="tool")
        state.reliable.extend([first, second])
        state.telemetry["tool"] = tool

        assert tb._tg_pick_next(state) == ("reliable", first)
        assert tb._tg_pick_next(state) == ("reliable", second)
        selected = tb._tg_pick_next(state)
        assert selected[0] == "telemetry"
        assert selected[1] is tool

    @pytest.mark.asyncio
    async def test_thousand_same_topic_tools_use_one_coalesced_entry(
        self, tb, monkeypatch,
    ):
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()
        calls = []

        async def send_message(chat_id, text, **kwargs):
            calls.append(text)
            if text == "blocker":
                blocker_started.set()
                await release_blocker.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0, raising=False)

        blocker = asyncio.create_task(
            tb._tg_send_safe(-100, "blocker", 77, important=True),
        )
        await asyncio.wait_for(blocker_started.wait(), timeout=5)
        tools = [
            await tb._tg_send_safe(-100, f"tool-{i}", 77)
            for i in range(1000)
        ]

        snapshot = tb._tg_delivery_snapshot(-100)
        assert snapshot["telemetry_pending"] == 1
        assert snapshot["telemetry_coalesced"] == 999
        assert len({id(result) for result in tools}) == 1

        release_blocker.set()
        await asyncio.gather(blocker, *tools)

        tool_calls = [text for text in calls if text.startswith("tool-")]
        assert len(tool_calls) == 1
        assert "tool-999" in tool_calls[0]
        assert "1000" in tool_calls[0]

    @pytest.mark.asyncio
    async def test_tool_timeout_releases_following_reliable_call(
        self, tb, monkeypatch,
    ):
        tool_started = asyncio.Event()
        never = asyncio.Event()
        calls = []

        async def send_message(chat_id, text, **kwargs):
            calls.append(text)
            if text == "tool":
                tool_started.set()
                await never.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0, raising=False)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_CALL_TIMEOUT", 0.01, raising=False)

        tool = await tb._tg_send_safe(-100, "tool", 77)
        await asyncio.wait_for(tool_started.wait(), timeout=5)
        reply = asyncio.create_task(
            tb._tg_send_safe(-100, "reply", 77, important=True),
        )

        await asyncio.wait_for(reply, timeout=5)
        assert await asyncio.wait_for(tool, timeout=5) is None
        assert calls == ["tool", "reply"]

    @pytest.mark.asyncio
    async def test_telemetry_key_capacity_drops_new_keys_without_tasks(
        self, tb, monkeypatch,
    ):
        blocker_started = asyncio.Event()
        release_blocker = asyncio.Event()

        async def send_message(chat_id, text, **kwargs):
            if text == "blocker":
                blocker_started.set()
                await release_blocker.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_KEYS", 3)

        blocker = asyncio.create_task(
            tb._tg_send_safe(-100, "blocker", 77, important=True),
        )
        await asyncio.wait_for(blocker_started.wait(), timeout=5)
        telemetry = [
            await tb._tg_send_safe(
                -100,
                f"tool-{i}",
                77,
                telemetry_key=(77, i),
            )
            for i in range(10)
        ]

        snapshot = tb._tg_delivery_snapshot(-100)
        assert snapshot["telemetry_pending"] == 3
        assert snapshot["telemetry_dropped"] == 7
        assert sum(result is None for result in telemetry) == 7
        assert len(tb._tg_result_tasks) == 3

        release_blocker.set()
        await asyncio.gather(
            blocker,
            *(result for result in telemetry if result is not None),
        )

    @pytest.mark.asyncio
    async def test_update_while_digest_is_sending_survives_old_completion(
        self, tb, monkeypatch,
    ):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        calls = []

        async def send_message(chat_id, text, **kwargs):
            calls.append(text)
            if text.startswith("tool-1"):
                first_started.set()
                await release_first.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0, raising=False)

        first = await tb._tg_send_safe(-100, "tool-1", 77)
        await asyncio.wait_for(first_started.wait(), timeout=5)
        second = await tb._tg_send_safe(-100, "tool-2", 77)
        release_first.set()

        await asyncio.gather(first, second)

        assert any(text.startswith("tool-1") for text in calls)
        assert any(text.startswith("tool-2") for text in calls)

    @pytest.mark.asyncio
    async def test_reliable_admission_and_reset_are_bounded(self, tb, monkeypatch):
        blocker_started = asyncio.Event()
        never = asyncio.Event()

        async def send_message(chat_id, text, **kwargs):
            if text == "blocker":
                blocker_started.set()
                await never.wait()
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_RELIABLE_QUEUE_MAX", 4, raising=False)
        monkeypatch.setattr(tb, "_TG_RELIABLE_ADMISSION_MAX", 2, raising=False)
        monkeypatch.setattr(tb, "_TG_RELIABLE_ADMISSION_TIMEOUT", 1, raising=False)

        blocker = asyncio.create_task(
            tb._tg_send_safe(-100, "blocker", 77, important=True),
        )
        await asyncio.wait_for(blocker_started.wait(), timeout=5)
        submissions = [
            asyncio.create_task(
                tb._tg_send_safe(-100, f"reply-{i}", 77, important=True),
            )
            for i in range(20)
        ]
        await asyncio.sleep(0.01)

        snapshot = tb._tg_delivery_snapshot(-100)
        assert snapshot["reliable_queued"] == 4
        assert snapshot["reliable_admission_waiters"] == 2
        assert snapshot["reliable_overflow"] == 14

        await tb._reset_tg_delivery_state()
        results = await asyncio.wait_for(
            asyncio.gather(blocker, *submissions, return_exceptions=True),
            timeout=5,
        )
        assert sum(
            isinstance(result, tb._TgDeliveryOverloaded)
            for result in results
        ) == 14
        assert sum(result is None for result in results) == 7


class TestSendFileRetry:
    @pytest.mark.asyncio
    async def test_recreates_files_for_primary_retry_and_async_mirror(
        self, tb, tmp_path, monkeypatch,
    ):
        path = tmp_path / "report.txt"
        path.write_text("hello")
        method = SendMessage(chat_id=-100, text="file placeholder")
        mirror_done = asyncio.Event()
        primary = type("M", (), {
            "message_id": 5,
            "chat": type("C", (), {"id": -100123456})(),
            "message_thread_id": 555,
        })()
        tb.bot = AsyncMock()

        async def send_document(*args, **kwargs):
            call_no = tb.bot.send_document.await_count
            if call_no == 1:
                raise TelegramNetworkError(method=method, message="timeout")
            if call_no == 3:
                mirror_done.set()
                return object()
            return primary

        tb.bot.send_document.side_effect = send_document
        tb.config["topics"] = {"worker-a": 555}
        tb.config["mirrors"] = {"worker-a": {"chat_id": -200, "topic_id": 666}}
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)

        result = await tb.send_file_to_tg(str(path), "cap", "/s", "worker-a", as_document=True)
        await asyncio.wait_for(mirror_done.wait(), timeout=5)

        assert result["ok"] is True
        assert tb.bot.send_document.await_count == 3
        files = [call.args[1] for call in tb.bot.send_document.await_args_list]
        assert len({id(file) for file in files}) == 3
        assert [
            call.kwargs["message_thread_id"]
            for call in tb.bot.send_document.await_args_list
        ] == [555, 555, 666]


class TestCronCommandTopicBoundary99:
    @pytest.mark.asyncio
    async def test_no_match_is_silent_but_match_reaches_topic_status(
        self, tb, monkeypatch,
    ):
        import app.bg_jobs as module

        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.return_value = object()
        tb.config["topics"] = {"orch": 42}

        session = type("Session", (), {
            "id": "intent-hunter",
            "parent_name": "orch",
            "last_task_sender": "orch",
        })()

        async def send(_message):
            await tb.notify_scope_running("orch")

        session.send = AsyncMock(side_effect=send)

        async def manager_send(_session_id, message, *, provenance):
            assert provenance.origin == "background_task"
            assert provenance.subtype == "cron_command"
            await session.send(message)

        session_manager = type("Manager", (), {
            "ensure_loaded": AsyncMock(return_value=session),
            # #82: цель ищется по неизменяемому id, а не по имени.
            "ensure_loaded_by_id": AsyncMock(return_value=session),
            "send": AsyncMock(side_effect=manager_send),
        })()
        manager = module.BgJobManager()
        manager.set_session_manager(session_manager)
        monkeypatch.setattr(
            module, "bg_get_job", lambda _job_id: {"target_session_id": "intent-hunter"},
        )
        monkeypatch.setattr(module, "bg_cron_should_fire", lambda _job_id: True)
        monkeypatch.setattr(module, "bg_update_output", lambda *_args: None)
        monkeypatch.setattr(module, "bg_cron_record_fire", lambda _job_id: None)
        outputs = [b"empty-1", b"empty-2", b"empty-3", b"empty-4", b"FOUND: 42"]

        async def create_process(*_args, **_kwargs):
            return type("Process", (), {
                "pid": 12345,
                "returncode": 0,
                "output": outputs.pop(0),
                "error": b"",
            })()

        async def communicate(process):
            return process.output, process.error

        monkeypatch.setattr(module, "_spawn_bg_process", create_process)
        monkeypatch.setattr(module, "_kill_proc", AsyncMock())
        monkeypatch.setattr(module, "_communicate_cron_command", communicate)

        for _ in range(4):
            await manager._fire_cron_command(
                "monitor",
                "python monitor.py",
                "^FOUND:",
                "new intent found",
                "intent-hunter",
                "/scope",
            )

        session.send.assert_not_awaited()
        tb.bot.edit_forum_topic.assert_not_awaited()

        await manager._fire_cron_command(
            "monitor",
            "python monitor.py",
            "^FOUND:",
            "new intent found",
            "intent-hunter",
            "/scope",
        )
        await asyncio.gather(*tb._topic_status_tasks.values())

        session_manager.send.assert_awaited_once()
        session.send.assert_awaited_once()
        tb.bot.edit_forum_topic.assert_awaited_once()


class TestTopicStatusHysteresis99:
    @staticmethod
    def _manager(status_value="idle"):
        status = SimpleNamespace(value=status_value)
        session = SimpleNamespace(
            name="orch",
            role="orchestrator",
            is_orchestrator=True,
            scope="/scope",
            status=status,
        )
        return SimpleNamespace(sessions={"orch": session}), status

    @pytest.mark.asyncio
    async def test_idle_waits_before_editing_topic(self, tb, monkeypatch):
        delay_started = asyncio.Event()
        release_delay = asyncio.Event()

        async def wait_for_idle_fade():
            delay_started.set()
            await release_delay.wait()

        manager, _status = self._manager()
        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.return_value = object()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", manager)
        monkeypatch.setattr(
            tb,
            "_wait_for_topic_status_idle_fade",
            wait_for_idle_fade,
        )

        task = tb._schedule_topic_status("orch", False)
        await delay_started.wait()
        tb.bot.edit_forum_topic.assert_not_awaited()

        release_delay.set()
        await task

        tb.bot.edit_forum_topic.assert_awaited_once()
        assert tb.bot.edit_forum_topic.await_args.kwargs[
            "icon_custom_emoji_id"
        ] == tb._ICON_IDLE

    @pytest.mark.asyncio
    async def test_running_cancels_four_pending_idle_transitions(
        self, tb, monkeypatch,
    ):
        delay_started = asyncio.Queue()
        never_release = asyncio.Event()

        async def wait_for_idle_fade():
            delay_started.put_nowait(True)
            await never_release.wait()

        manager, _status = self._manager()
        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.return_value = object()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", manager)
        monkeypatch.setattr(
            tb,
            "_wait_for_topic_status_idle_fade",
            wait_for_idle_fade,
        )

        for _ in range(4):
            idle_task = tb._schedule_topic_status("orch", False)
            await delay_started.get()
            running_task = tb._schedule_topic_status("orch", True)
            await asyncio.gather(idle_task, return_exceptions=True)
            await running_task

        tb.bot.edit_forum_topic.assert_awaited_once()
        assert tb.bot.edit_forum_topic.await_args.kwargs[
            "icon_custom_emoji_id"
        ] == tb._ICON_RUNNING

    @pytest.mark.asyncio
    async def test_idle_rechecks_current_scope_after_delay(self, tb, monkeypatch):
        delay_started = asyncio.Event()
        release_delay = asyncio.Event()

        async def wait_for_idle_fade():
            delay_started.set()
            await release_delay.wait()

        manager, status = self._manager()
        tb.bot = AsyncMock()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", manager)
        monkeypatch.setattr(
            tb,
            "_wait_for_topic_status_idle_fade",
            wait_for_idle_fade,
        )

        task = tb._schedule_topic_status("orch", False)
        await delay_started.wait()
        status.value = "running"
        release_delay.set()
        await task

        tb.bot.edit_forum_topic.assert_not_awaited()
        assert "orch" not in tb._topic_status

    @pytest.mark.asyncio
    async def test_startup_sync_serializes_topic_edits(self, tb, monkeypatch):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        calls = []

        def session(name):
            return SimpleNamespace(
                name=name,
                role="orchestrator",
                is_orchestrator=True,
                scope=f"/{name}",
                status=SimpleNamespace(value="idle"),
            )

        tb.bot = object()
        tb.config["topics"] = {"orch-1": 1, "orch-2": 2}
        monkeypatch.setattr(
            tb,
            "_manager",
            SimpleNamespace(sessions={
                "orch-1": session("orch-1"),
                "orch-2": session("orch-2"),
            }),
        )

        async def update(name, is_running):
            calls.append((name, is_running))
            if name == "orch-1":
                first_started.set()
                await release_first.wait()

        monkeypatch.setattr(tb, "_update_topic_status", update)

        sync_task = asyncio.create_task(tb._sync_all_topic_statuses())
        await first_started.wait()
        assert calls == [("orch-1", False)]

        release_first.set()
        await sync_task

        assert calls == [("orch-1", False), ("orch-2", False)]

    @pytest.mark.asyncio
    async def test_runtime_running_serializes_after_started_startup_idle(
        self, tb, monkeypatch,
    ):
        idle_started = asyncio.Event()
        release_idle = asyncio.Event()
        running_started = asyncio.Event()
        edits = []

        async def edit_forum_topic(**kwargs):
            edits.append(kwargs["icon_custom_emoji_id"])
            if kwargs["icon_custom_emoji_id"] == tb._ICON_IDLE:
                idle_started.set()
                await release_idle.wait()
            else:
                running_started.set()
            return object()

        manager, status = self._manager()
        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.side_effect = edit_forum_topic
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", manager)

        sync_task = asyncio.create_task(tb._sync_all_topic_statuses())
        await idle_started.wait()
        status.value = "running"
        running_task = tb._schedule_topic_status("orch", True)
        assert not running_started.is_set()

        release_idle.set()
        await running_task
        await sync_task

        assert tb._topic_status == {"orch": True}
        assert edits == [tb._ICON_IDLE, tb._ICON_RUNNING]

    @pytest.mark.asyncio
    async def test_startup_sync_interrupts_existing_idle_delay(
        self, tb, monkeypatch,
    ):
        delay_started = asyncio.Event()
        never_release = asyncio.Event()

        async def wait_for_idle_fade():
            delay_started.set()
            await never_release.wait()

        manager, _status = self._manager()
        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.return_value = object()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", manager)
        monkeypatch.setattr(
            tb,
            "_wait_for_topic_status_idle_fade",
            wait_for_idle_fade,
        )

        pending_idle = tb._schedule_topic_status("orch", False)
        await delay_started.wait()
        await tb._sync_all_topic_statuses()

        assert pending_idle.cancelled()
        tb.bot.edit_forum_topic.assert_awaited_once()
        assert tb._topic_status == {"orch": False}

    @pytest.mark.asyncio
    async def test_manifest_orchestrator_scope_can_fade_idle(
        self, tb, monkeypatch,
    ):
        manager, _status = self._manager()
        manager.sessions["orch"].role = "pm-glava"
        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.return_value = object()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", manager)
        monkeypatch.setattr(
            tb,
            "_wait_for_topic_status_idle_fade",
            AsyncMock(),
        )

        task = tb._schedule_topic_status("orch", False)
        await task

        tb.bot.edit_forum_topic.assert_awaited_once()
        assert tb._topic_status == {"orch": False}

    @pytest.mark.asyncio
    async def test_startup_sync_keeps_status_cache_debounce(self, tb, monkeypatch):
        manager, _status = self._manager()
        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.return_value = object()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", manager)

        await tb._sync_all_topic_statuses()
        await tb._sync_all_topic_statuses()

        tb.bot.edit_forum_topic.assert_awaited_once()
        assert tb._topic_status == {"orch": False}

    @pytest.mark.asyncio
    async def test_lifecycle_cancel_during_idle_delay_leaves_no_edit(
        self, tb, monkeypatch,
    ):
        delay_started = asyncio.Event()
        never_release = asyncio.Event()

        async def wait_for_idle_fade():
            delay_started.set()
            await never_release.wait()

        manager, _status = self._manager()
        tb.bot = AsyncMock()
        tb.config["topics"] = {"orch": 42}
        monkeypatch.setattr(tb, "_manager", manager)
        monkeypatch.setattr(
            tb,
            "_wait_for_topic_status_idle_fade",
            wait_for_idle_fade,
        )

        task = tb._schedule_topic_status("orch", False)
        await delay_started.wait()
        await tb._cancel_orch_lifecycle("orch")

        assert task.cancelled()
        assert "orch" not in tb._topic_status_tasks
        assert "orch" not in tb._topic_status_desired
        tb.bot.edit_forum_topic.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("error", "class_name"),
        [
            (TimeoutError(), "TimeoutError"),
            (
                TelegramBadRequest(
                    method=SendMessage(chat_id=-100, text="placeholder"),
                    message="TOPIC_ID_INVALID",
                ),
                "TelegramBadRequest",
            ),
        ],
    )
    async def test_topic_status_failure_logs_class_and_does_not_cache(
        self, tb, caplog, error, class_name,
    ):
        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.side_effect = error
        tb.config["topics"] = {"orch": 42}
        caplog.set_level("WARNING", logger=tb.logger.name)

        await tb._update_topic_status("orch", False)

        assert class_name in caplog.text
        assert "orch" not in tb._topic_status

    @pytest.mark.asyncio
    async def test_topic_not_modified_is_success_without_warning(
        self, tb, caplog,
    ):
        tb.bot = AsyncMock()
        tb.bot.edit_forum_topic.side_effect = TelegramBadRequest(
            method=SendMessage(chat_id=-100, text="placeholder"),
            message="TOPIC_NOT_MODIFIED",
        )
        tb.config["topics"] = {"orch": 42}
        caplog.set_level("WARNING", logger=tb.logger.name)

        await tb._update_topic_status("orch", False)

        assert "TG topic_status failed" not in caplog.text
        assert tb._topic_status == {"orch": False}


class TestSilentFallbacksAreLogged:
    """#108 T3: фолбэки остаются как есть, но перестают быть немыми.

    Поток управления НЕ менялся — добавлено только логирование. Самый дорогой
    случай: сбой markdown→entities деградирует КАЖДОЕ форматированное сообщение
    до плоского текста, и раньше об этом не было ни строки в логе.
    """

    def test_md_entities_fallback_logs_reason(self, tb, monkeypatch, caplog):
        def _boom(_text):
            raise ValueError("bad markdown")

        monkeypatch.setattr(tb, "md_convert", _boom)
        caplog.set_level("WARNING", logger=tb.logger.name)

        text, ents = tb._md_entities("**hello**")

        # фолбэк прежний: исходный текст, пустые entities
        assert (text, ents) == ("**hello**", [])
        # но теперь причина видна
        assert "ValueError" in caplog.text
        assert "bad markdown" in caplog.text

    def test_md_entities_success_path_unchanged(self, tb, caplog):
        caplog.set_level("WARNING", logger=tb.logger.name)
        text, ents = tb._md_entities("plain text")
        assert isinstance(text, str)
        assert "markdown→entities failed" not in caplog.text


class TestToolMessagesAllDelivered141:
    """#141: содержимое ВСЕХ вызовов тулов доходит до юзера, ничего не теряется."""

    @pytest.mark.asyncio
    async def test_burst_of_tool_calls_loses_no_content(self, tb, monkeypatch):
        calls = []

        async def send_message(chat_id, text, **kwargs):
            calls.append(text)
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        bucket = tb._tg_tool_batch(77, "orch")
        futures = [
            await tb._tg_send_safe(
                -100, f"tool-{i}", 77,
                telemetry_key=("tool", 77, "orch"),
                batch_bucket=bucket,
            )
            for i in range(24)
        ]
        await asyncio.gather(*[f for f in futures if f is not None])

        delivered = "\n".join(calls)
        missing = [i for i in range(24) if f"tool-{i}" not in delivered]
        assert not missing, f"потеряно: {missing}"
        assert tb._tg_delivery_snapshot(-100)["telemetry_dropped"] == 0

    @pytest.mark.asyncio
    async def test_reliable_text_not_blocked_by_tool_burst(self, tb, monkeypatch):
        calls = []

        async def send_message(chat_id, text, **kwargs):
            calls.append(text)
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        bucket = tb._tg_tool_batch(77, "orch")
        for i in range(24):
            await tb._tg_send_safe(
                -100, f"tool-{i}", 77,
                telemetry_key=("tool", 77, "orch"),
                batch_bucket=bucket,
            )
        await tb._tg_send_safe(-100, "ответ юзеру", 77, important=True)

        assert "ответ юзеру" in calls
        assert tb._tg_delivery_snapshot(-100)["reliable_overflow"] == 0

    @pytest.mark.asyncio
    async def test_batched_message_drops_stale_entities(self, tb, monkeypatch):
        """entities посчитаны под один body — в склейке их слать нельзя."""
        seen = []

        async def send_message(chat_id, text, **kwargs):
            seen.append((text, kwargs.get("entities")))
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        from aiogram.types import MessageEntity
        ent = [MessageEntity(type="bold", offset=0, length=4)]
        bucket = tb._tg_tool_batch(77, "orch")
        f1 = await tb._tg_send_safe(
            -100, "aaaa", 77, entities=ent,
            telemetry_key=("tool", 77, "orch"), batch_bucket=bucket,
        )
        f2 = await tb._tg_send_safe(
            -100, "bbbb", 77, entities=ent,
            telemetry_key=("tool", 77, "orch"), batch_bucket=bucket,
        )
        await asyncio.gather(*[f for f in (f1, f2) if f is not None])

        for text, entities in seen:
            if "\n\n" in text:
                assert entities is None, "склейка ушла со старыми offsets"

    @pytest.mark.asyncio
    async def test_large_bodies_split_across_messages_without_loss(
        self, tb, monkeypatch,
    ):
        """Батч не должен превышать лимит TG — иначе отказ убьёт всю пачку."""
        calls = []

        async def send_message(chat_id, text, **kwargs):
            calls.append(text)
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        bucket = tb._tg_tool_batch(77, "orch")
        body = "X" * 900
        futures = [
            await tb._tg_send_safe(
                -100, f"tool-{i}-{body}", 77,
                telemetry_key=("tool", 77, "orch"),
                batch_bucket=bucket,
            )
            for i in range(20)
        ]
        await asyncio.gather(*[f for f in futures if f is not None])
        for _ in range(30):
            if not bucket:
                break
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)

        delivered = "\n".join(calls)
        missing = [i for i in range(20) if f"tool-{i}-" not in delivered]
        assert not missing, f"потеряно: {missing}"
        assert not [c for c in calls if tb._utf16_len(c) > tb.TG_MSG_LIMIT]
        assert bucket == [], "хвост застрял в bucket"

    @pytest.mark.asyncio
    async def test_single_oversized_body_is_split_not_rejected(
        self, tb, monkeypatch,
    ):
        """Одно тело длиннее лимита TG режется, а не улетает в отказ целиком."""
        calls = []

        async def send_message(chat_id, text, **kwargs):
            calls.append(text)
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        bucket = tb._tg_tool_batch(77, "orch")
        future = await tb._tg_send_safe(
            -100, "tool-huge-" + "X" * 5000, 77,
            telemetry_key=("tool", 77, "orch"), batch_bucket=bucket,
        )
        if future is not None:
            await future

        assert not [c for c in calls if tb._utf16_len(c) > tb.TG_MSG_LIMIT]
        assert "tool-huge-" in "\n".join(calls)

    @pytest.mark.asyncio
    async def test_failed_send_returns_batch_to_bucket(self, tb, monkeypatch):
        """Упавшая отправка не должна молча съедать вынутые тела."""
        async def send_message(chat_id, text, **kwargs):
            raise RuntimeError("TG упал")

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        bucket = tb._tg_tool_batch(77, "orch")
        futures = [
            await tb._tg_send_safe(
                -100, f"tool-{i}", 77,
                telemetry_key=("tool", 77, "orch"), batch_bucket=bucket,
            )
            for i in range(4)
        ]
        await asyncio.gather(
            *[f for f in futures if f is not None], return_exceptions=True,
        )

        assert bucket, "тела исчезли вместе с упавшей отправкой"
        assert any("tool-0" in item for item in bucket)


class TestBackgroundSubagentFilter:
    """`subagent_end` carries both background Bash and real subagents.

    Live week: 1608 of 1612 events were background Bash. Announcing each as
    "Sub-agent done" both lied about delegation and ate the 20 msg/60 s budget.
    """

    def test_explicit_background_type_is_filtered(self, tb):
        assert tb._is_background_subagent(
            "Run tests | type=local_bash | id=bo6qcdg9w | status=completed"
        )

    def test_explicit_type_wins_over_id_shape(self, tb):
        """Type must be read on its own: an id-only check would miss this."""
        assert tb._is_background_subagent(
            "Run tests | type=local_bash | id=xyz123 | status=completed"
        )

    def test_real_subagents_are_kept(self, tb):
        assert not tb._is_background_subagent(
            "Ресёрч грантов | type=local_agent | id=a68c1b91c70e01ead | status=completed"
        )
        assert not tb._is_background_subagent(
            "wait | type=codex | id=t-1 | status=completed"
        )

    def test_empty_type_falls_back_to_id_shape(self, tb):
        """Real live rows: type is missing, only the id tells them apart."""
        assert tb._is_background_subagent(
            " | type= | id=bdtgmnypg | tool_use_id=toolu_01JW | status=stopped"
        )
        assert not tb._is_background_subagent(
            " | type= | id=a1d116686cc8ce | tool_use_id=toolu_01X5 | status=stopped"
        )

    def test_unparseable_content_is_kept(self, tb):
        """Unknown shape → announce it; silently dropping delegation is worse."""
        assert not tb._is_background_subagent("something unexpected")


def _notify_row(log_id: int, reason: str = "развилка: два пути, оба ломают учёт",
                tool_name: str = "mcp__orchestra__notify_user", args: str | None = None):
    """Строка журнала о РЕАЛЬНОМ вызове notify_user — как её пишет рантайм."""
    body = args if args is not None else json.dumps({"reason": reason}, ensure_ascii=False)
    return {
        "id": log_id,
        "type": "tool",
        "tool_name": tool_name,
        "tool_use_id": f"notify-{log_id}",
        "content": f"{tool_name}: {body}",
    }


class TestTurnEndMention:
    """ГДЕ и КАК уходит тег владельца. Условие «когда» переехало в #241 — оно живёт
    в `TestNotifyUserMention`, здесь остались только общие для обоих правил свойства.

    Разметки «финальное сообщение» на строке `text` НЕТ и быть не может: мост
    стримит журнал вперёд и в момент отправки текста не знает, будет ли ещё один.
    Живой замер (1384 хода оркестраторов): 4777 из 6161 строк `text` —
    промежуточные. Границу хода даёт отдельная durable-строка `status: turn ended (...)`,
    которую мост и так читает. Тег уходит на ней — отдельным important-сообщением,
    потому что сам `status` идёт по косметической полосе и может быть дропнут.
    """

    def test_mention_renders_as_clickable_entity_for_numeric_id(self, tb):
        """user_id → text_link `tg://user?id=`: уведомление приходит даже если
        username не резолвится. Проверяем сущность, а не подстроку."""
        converted, entities = tb._formatted_chunks(tb._mention_markup("123456"))[0]
        assert entities
        assert entities[0].type == "text_link"
        assert entities[0].url == "tg://user?id=123456"

    def test_username_is_passed_through(self, tb):
        assert "@DrSeedon" in tb._mention_markup("@DrSeedon")

    @staticmethod
    async def _run(
        tb, monkeypatch, logs, *, role="orchestrator", mention="@DrSeedon",
        capture_mirror=False,
    ):
        class FakeConn:
            def close(self):
                pass

        calls = 0

        def get_logs(session_id, after_id=0, conn=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                return []
            if calls == 2:
                return logs
            raise asyncio.CancelledError

        async def no_sleep(_delay):
            return None

        sent = []
        mirrored = []

        async def tg_send_safe(chat_id, text, thread_id, entities=None, important=False, **kw):
            sent.append({"text": text, "important": important, "entities": entities})

        async def mirror_send(_orch_name, text, **_kwargs):
            mirrored.append(text)

        monkeypatch.setattr(tb, "TG_USER_MENTION", mention)
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "scope": "/scope", "role": role}],
        )
        monkeypatch.setattr(
            "app.db.get_session_by_name", lambda name, scope: {"id": "sid"},
        )
        monkeypatch.setattr("app.db.get_logs", get_logs)
        monkeypatch.setattr("app.db._conn", FakeConn)
        monkeypatch.setattr(tb, "_schedule_topic_status", lambda *a: None)
        monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
        monkeypatch.setattr(tb, "_tg_send_safe", tg_send_safe)
        monkeypatch.setattr(tb, "_mirror_send", mirror_send)
        monkeypatch.setattr(tb.asyncio, "sleep", no_sleep)

        with pytest.raises(asyncio.CancelledError):
            await tb.stream_logs("orch", 42)
        return (sent, mirrored) if capture_mirror else sent

    @pytest.mark.asyncio
    async def test_intermediate_messages_carry_no_mention(self, tb, monkeypatch):
        """Ход ещё не кончился — тега нет вообще."""
        sent = await self._run(tb, monkeypatch, [
            {"id": 1, "type": "text", "content": "работаю"},
            {"id": 2, "type": "tool", "content": 'Bash: {"command":"ls"}'},
        ])
        assert not [m for m in sent if "@DrSeedon" in m["text"]]

    @pytest.mark.asyncio
    async def test_worker_turn_end_is_not_mentioned(self, tb, monkeypatch):
        """Воркеры шлют оркестратору, а не юзеру — дёргать его нечем."""
        sent = await self._run(tb, monkeypatch, [
            {"id": 1, "type": "text", "content": "DONE #1"},
            {"id": 2, "type": "status", "content": "turn ended (end_turn, 2 turns, $0.01 turn)"},
        ], role="worker")
        assert not [m for m in sent if "@DrSeedon" in m["text"]]

    @pytest.mark.asyncio
    async def test_turn_without_speech_is_not_mentioned(self, tb, monkeypatch):
        """Ход кончился, но юзеру ничего не сказали — уведомлять не о чем."""
        sent = await self._run(tb, monkeypatch, [
            {"id": 1, "type": "tool", "content": 'Bash: {"command":"ls"}'},
            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
        ])
        assert not [m for m in sent if "@DrSeedon" in m["text"]]

    @pytest.mark.asyncio
    async def test_exact_silent_turn_marker_is_not_delivered_or_mentioned(
        self, tb, monkeypatch,
    ):
        rows = [
            {"id": 1, "type": "text", "content": "[[ORCHESTRA:SILENT_TURN]]"},
            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
        ]

        sent, mirrored = await self._run(
            tb, monkeypatch, rows, capture_mirror=True,
        )

        assert not [m for m in sent if "ORCHESTRA:SILENT_TURN" in m["text"]]
        assert not [text for text in mirrored if "ORCHESTRA:SILENT_TURN" in text]
        assert not [m for m in sent if "@DrSeedon" in m["text"]]
        assert sent == [], sent
        assert mirrored == [], mirrored
        assert rows[0] == {
            "id": 1,
            "type": "text",
            "content": "[[ORCHESTRA:SILENT_TURN]]",
        }

    @pytest.mark.asyncio
    async def test_silent_turn_with_actions_keeps_completion_anchor(self, tb, monkeypatch):
        rows = [
            {"id": 1, "type": "tool", "content": 'Bash: {"command":"ls"}'},
            {"id": 2, "type": "text", "content": "[[ORCHESTRA:SILENT_TURN]]"},
            {"id": 3, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
        ]

        sent, mirrored = await self._run(
            tb, monkeypatch, rows, capture_mirror=True,
        )

        anchors = [m for m in sent if m["text"].startswith("━")]
        assert len(anchors) == 1, sent
        assert anchors[0]["text"].startswith("━" * 19)
        assert any(text.startswith("━") for text in mirrored)

    @pytest.mark.asyncio
    async def test_turn_without_actions_sends_no_empty_anchor(self, tb, monkeypatch):
        """Обычный ход, где агент только ответил текстом, не шлёт голую полосу.

        28.08.2026 юзер получил «━ ход окончен · 0 действий · $0.00» и прочитал это как
        сбой. Раньше пустой якорь подавлялся ТОЛЬКО для `[[ORCHESTRA:SILENT_TURN]]`;
        обычный ход без вызовов инструментов такую полосу отправлял.
        """
        rows = [
            {"id": 1, "type": "text", "content": "коротко ответил и всё"},
            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.00 turn)"},
        ]

        sent, _ = await self._run(tb, monkeypatch, rows, capture_mirror=True)

        anchors = [m for m in sent if m["text"].startswith("━")]
        assert anchors == [], f"пустой якорь не должен уходить юзеру: {anchors}"
        # Сам ответ агента при этом доставлен — гасим ТОЛЬКО полосу.
        assert any("коротко ответил" in m["text"] for m in sent), sent

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        [
            "_",
            "[[ORCHESTRA:SILENT_TURN]] ",
            "prefix [[ORCHESTRA:SILENT_TURN]]",
            "[[ORCHESTRA:SILENT_TURN]]\nexplanation",
        ],
    )
    async def test_silent_turn_near_misses_are_delivered(
        self, tb, monkeypatch, content,
    ):
        sent = await self._run(tb, monkeypatch, [
            {"id": 1, "type": "text", "content": content},
        ])

        assert len(sent) == 1
        assert sent[0]["text"].startswith("💬")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("log_type", "prefix"),
        [("user_message", "👤"), ("error", "❌")],
    )
    async def test_silent_marker_only_applies_to_agent_text(
        self, tb, monkeypatch, log_type, prefix,
    ):
        row = {
            "id": 1,
            "type": log_type,
            "content": "[[ORCHESTRA:SILENT_TURN]]",
        }
        if log_type == "user_message":
            row.update({
                "content": "[from:fake-agent] [[ORCHESTRA:SILENT_TURN]]",
                "origin": "user",
                "origin_detail": {"senders": ["user"]},
            })
        sent = await self._run(tb, monkeypatch, [row])

        assert len(sent) == 1
        assert sent[0]["text"].startswith(prefix)

    @pytest.mark.asyncio
    async def test_agent_speech_itself_is_not_tagged(self, tb, monkeypatch):
        """Регресс на прежнее поведение: тег на КАЖДОЙ строке text (78% из них —
        промежуточные) заменён тегом на границе хода."""
        sent = await self._run(tb, monkeypatch, [
            {"id": 1, "type": "text", "content": "шаг"},
        ])
        assert sent and "@DrSeedon" not in sent[0]["text"]

    @pytest.mark.asyncio
    async def test_replay_after_mention_does_not_duplicate_it(self, tb, monkeypatch):
        """Перегрузка на строке ПОСЛЕ тега не должна слать тег дважды.

        Курсор откатывается на начало пачки, но `turn ended` уже переигран не будет:
        рассылка идёт по строкам с id > last_id, а он сдвинут за границу хода.
        """
        class FakeConn:
            def close(self):
                pass

        rows = [
            _notify_row(1, reason="нужно решение"),
            {"id": 2, "type": "status", "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
            {"id": 3, "type": "error", "content": "後из фона"},
        ]
        calls = 0

        def get_logs(session_id, after_id=0, conn=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                return []
            if calls in (2, 3):
                return [r for r in rows if r["id"] > after_id]
            raise asyncio.CancelledError

        sent = []
        failed_once = False

        async def tg_send_safe(chat_id, text, thread_id, entities=None, important=False, **kw):
            nonlocal failed_once
            if text.startswith("❌") and not failed_once:
                failed_once = True
                raise tb._TgDeliveryOverloaded("queue full")
            sent.append({"text": text, "important": important})

        async def no_sleep(_delay):
            return None

        monkeypatch.setattr(tb, "TG_USER_MENTION", "@DrSeedon")
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "scope": "/scope", "role": "orchestrator"}],
        )
        monkeypatch.setattr(
            "app.db.get_session_by_name", lambda name, scope: {"id": "sid"},
        )
        monkeypatch.setattr("app.db.get_logs", get_logs)
        monkeypatch.setattr("app.db._conn", FakeConn)
        monkeypatch.setattr(tb, "_schedule_topic_status", lambda *a: None)
        monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
        monkeypatch.setattr(tb, "_tg_send_safe", tg_send_safe)
        monkeypatch.setattr(tb, "_mirror_send", AsyncMock())
        monkeypatch.setattr(tb.asyncio, "sleep", no_sleep)

        with pytest.raises(asyncio.CancelledError):
            await tb.stream_logs("orch", 42)

        assert len([m for m in sent if "@DrSeedon" in m["text"]]) == 1, sent


class TestNotifyUserMention:
    """#241: тег приходит ТОЛЬКО по явному вызову `notify_user` в этом ходе.

    Прежнее правило (#158) тегало на КАЖДОЙ границе хода оркестратора, где был текст,
    то есть и на рутине — сигнал «посмотри» обесценился. Теперь молчание это дефолт.
    Направление отказа: забыл вызвать → юзер прочитает позже (вреда нет); вызвал зря →
    прежнее шумное поведение. Опасного направления (проглотить явную просьбу) нет.
    """

    # staticmethod(...) обязателен: голая ссылка на функцию в теле класса становится
    # методом, и `self` уезжает в аргумент `tb` — тесты падают до единой проверки.
    _run = staticmethod(TestTurnEndMention._run)
    _END = {"id": 90, "type": "status",
            "content": "turn ended (end_turn, 1 turns, $0.01 turn)"}

    @pytest.mark.asyncio
    async def test_notify_call_mentions_and_shows_its_reason(self, tb, monkeypatch):
        sent = await self._run(tb, monkeypatch, [
            _notify_row(1, reason="кеш падает 93.6% → 15%"),
            {"id": 2, "type": "text", "content": "замер закончен"},
            dict(self._END),
        ])

        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
        assert len(mentions) == 1, sent
        assert "кеш падает 93.6% → 15%" in mentions[0]["text"]
        # Надёжная полоса: important=False молча дропается под нагрузкой.
        assert mentions[0]["important"] is True
        # И только ПОСЛЕ содержания, иначе уведомление опережает то, ради чего оно.
        assert sent.index(mentions[0]) == len(sent) - 1

    @pytest.mark.asyncio
    async def test_turn_without_notify_call_is_not_mentioned(self, tb, monkeypatch):
        """Ядро #241: текст в ходе БОЛЬШЕ не является поводом дёрнуть юзера."""
        sent = await self._run(tb, monkeypatch, [
            {"id": 1, "type": "text", "content": "промежуточный шаг"},
            {"id": 2, "type": "text", "content": "готово, жду ответа"},
            dict(self._END),
        ])

        assert sent, "ход без тула всё равно обязан доставить свой текст"
        assert not [m for m in sent if "@DrSeedon" in m["text"]]

    @pytest.mark.asyncio
    async def test_sub_orchestrator_notify_call_is_mentioned(self, tb, monkeypatch):
        """Суб-оркестратор тоже разговаривает с юзером — гейт по роли его пускает."""
        sent = await self._run(tb, monkeypatch, [
            _notify_row(1, reason="фаза закрыта, нужен выбор"),
            dict(self._END),
        ], role="sub-orchestrator")

        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
        assert len(mentions) == 1, sent
        assert "фаза закрыта, нужен выбор" in mentions[0]["text"]

    @pytest.mark.asyncio
    async def test_worker_notify_call_never_mentions(self, tb, monkeypatch):
        """Воркеры отчитываются оркестратору; тул у них есть, но тега быть не должно."""
        sent = await self._run(tb, monkeypatch, [
            _notify_row(1),
            {"id": 2, "type": "text", "content": "DONE #241"},
            dict(self._END),
        ], role="worker")

        assert not [m for m in sent if "@DrSeedon" in m["text"]]

    @pytest.mark.asyncio
    async def test_quoting_the_tool_name_in_text_does_not_mention(self, tb, monkeypatch):
        """Признак — СТРУКТУРНЫЙ: строка журнала ЕСТЬ вызов тула.

        Классификатор по имени тула в тексте тегал бы любого, кто это имя цитирует, —
        а объяснять устройство тега агенты будут именно текстом (замер #161).
        """
        quoted = _notify_row(1)["content"]
        sent = await self._run(tb, monkeypatch, [
            {"id": 1, "type": "text", "content": f"зови так: {quoted}"},
            {"id": 2, "type": "user_message", "content": quoted},
            dict(self._END),
        ])

        assert not [m for m in sent if "@DrSeedon" in m["text"]]

    @pytest.mark.asyncio
    async def test_another_orchestra_tool_does_not_mention(self, tb, monkeypatch):
        sent = await self._run(tb, monkeypatch, [
            _notify_row(1, tool_name="mcp__orchestra__send_message"),
            dict(self._END),
        ])

        assert not [m for m in sent if "@DrSeedon" in m["text"]]

    @pytest.mark.asyncio
    async def test_unreadable_args_still_mention_without_reason(self, tb, monkeypatch):
        """Разбор аргументов — побочная услуга; сигналом является САМ вызов.

        Потерять тег из-за нечитаемого `reason` значит проглотить явную просьбу —
        единственное по-настоящему опасное направление в этой задаче.
        """
        sent = await self._run(tb, monkeypatch, [
            _notify_row(1, args="{oops not json"),
            dict(self._END),
        ])

        assert len([m for m in sent if "@DrSeedon" in m["text"]]) == 1, sent

    @pytest.mark.asyncio
    async def test_next_turn_without_notify_is_not_mentioned(self, tb, monkeypatch):
        """Признак вызова обязан гаснуть на границе, иначе один вызов тегает навсегда."""
        sent = await self._run(tb, monkeypatch, [
            _notify_row(1, reason="первый"),
            {"id": 2, "type": "text", "content": "ответ"},
            {"id": 3, "type": "status",
             "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
            {"id": 4, "type": "text", "content": "рутина следующего хода"},
            {"id": 5, "type": "status",
             "content": "turn ended (end_turn, 1 turns, $0.02 turn)"},
        ])

        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
        assert len(mentions) == 1, sent
        assert "первый" in mentions[0]["text"]

    @pytest.mark.asyncio
    async def test_two_notified_turns_give_two_mentions(self, tb, monkeypatch):
        sent = await self._run(tb, monkeypatch, [
            _notify_row(1, reason="первый"),
            {"id": 2, "type": "status",
             "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
            _notify_row(3, reason="второй"),
            {"id": 4, "type": "status",
             "content": "turn ended (end_turn, 1 turns, $0.02 turn)"},
        ])

        mentions = [m["text"] for m in sent if "@DrSeedon" in m["text"]]
        assert len(mentions) == 2, sent
        assert "первый" in mentions[0] and "второй" in mentions[1]

    @pytest.mark.asyncio
    async def test_mention_survives_backpressure_replay(self, tb, monkeypatch):
        """Перегрузка на ⚡ откатывает курсор и ПЕРЕИГРЫВАЕТ строки хода.

        Признак вызова к этому моменту гасить нельзя: на повторе тул уже не переиграется,
        и наивная реализация молча потеряла бы ровно тот тег, ради которого её писали.
        """
        class FakeConn:
            def close(self):
                pass

        rows = [
            _notify_row(1, reason="инцидент на живой"),
            {"id": 2, "type": "text", "content": "подробности"},
            {"id": 3, "type": "status",
             "content": "turn ended (end_turn, 1 turns, $0.01 turn)"},
        ]
        calls = 0

        def get_logs(session_id, after_id=0, conn=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                return []
            if calls in (2, 3):
                return [r for r in rows if r["id"] > after_id]
            raise asyncio.CancelledError

        sent = []
        overloaded_once = False

        async def tg_send_safe(chat_id, text, thread_id, entities=None, important=False, **kw):
            nonlocal overloaded_once
            if text.startswith("⚡") and not overloaded_once:
                overloaded_once = True
                raise tb._TgDeliveryOverloaded("queue full")
            sent.append({"text": text, "important": important})

        async def no_sleep(_delay):
            return None

        monkeypatch.setattr(tb, "TG_USER_MENTION", "@DrSeedon")
        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "scope": "/scope", "role": "orchestrator"}],
        )
        monkeypatch.setattr(
            "app.db.get_session_by_name", lambda name, scope: {"id": "sid"},
        )
        monkeypatch.setattr("app.db.get_logs", get_logs)
        monkeypatch.setattr("app.db._conn", FakeConn)
        monkeypatch.setattr(tb, "_schedule_topic_status", lambda *a: None)
        monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
        monkeypatch.setattr(tb, "_tg_send_safe", tg_send_safe)
        monkeypatch.setattr(tb, "_mirror_send", AsyncMock())
        monkeypatch.setattr(tb.asyncio, "sleep", no_sleep)

        with pytest.raises(asyncio.CancelledError):
            await tb.stream_logs("orch", 42)

        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
        assert len(mentions) == 1, sent
        assert "инцидент на живой" in mentions[0]["text"]

    @pytest.mark.asyncio
    async def test_no_mention_configured_sends_nothing_extra(self, tb, monkeypatch):
        sent = await self._run(tb, monkeypatch, [
            _notify_row(1),
            {"id": 2, "type": "text", "content": "готово"},
            dict(self._END),
        ], mention="")

        # Считаем не длину (её задаёт свёртка хода), а факт: пустого тега нет, и
        # последним ушёл якорь — после него ничего не дописано.
        assert not [m for m in sent if "⬆️" in m["text"]]
        assert sent[-1]["text"].startswith("━")

    def test_reason_is_bounded_in_the_mention_line(self, tb):
        """Причина едет юзеру ЦЕЛИКОМ в журнал, но в тег — обрезанной: тег это сигнал."""
        line = tb._mention_markup("@DrSeedon", "д" * 400)

        assert len(line) < 300
        assert "…" in line


# ── #189: свёртка хода — строка на действие, ⚙️ и якорь ────────────────────
# Тела тулов взяты ДОСЛОВНО из живого журнала (logs.id 54910, 54916 и правка из
# сессии back): выдуманный пример здесь бесполезен — экранирование `\"` появляется
# именно у настоящей обёртки `/bin/bash -lc "..."`, которую пишет Codex.
LIVE_BASH_SED = (
    'Bash: {"command": "/bin/bash -lc \\"sed -n \'1,260p\' '
    '/home/kesha/orchestra/.codex/skills/vps-deploy/SKILL.md\\"", '
    '"cwd": "/home/kesha/orchestra", "_codex_item_id": "exec-6e1a295f"}'
)
LIVE_BASH_RG = (
    'Bash: {"command": "/bin/bash -lc \\"rg -n \\\\\\"def change_model\\\\\\" '
    'app/manager.py\\"", "cwd": "/home/kesha/orchestra"}'
)
LIVE_FILE_CHANGE = (
    'FileChange: {"changes": [{"path": "/home/kesha/orchestra/worktrees/'
    'home-kesha-projects-kesha-tg-bot/fix-image-json-buffer/claude_session.py", '
    '"kind": {"type": "update"}, "diff": "@@ -51,2 +51,5 @@\\n NORMAL = 1\\n'
    '+# comment\\n+CLAUDE_MAX_BUFFER_SIZE = 64\\n-old line\\n"}], '
    '"status": "inProgress"}'
)
LIVE_EDIT = (
    'Edit: {"file_path": "/home/kesha/orchestra/worktrees/home-kesha-orchestra/'
    'back/app/auth.py", "old_string": "def a():\\n    return 1", '
    '"new_string": "def a():\\n    return 2\\n    # tail"}'
)


class TestTurnFold:
    def test_bash_line_shows_command_without_shell_escaping(self, tb):
        name, body = LIVE_BASH_SED.split(":", 1)
        line = tb._tool_line(name.strip(), body.strip())
        assert line.startswith("🖥 ")
        assert "sed -n '1,260p'" in line
        assert "Bash" not in line          # в заголовке команда, а не имя тула
        assert len(line) <= tb._ACTION_LINE_MAX

        name, body = LIVE_BASH_RG.split(":", 1)
        line = tb._tool_line(name.strip(), body.strip())
        assert 'rg -n "def change_model"' in line
        assert "\\" not in line            # экранирование оболочки снято

    def test_file_change_and_edit_render_the_same_way(self, tb):
        name, body = LIVE_FILE_CHANGE.split(":", 1)
        codex = tb._tool_line(name.strip(), body.strip())
        name, body = LIVE_EDIT.split(":", 1)
        claude = tb._tool_line(name.strip(), body.strip())
        assert codex.startswith("✏️ ") and claude.startswith("✏️ ")
        assert "claude_session.py +2 −1" in codex, codex
        assert "app/auth.py +2 −1" in claude, claude
        assert "worktrees" not in codex and "worktrees" not in claude
        assert "{" not in codex and "diff" not in codex   # не сырой патч

    def test_anchor_stays_short_on_the_worst_turn(self, tb):
        actions = [f"🖥 {'очень длинная команда ' * 4}{i}" for i in range(157)]
        anchor = tb._turn_anchor(actions, 9999.0, "turn ended (…, $12.34 turn, …)")
        assert anchor.startswith("━")
        assert len(anchor) <= tb._ANCHOR_MAX_CHARS
        assert "157 действий" in anchor
        assert "$12.34" in anchor
        # ключевое: якорь идёт по надёжной полосе и обязан быть ОДНИМ сообщением
        assert len(tb._formatted_chunks(anchor)) == 1

    def test_progress_body_stays_bounded(self, tb):
        lines = [f"🖥 команда номер {i} {'x' * 50}" for i in range(157)]
        text = tb._progress_text(lines, 157, 300.0)
        assert len(text) <= tb._PROGRESS_MAX_CHARS + 64
        assert "…ещё" in text
        assert "157 действий" in text
        assert "5 мин" in text

    def test_result_mark_reports_size_and_error(self, tb):
        assert tb._result_mark("x" * 2115, False) == "2.1 КБ ✓"
        assert tb._result_mark("", None) == "0 б ✓"
        assert tb._result_mark("SyntaxError: bad\nmore", True).startswith("✗ SyntaxError")

    # ── состояние хода ────────────────────────────────────────────────────
    def test_state_is_idempotent_on_replay(self, tb):
        """Перегрузка очереди откатывает курсор и переигрывает строки журнала."""
        state = tb._TurnState()
        for _ in range(2):                      # вторая итерация = переигрывание
            state.add(1, "🖥 first", "call-1")
            state.add(2, "🖥 second", "call-2")
            state.close(3, "call-2", "1 КБ ✓")
            state.close(4, "call-1", "2 КБ ✓")
        assert len(state.actions) == 2
        assert state.all_lines() == ["🖥 first  2 КБ ✓", "🖥 second  1 КБ ✓"]

    def test_result_finds_its_own_call_when_tools_run_in_parallel(self, tb):
        state = tb._TurnState()
        state.add(1, "🖥 first", "call-1")
        state.add(2, "🖥 second", "call-2")
        state.close(3, "call-2", "мой ✓")       # результат ВТОРОГО пришёл первым
        assert state.line(2).endswith("мой ✓")
        assert state.line(1) == "🖥 first"

    def test_legacy_rows_without_tool_use_id_pair_fifo(self, tb):
        state = tb._TurnState()
        state.add(1, "🖥 first", "")
        state.add(2, "🖥 second", "")
        state.close(3, "", "A ✓")
        state.close(4, "", "B ✓")
        assert state.line(1).endswith("A ✓") and state.line(2).endswith("B ✓")

    def test_result_without_any_open_call_is_ignored(self, tb):
        state = tb._TurnState()
        state.close(1, "orphan", "1 КБ ✓")
        assert state.all_lines() == []


class TestReadImagePreview:

    @pytest.mark.asyncio
    async def test_read_image_uses_important_isolated_preview(
        self, tb, tmp_path, monkeypatch,
    ):
        image = tmp_path / "read.png"
        image.write_bytes(b"image")
        sent = asyncio.Event()
        captured = {}
        log_calls = 0

        class FakeConn:
            def close(self):
                pass

        def get_logs(session_id, after_id=0, conn=None):
            nonlocal log_calls
            log_calls += 1
            if log_calls == 1:
                return []
            if log_calls == 2:
                return [
                    {
                        "id": 1,
                        "type": "tool",
                        "content": (
                            f'Read: {{"file_path":"{image}"}}'
                        ),
                    },
                    {
                        "id": 2,
                        "type": "tool_result",
                        "content": '{"type": "image"}',
                    },
                ]
            return []

        async def send_file(*args, **kwargs):
            captured.update(kwargs)
            done = asyncio.get_running_loop().create_future()
            done.set_result(object())
            sent.set()
            return done

        monkeypatch.setattr(
            "app.db.get_all_sessions",
            lambda: [{"name": "orch", "scope": "/scope"}],
        )
        monkeypatch.setattr(
            "app.db.get_session_by_name",
            lambda name, scope: {"id": "sid"},
        )
        monkeypatch.setattr("app.db.get_logs", get_logs)
        monkeypatch.setattr("app.db._conn", FakeConn)
        monkeypatch.setattr(tb, "_schedule_topic_status", lambda *args: None)
        monkeypatch.setattr(tb, "_tg_send_file_safe", send_file)
        monkeypatch.setattr(tb, "_send_expandable", AsyncMock(return_value=object()))
        async def mirror_send(orch, text, **kw):
            # Зеркало отправляется ПОСЛЕ якоря в том же обходе строки: если перегрузка
            # приходит здесь, якорь уже ушёл, а курсор всё равно откатится.
            if overload_after_anchor and text.startswith("━") and calls["anchor"] == 1:
                raise tb._TgDeliveryOverloaded("mirror full")
        monkeypatch.setattr(tb, "_mirror_send", mirror_send)

        stream = asyncio.create_task(tb.stream_logs("orch", 42))
        try:
            await asyncio.wait_for(sent.wait(), timeout=5)
        finally:
            stream.cancel()
            await asyncio.gather(stream, return_exceptions=True)

        assert captured["important"] is True
        assert captured["isolated_preview"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "marked"),
    [
        ('câ{"cmd":"pwd"}</parameter>\n</invoke>', True),
        ("The invoke helper receives a parameter and returns normally.", False),
        (
            "Documentation example:\n```xml\n<function_calls>\n"
            '<invoke name="Bash"><parameter name="cmd">pwd</parameter></invoke>\n'
            "```",
            False,
        ),
    ],
)
async def test_text_tool_call_marker_reaches_topic_and_mirror(
    tb, monkeypatch, content, marked,
):
    log_calls = 0

    class FakeConn:
        def close(self):
            pass



class TestTurnFoldStream:
    """Поток целиком: что мост РЕАЛЬНО отправляет за ход."""

    @pytest.mark.asyncio
    async def test_rate_limit_raw_stays_in_logs_but_not_user_channel(
        self, tb, monkeypatch,
    ):
        """Claude raw rate-limit telemetry is durable status, not user-facing status."""
        from app.events import AgentEvent
        from app.session import AgentSession

        raw_content = 'RATE_LIMIT_RAW {"utilization":0.16327272727272726}'
        persisted = []
        session = AgentSession(
            id="sid", name="orch", scope="/s", cwd="/tmp",
            model="claude-sonnet-5[1m]", system_prompt="test",
        )
        monkeypatch.setattr(
            session, "_log",
            lambda log_type, content, **kwargs: persisted.append({
                "id": 1, "type": log_type, "content": content,
            }),
        )
        session._handle_event(AgentEvent("status", raw_content))

        assert persisted == [{"id": 1, "type": "status", "content": raw_content}]
        sent, _, _ = await self._run(tb, monkeypatch, [persisted])

        # Anchor on the bridge's own primary-TG send node, not the whole event stream.
        assert not [item for item in sent if raw_content in item["text"]]

    async def _run(self, tb, monkeypatch, batches, overload_first_anchor=False,
                   overload_after_anchor=False):
        sent, expandables, edits = [], [], []
        calls = {"n": 0, "anchor": 0}

        def get_logs(session_id, after_id=0, conn=None):
            # Первый вызов stream_logs делает ДО цикла — им он берёт стартовый курсор.
            i = calls["n"] - 1
            calls["n"] += 1
            if i < 0:
                return []
            if i >= len(batches):
                raise asyncio.CancelledError
            return [dict(r) for r in batches[i]]

        async def send_safe(chat_id, text, thread_id=None, **kw):
            if text.startswith("━"):
                calls["anchor"] += 1
                if overload_first_anchor and calls["anchor"] == 1:
                    raise tb._TgDeliveryOverloaded("full")
            sent.append({"text": text, "important": kw.get("important", False)})
            return SimpleNamespace(message_id=len(sent))

        async def send_expandable(chat_id, thread_id, header, body, **kw):
            expandables.append(f"{header}\n{body}")
            return SimpleNamespace(message_id=100 + len(expandables))

        async def edit_safe(chat_id, message, text, entities=None, **kw):
            edits.append(text)
            return True

        monkeypatch.setattr("app.db.get_all_sessions",
                            lambda: [{"name": "orch", "scope": "/s", "role": "orchestrator"}])
        monkeypatch.setattr("app.db.get_session_by_name", lambda n, s: {"id": "sid"})
        monkeypatch.setattr("app.db.get_logs", get_logs)
        monkeypatch.setattr("app.db._conn", lambda: SimpleNamespace(close=lambda: None))
        monkeypatch.setattr(tb, "_schedule_topic_status", lambda *a: None)
        monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
        monkeypatch.setattr(tb, "_tg_send_safe", send_safe)
        monkeypatch.setattr(tb, "_send_expandable", send_expandable)
        monkeypatch.setattr(tb, "_tg_edit_message_safe", edit_safe)
        async def mirror_send(orch, text, **kw):
            # Зеркало отправляется ПОСЛЕ якоря в том же обходе строки: если перегрузка
            # приходит здесь, якорь уже ушёл, а курсор всё равно откатится.
            if overload_after_anchor and text.startswith("━") and calls["anchor"] == 1:
                raise tb._TgDeliveryOverloaded("mirror full")
        monkeypatch.setattr(tb, "_mirror_send", mirror_send)
        monkeypatch.setattr(tb.asyncio, "sleep", AsyncMock())
        with pytest.raises(asyncio.CancelledError):
            await tb.stream_logs("orch", 42)
        return sent, expandables, edits

    @pytest.mark.asyncio
    async def test_tool_rows_never_send_their_own_message(self, tb, monkeypatch):
        sent, expandables, edits = await self._run(tb, monkeypatch, [[
            {"id": 1, "type": "tool", "content": LIVE_BASH_SED, "tool_use_id": "c1"},
            {"id": 2, "type": "tool_result", "content": "x" * 2115, "tool_use_id": "c1"},
        ]])
        assert sent == []                      # ни одного сообщения на тул
        assert len(expandables) == 1           # только ⚙️
        assert expandables[0].startswith("⚙️ 1 действие")
        assert "sed -n '1,260p'" in expandables[0]

    @pytest.mark.asyncio
    async def test_engine_status_dropped_user_status_becomes_action(self, tb, monkeypatch):
        monkeypatch.setattr(tb, "_PROGRESS_MIN_INTERVAL", 0.0)
        sent, expandables, edits = await self._run(tb, monkeypatch, [[
            {"id": 1, "type": "status", "content": "codex turn=019f started"},
            {"id": 2, "type": "status", "content": 'precompact timer scheduled: {"a": 1}'},
            {"id": 3, "type": "status", "content": "message steered into active Codex turn"},
        ]])
        assert sent == []
        assert len(expandables) == 1
        assert "↪ сообщение вошло в текущий ход" in expandables[0]

    @pytest.mark.asyncio
    async def test_turn_end_sends_exactly_one_reliable_anchor(self, tb, monkeypatch):
        sent, _, _ = await self._run(tb, monkeypatch, [[
            {"id": 1, "type": "tool", "content": LIVE_BASH_SED, "tool_use_id": "c1"},
            {"id": 2, "type": "status",
             "content": "turn ended (end_turn, 0 turns, $1.60 turn, ctx:46%)"},
        ]])
        anchors = [m for m in sent if m["text"].startswith("━")]
        assert len(anchors) == 1
        assert anchors[0]["important"] is True      # надёжная полоса, иначе потеряется
        assert "1 действие" in anchors[0]["text"] and "$1.60" in anchors[0]["text"]

    @pytest.mark.asyncio
    async def test_replayed_turn_end_does_not_duplicate_the_anchor(self, tb, monkeypatch):
        """Перегрузка откатывает курсор — строки хода проигрываются ВТОРОЙ раз."""
        batch = [
            {"id": 1, "type": "tool", "content": LIVE_BASH_SED, "tool_use_id": "c1"},
            {"id": 2, "type": "status",
             "content": "turn ended (end_turn, 0 turns, $1.60 turn, ctx:46%)"},
        ]
        sent, expandables, _ = await self._run(
            tb, monkeypatch, [batch, batch], overload_first_anchor=True,
        )
        anchors = [m for m in sent if m["text"].startswith("━")]
        assert len(anchors) == 1, anchors
        assert "1 действие" in anchors[0]["text"]   # действие не задвоилось

    @pytest.mark.asyncio
    async def test_anchor_is_not_resent_when_its_row_replays_after_delivery(
        self, tb, monkeypatch,
    ):
        """Якорь УЖЕ ушёл, а строка переигрывается: падение случилось позже, на той же
        строке журнала. Без отметки `_anchor_sent_for` юзер получил бы два якоря."""
        batch = [
            {"id": 1, "type": "tool", "content": LIVE_BASH_SED, "tool_use_id": "c1"},
            {"id": 2, "type": "status",
             "content": "turn ended (end_turn, 0 turns, $1.60 turn, ctx:46%)"},
        ]
        sent, _, _ = await self._run(
            tb, monkeypatch, [batch, batch], overload_after_anchor=True,
        )
        anchors = [m for m in sent if m["text"].startswith("━")]
        assert len(anchors) == 1, anchors

    @pytest.mark.asyncio
    async def test_progress_edit_is_throttled_and_skips_identical_text(self, tb, monkeypatch):
        rows = [{"id": i, "type": "tool", "content": LIVE_BASH_SED,
                 "tool_use_id": f"c{i}"} for i in range(1, 6)]
        _, expandables, edits = await self._run(tb, monkeypatch, [rows])
        assert len(expandables) == 1
        assert edits == []          # пять действий за секунду — ни одной лишней правки

    @pytest.mark.asyncio
    async def test_parallel_results_land_on_their_own_calls(self, tb, monkeypatch):
        """Живой порядок из журнала (logs.id 54877-54880): два вызова подряд, потом два
        результата, причём ПЕРВЫЙ результат принадлежит ВТОРОМУ вызову. По соседству
        такую пару не сшить — только по tool_use_id, который пишется с #174."""
        monkeypatch.setattr(tb, "_PROGRESS_MIN_INTERVAL", 0.0)
        _, expandables, edits = await self._run(tb, monkeypatch, [[
            {"id": 54877, "type": "tool", "tool_use_id": "bash-1",
             "content": 'Bash: {"command": "/bin/bash -lc \'codex mcp list\'"}'},
            {"id": 54878, "type": "tool", "tool_use_id": "search-1",
             "content": 'WebSearch: {"query": "GPT-5.6-Cyber"}'},
            {"id": 54879, "type": "tool_result", "tool_use_id": "search-1",
             "content": "x" * 3000},                       # 2.9 КБ — ответ поиска
            {"id": 54880, "type": "tool_result", "tool_use_id": "bash-1",
             "content": "Codex CLI\nUsage: codex"},        # 22 б — ответ баша
        ]])
        final = (edits or expandables)[-1]
        assert "🖥 codex mcp list  22 б ✓" in final, final
        assert "🌐 GPT-5.6-Cyber  2.9 КБ ✓" in final, final

    @pytest.mark.asyncio
    async def test_mention_survives_replay_of_an_already_sent_anchor(self, tb, monkeypatch):
        """Якорь ушёл, зеркало упало, строка переигралась. Пропустить надо ТОЛЬКО
        повтор якоря: тег владельца живёт дальше по той же строке журнала."""
        monkeypatch.setattr(tb, "TG_USER_MENTION", "@DrSeedon")
        batch = [
            _notify_row(1, reason="жду ответа"),
            {"id": 2, "type": "text", "content": "готово, жду ответа"},
            {"id": 3, "type": "status",
             "content": "turn ended (end_turn, 0 turns, $1.60 turn)"},
        ]
        sent, _, _ = await self._run(
            tb, monkeypatch, [batch, batch], overload_after_anchor=True,
        )
        anchors = [m for m in sent if m["text"].startswith("━")]
        mentions = [m for m in sent if "@DrSeedon" in m["text"]]
        assert len(anchors) == 1, anchors
        assert len(mentions) == 1, sent          # тег не потерян и не задвоен
        assert mentions[0]["important"] is True

    def test_progress_body_respects_utf16_limit(self, tb):
        """Telegram считает лимит в UTF-16: эмодзи вне BMP весит две единицы, и
        формально короткое тело может не влезть в правку сообщения."""
        lines = ["🖥 " + "🧨" * 60 for _ in range(40)]
        text = tb._progress_text(lines, 40, 60.0)
        assert tb._utf16_len(text) <= tb._PROGRESS_MAX_CHARS + 64
        assert len(tb._formatted_chunks(text)) == 1

    @pytest.mark.asyncio
    async def test_late_message_id_does_not_leak_into_the_next_block(self, tb, monkeypatch):
        """Отправка ⚙️ доехала уже после того, как текст юзеру начал новую пачку."""
        state = tb._TurnState()
        state.add(1, "🖥 first")
        loop = asyncio.get_running_loop()
        pending = loop.create_future()

        async def send_expandable(chat_id, thread_id, header, body, **kw):
            return pending

        monkeypatch.setattr(tb, "_send_expandable", send_expandable)
        monkeypatch.setattr(tb, "config", {"group_id": -100})
        await tb._update_progress(state, 42, "orch", force=True)
        state.new_block()                       # 💬 юзеру: пачка сменилась
        pending.set_result(SimpleNamespace(message_id=777))
        await asyncio.sleep(0)
        assert state.msg_id is None, "message_id прошлой пачки утёк в новую"

    def test_anchor_bar_is_one_line_wide(self, tb):
        """Ширина полосы — 19 знаков: на 20 пузырь переносил её на вторую строку."""
        anchor = tb._turn_anchor(["🖥 a"] * 3, 300.0, "turn ended ($0.10 turn)")
        bar = anchor.splitlines()[0]
        assert bar == "━" * 19
        assert len(bar) == tb._ANCHOR_BAR_WIDTH == 19
