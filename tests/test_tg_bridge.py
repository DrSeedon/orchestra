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
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage
from app.tg_bridge import stop_bridge as _real_stop_bridge


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
async def test_polling_does_not_override_uvicorn_signal_handlers(tb):
    dispatcher = AsyncMock()
    dispatcher.start_polling.side_effect = asyncio.CancelledError
    bot = object()
    tb.dp = dispatcher
    tb.bot = bot

    with pytest.raises(asyncio.CancelledError):
        await tb._safe_polling()

    dispatcher.start_polling.assert_awaited_once_with(bot, handle_signals=False)


@pytest.mark.asyncio
async def test_transcribe_audio_persists_voice_cost(tb, tmp_path, monkeypatch):
    db_path = tmp_path / "voice-cost.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import _conn, init_db
    init_db()

    audio_path = tmp_path / "voice.oga"
    audio_path.write_bytes(b"audio")
    tb.DEEPGRAM_API_KEY = "test-key"
    tb._transcription_cache = {}
    monkeypatch.setattr(tb, "_save_transcription_cache", lambda cache: None)

    payload = {
        "metadata": {"duration": 90.0},
        "results": {"channels": [{"alternatives": [{"transcript": "hello"}]}]},
    }

    class FakeResponse:
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


# ── _diff_images_enabled ───────────────────────────────────────────────────


class TestDiffImagesEnabled:
    def test_default_true_without_env(self, tb, monkeypatch):
        """`_diff_images_enabled()` без TG_DIFF_IMAGES = True (при наличии PIL)."""
        tb._pil_available = True
        monkeypatch.delenv("TG_DIFF_IMAGES", raising=False)
        assert tb._diff_images_enabled() is True

    def test_false_when_env_false(self, tb, monkeypatch):
        """TG_DIFF_IMAGES=false → False."""
        tb._pil_available = True
        monkeypatch.setenv("TG_DIFF_IMAGES", "false")
        assert tb._diff_images_enabled() is False

    def test_false_when_env_zero(self, tb, monkeypatch):
        """TG_DIFF_IMAGES=0 → False."""
        tb._pil_available = True
        monkeypatch.setenv("TG_DIFF_IMAGES", "0")
        assert tb._diff_images_enabled() is False

    def test_false_when_env_no(self, tb, monkeypatch):
        """TG_DIFF_IMAGES=no → False."""
        tb._pil_available = True
        monkeypatch.setenv("TG_DIFF_IMAGES", "no")
        assert tb._diff_images_enabled() is False

    def test_true_when_env_true(self, tb, monkeypatch):
        """TG_DIFF_IMAGES=true → True."""
        tb._pil_available = True
        monkeypatch.setenv("TG_DIFF_IMAGES", "true")
        assert tb._diff_images_enabled() is True

    def test_false_when_pil_missing(self, tb, monkeypatch):
        """Без Pillow → False даже при TG_DIFF_IMAGES=true."""
        tb._pil_available = False
        monkeypatch.setenv("TG_DIFF_IMAGES", "true")
        assert tb._diff_images_enabled() is False


# ── _result_images_enabled ─────────────────────────────────────────────────


class TestResultImagesEnabled:
    def test_default_true_without_env(self, tb, monkeypatch):
        """`_result_images_enabled()` без TG_RESULT_IMAGES = True (opt-out)."""
        tb._pil_available = True
        monkeypatch.delenv("TG_RESULT_IMAGES", raising=False)
        assert tb._result_images_enabled() is True

    def test_true_when_env_true(self, tb, monkeypatch):
        """TG_RESULT_IMAGES=true → True."""
        tb._pil_available = True
        monkeypatch.setenv("TG_RESULT_IMAGES", "true")
        assert tb._result_images_enabled() is True

    def test_false_when_pil_missing(self, tb, monkeypatch):
        """Без Pillow → False даже при TG_RESULT_IMAGES=true."""
        tb._pil_available = False
        monkeypatch.setenv("TG_RESULT_IMAGES", "true")
        assert tb._result_images_enabled() is False


# ── _check_pil ──────────────────────────────────────────────────────────────


class TestCheckPil:
    def test_caches_result(self, tb, monkeypatch):
        """Повторный вызов не перепроверяет — кеш в _pil_available."""
        tb._pil_available = None
        first = tb._check_pil()
        # принудительно ломаем — если бы перепроверял, упал бы
        assert tb._check_pil() is first

    def test_returns_false_and_warns_when_missing(self, tb, monkeypatch):
        """ImportError → False + один warning, без исключения наружу."""
        import builtins
        tb._pil_available = None
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "PIL":
                raise ImportError("No module named 'PIL'")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert tb._check_pil() is False


# ── _send_diff_image ───────────────────────────────────────────────────────


class TestSendDiffImage:
    @pytest.mark.asyncio
    async def test_parse_edit_calls_render(self, tb, monkeypatch):
        """_send_diff_image парсит Edit JSON и вызывает render_edit_diff."""
        import json
        rendered = []

        def fake_render(file_path, old_str, new_str):
            rendered.append((file_path, old_str, new_str))
            return b"\x89PNG..."

        monkeypatch.setenv("TG_DIFF_IMAGES", "true")
        monkeypatch.setattr("app.diff_image.render_edit_diff", fake_render)
        # Мокаем _send_png_to_tg чтобы не трогать TG API
        sent_pngs = []
        async def fake_send_png(png, chat_id, thread_id, label):
            sent_pngs.append(png)
        monkeypatch.setattr(tb, "_send_png_to_tg", fake_send_png)

        params = {"file_path": "app/main.py", "old_string": "old", "new_string": "new"}
        raw = f"Edit: {json.dumps(params)}"
        await tb._send_diff_image("Edit", raw, -100, 42)

        assert len(rendered) == 1
        assert rendered[0] == ("app/main.py", "old", "new")
        assert sent_pngs == [b"\x89PNG..."]

    @pytest.mark.asyncio
    async def test_disabled_env_skips_render(self, tb, monkeypatch):
        """При TG_DIFF_IMAGES=false render не вызывается."""
        import json
        rendered = []
        monkeypatch.setenv("TG_DIFF_IMAGES", "false")
        monkeypatch.setattr("app.diff_image.render_edit_diff", lambda *a: rendered.append(a) or b"")

        raw = f"Edit: {json.dumps({'file_path': 'f', 'old_string': '', 'new_string': ''})}"
        await tb._send_diff_image("Edit", raw, -100, 42)
        assert rendered == []  # не вызван

    @pytest.mark.asyncio
    async def test_invalid_json_does_not_raise(self, tb, monkeypatch):
        """Невалидный JSON в raw_content → тихий return без исключения."""
        monkeypatch.setenv("TG_DIFF_IMAGES", "true")
        # Не должно бросить исключение
        await tb._send_diff_image("Edit", "Edit: not_json_at_all", -100, 42)

    @pytest.mark.asyncio
    async def test_failed_delivery_is_not_reported_as_image_success(
        self, tb, monkeypatch,
    ):
        import json

        monkeypatch.setenv("TG_DIFF_IMAGES", "true")
        monkeypatch.setattr(
            "app.diff_image.render_edit_diff",
            lambda *args: b"\x89PNG...",
        )
        monkeypatch.setattr(
            tb,
            "_send_png_to_tg",
            AsyncMock(return_value=False),
        )
        raw = f"Edit: {json.dumps({
            'file_path': 'app/main.py',
            'old_string': 'old',
            'new_string': 'new',
        })}"

        assert await tb._send_diff_image("Edit", raw, -100, 42) is False

    @pytest.mark.asyncio
    async def test_truthy_image_submission_never_suppresses_tool_text(
        self, tb, monkeypatch,
    ):
        expandable_sent = asyncio.Event()
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
                return [{
                    "id": 1,
                    "type": "tool",
                    "content": (
                        'Edit: {"file_path":"x","old_string":"a",'
                        '"new_string":"b"}'
                    ),
                }]
            return []

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
        monkeypatch.setattr(
            tb,
            "_send_diff_image",
            AsyncMock(return_value=object()),
        )
        monkeypatch.setattr(tb, "_mirror_send", AsyncMock())

        async def send_expandable(*args, **kwargs):
            expandable_sent.set()
            return object()

        monkeypatch.setattr(tb, "_send_expandable", send_expandable)

        stream = asyncio.create_task(tb.stream_logs("orch", 42))
        try:
            await asyncio.wait_for(expandable_sent.wait(), timeout=0.05)
        finally:
            stream.cancel()
            await asyncio.gather(stream, return_exceptions=True)


class TestTgImageLane:
    @pytest.mark.asyncio
    async def test_image_ingress_is_bounded_and_reset_cleans_temp_files(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        tb.bot = AsyncMock()
        tb.bot.send_photo.return_value = object()
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
        monkeypatch.setattr(tb, "_TG_OPTIONAL_QUEUE_MAX", 3, raising=False)
        monkeypatch.setattr(tb, "_TG_IMAGE_QUEUE_MAX", 2, raising=False)

        submissions = [
            await tb._send_png_to_tg(b"\x89PNG...", -100, 42, f"img-{i}")
            for i in range(10)
        ]

        snapshot = tb._tg_delivery_snapshot(-100)
        assert snapshot["optional_images"] == 2
        assert snapshot["optional_dropped"] == 8
        assert sum(submission.accepted for submission in submissions) == 2
        assert len(list(tmp_path.glob("diff-*.png"))) == 2

        await tb._reset_tg_delivery_state()
        await asyncio.sleep(0)
        assert not list(tmp_path.glob("diff-*.png"))

    @pytest.mark.asyncio
    async def test_image_completion_reports_delivery_failure_and_cleans_file(
        self, tb, tmp_path, monkeypatch,
    ):
        import tempfile

        method = SendMessage(chat_id=-100, text="image placeholder")
        tb.bot = AsyncMock()
        tb.bot.send_photo.side_effect = TelegramNetworkError(
            method=method,
            message="timeout",
        )
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)

        submission = await tb._send_png_to_tg(
            b"\x89PNG...", -100, 42, "failed",
        )

        assert submission.accepted is True
        assert await submission.completion is None
        await asyncio.sleep(0)
        assert not list(tmp_path.glob("diff-*.png"))


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
    async def test_total_timeout_bounds_one_stalled_attempt_and_releases_queue(
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
        monkeypatch.setattr(tb, "_TG_RELIABLE_CALL_TIMEOUT", 1.0, raising=False)
        monkeypatch.setattr(tb, "_TG_RELIABLE_TOTAL_TIMEOUT", 0.02, raising=False)

        started = time.monotonic()
        results = await asyncio.wait_for(
            asyncio.gather(
                tb._tg_send_safe(-100, "slow", 7, important=True),
                tb._tg_send_safe(-100, "reply", 7, important=True),
            ),
            timeout=5,
        )
        snapshot = tb._tg_delivery_snapshot(-100)

        assert results[0] is None
        assert results[1] is not None
        assert slow_attempts == 1
        assert time.monotonic() - started < 0.1
        assert snapshot["reliable_total_timeouts"] == 1
        assert snapshot["reliable_lost"] == 1

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
        both_sent = asyncio.Event()
        sent_at = []

        async def send_message(*args, **kwargs):
            sent_at.append(asyncio.get_running_loop().time())
            if len(sent_at) == 2:
                both_sent.set()
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
        await asyncio.wait_for(both_sent.wait(), timeout=5)

        assert sent_at[1] - sent_at[0] >= 0.018
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

        try:
            await asyncio.wait_for(
                tb.notify_scope_running("orch"),
                timeout=0.05,
            )
            await asyncio.wait_for(edit_started.wait(), timeout=0.05)
            await tb.check_scope_idle("orch", "/scope")
            assert len(tb._topic_status_tasks) == 1
        finally:
            release_edit.set()
            await asyncio.gather(
                *tb._topic_status_tasks.values(),
                return_exceptions=True,
            )

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
    async def test_queued_nonimportant_calls_keep_rate_interval(self, tb, monkeypatch):
        sent_at = []

        async def send_message(*args, **kwargs):
            sent_at.append(asyncio.get_running_loop().time())
            return object()

        tb.bot = AsyncMock()
        tb.bot.send_message.side_effect = send_message
        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.02)
        monkeypatch.setattr(tb, "_TG_TELEMETRY_MAX_AGE", 0)

        first = await tb._tg_send_safe(
            -100, "tool-1", 77, telemetry_key=(77, "tool-1"),
        )
        second = await tb._tg_send_safe(
            -100, "tool-2", 77, telemetry_key=(77, "tool-2"),
        )
        await asyncio.gather(first, second)

        assert len(sent_at) == 2
        assert sent_at[1] - sent_at[0] >= 0.018

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


class TestTgTelemetryFairness:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("later_reliable", [5, 20, 50])
    async def test_overdue_tool_is_not_starved_by_later_reliable_calls(
        self, tb, monkeypatch, later_reliable,
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
        tool = await tb._tg_send_safe(-100, "tool", 77)
        reliable = [
            asyncio.create_task(
                tb._tg_send_safe(-100, f"reply-{i}", 77, important=True),
            )
            for i in range(later_reliable)
        ]
        await asyncio.sleep(0)
        release_blocker.set()

        await asyncio.gather(blocker, tool, *reliable)

        assert calls.index("tool") <= 4

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
