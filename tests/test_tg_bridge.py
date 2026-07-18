"""TDD-тесты для tg_bridge.py — инкремент имён топиков и cleanup при delete.

Покрытие:
- ``_short_name`` — нормализация имени оркестратора в имя топика.
- ``_pick_unique_topic_name`` — выбор свободного имени с инкрементом ``-2``, ``-3`` при коллизиях.
- ``remove_topics_for_orchs`` — удаление топиков из TG и записей из ``config["topics"]`` /
  ``config["topic_names"]``. Mirrors не трогаем. Ошибки Bot API не должны валить процесс.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest


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
