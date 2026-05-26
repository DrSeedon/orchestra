"""TDD-тесты для tg_bridge.py — инкремент имён топиков и cleanup при delete.

Покрытие:
- ``_short_name`` — нормализация имени оркестратора в имя топика.
- ``_pick_unique_topic_name`` — выбор свободного имени с инкрементом ``-2``, ``-3`` при коллизиях.
- ``remove_topics_for_orchs`` — удаление топиков из TG и записей из ``config["topics"]`` /
  ``config["topic_names"]``. Mirrors не трогаем. Ошибки Bot API не должны валить процесс.
"""

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
    return tg_bridge


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
