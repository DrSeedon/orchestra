"""#8 T1 — /api/logs/sync: зеркало журнала для браузера.

Проверяем ровно то, на что опирается клиентское хранилище: холодный срез по хвосту,
инкремент по watermark, обрезка по БАЙТАМ, полнота live_sessions и каскад при удалении
сессии. Ошибка в любом из этих пунктов приводит к тихому показу чужой или мёртвой истории.
"""

import json
from datetime import datetime, timezone

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


def _session(sid: str, name: str, scope: str = "/proj") -> dict:
    return {
        "id": sid, "name": name, "scope": scope, "cwd": scope,
        "model": "claude-opus-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": "sdk-" + sid, "cost_usd": 0.0, "worktree_path": None,
        "branch": None, "is_orchestrator": False, "color": "#818cf8",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    }


def _fill(sessions: dict[str, int]) -> None:
    """{session_id: сколько строк} — по строке на каждую, в порядке возрастания id."""
    from app.db import add_log, save_session
    for i, (sid, n) in enumerate(sessions.items()):
        save_session(_session(sid, f"agent-{i}"))
    for sid, n in sessions.items():
        for j in range(n):
            add_log(sid, datetime.now(timezone.utc), "text", f"{sid}-{j}")


class TestColdSync:
    def test_tail_limits_rows_per_session_not_globally(self, db):
        from app.db import get_logs_sync
        _fill({"s1": 30, "s2": 5})
        out = get_logs_sync(after_id=0, tail=20)
        per = {}
        for row in out["logs"]:
            per[row["session_id"]] = per.get(row["session_id"], 0) + 1
        assert per == {"s1": 20, "s2": 5}

    def test_tail_takes_the_newest_rows(self, db):
        from app.db import get_logs_sync
        _fill({"s1": 30})
        got = [r["content"] for r in get_logs_sync(after_id=0, tail=3)["logs"]]
        assert got == ["s1-27", "s1-28", "s1-29"]

    def test_rows_are_ordered_by_id_ascending(self, db):
        from app.db import get_logs_sync
        _fill({"s1": 4, "s2": 4})
        ids = [r["id"] for r in get_logs_sync(after_id=0, tail=20)["logs"]]
        assert ids == sorted(ids)

    def test_empty_db_does_not_raise(self, db):
        from app.db import get_logs_sync
        out = get_logs_sync(after_id=0, tail=20)
        assert out == {"max_log_id": 0, "live_sessions": [], "logs": []}


class TestIncrementalSync:
    def test_after_id_returns_only_newer_rows(self, db):
        from app.db import add_log, get_logs_sync
        _fill({"s1": 3})
        watermark = get_logs_sync(after_id=0, tail=20)["max_log_id"]
        add_log("s1", datetime.now(timezone.utc), "text", "свежая")
        out = get_logs_sync(after_id=watermark)
        assert [r["content"] for r in out["logs"]] == ["свежая"]
        assert out["max_log_id"] == watermark + 1

    def test_at_watermark_returns_nothing(self, db):
        from app.db import get_logs_sync
        _fill({"s1": 3})
        watermark = get_logs_sync(after_id=0, tail=20)["max_log_id"]
        assert get_logs_sync(after_id=watermark)["logs"] == []

    def test_increment_crosses_all_sessions(self, db):
        """Хвост открытого агента приносит SSE; всех остальных — только этот запрос."""
        from app.db import add_log, get_logs_sync
        _fill({"s1": 2, "s2": 2})
        watermark = get_logs_sync(after_id=0, tail=20)["max_log_id"]
        add_log("s1", datetime.now(timezone.utc), "text", "в s1")
        add_log("s2", datetime.now(timezone.utc), "text", "в s2")
        out = get_logs_sync(after_id=watermark)
        assert {r["session_id"] for r in out["logs"]} == {"s1", "s2"}


class TestContentCap:
    def test_caps_by_bytes_not_characters(self, db):
        """Кириллица — 2 байта на символ. По символам потолок уехал бы вдвое."""
        from app.db import add_log, get_logs_sync, save_session
        save_session(_session("s1", "a"))
        add_log("s1", datetime.now(timezone.utc), "text", "я" * 500)  # 1000 байт
        row = get_logs_sync(after_id=0, tail=20, cap=100)["logs"][0]
        assert len(row["content"].encode()) <= 100
        assert row["trunc"] == 1000

    def test_cut_in_the_middle_of_a_character_does_not_raise(self, db):
        from app.db import add_log, get_logs_sync, save_session
        save_session(_session("s1", "a"))
        add_log("s1", datetime.now(timezone.utc), "text", "я" * 50)
        row = get_logs_sync(after_id=0, tail=20, cap=51)["logs"][0]  # срез рубит символ
        assert row["content"] == "я" * 25
        assert row["trunc"] == 100

    def test_short_content_untouched_and_unmarked(self, db):
        from app.db import add_log, get_logs_sync, save_session
        save_session(_session("s1", "a"))
        add_log("s1", datetime.now(timezone.utc), "text", "коротко")
        row = get_logs_sync(after_id=0, tail=20, cap=16384)["logs"][0]
        assert row["content"] == "коротко"
        assert "trunc" not in row

    def test_cap_applies_to_incremental_sync_too(self, db):
        from app.db import add_log, get_logs_sync, save_session
        save_session(_session("s1", "a"))
        add_log("s1", datetime.now(timezone.utc), "text", "x")
        watermark = get_logs_sync(after_id=0)["max_log_id"]
        add_log("s1", datetime.now(timezone.utc), "text", "y" * 5000)
        row = get_logs_sync(after_id=watermark, cap=100)["logs"][0]
        assert row["trunc"] == 5000


class TestLiveSessions:
    def test_lists_every_session_including_archived(self, db):
        """Список строится без фильтров: пропущенная сессия = стёртая у клиента история."""
        from app.db import archive_session, get_logs_sync, save_session
        save_session(_session("s1", "живой"))
        save_session(_session("s2", "архивный"))
        archive_session("s2")
        got = get_logs_sync(after_id=0)["live_sessions"]
        assert {s["id"] for s in got} == {"s1", "s2"}

    def test_carries_name_and_scope_for_offline_lookup(self, db):
        """После F5 клиент знает имя агента, но не session_id — карта приходит отсюда."""
        from app.db import get_logs_sync, save_session
        save_session(_session("s1", "back", scope="/proj-a"))
        got = get_logs_sync(after_id=0)["live_sessions"]
        assert got == [{"id": "s1", "name": "back", "scope": "/proj-a"}]

    def test_deleted_session_disappears_with_its_logs(self, db):
        """ON DELETE CASCADE + foreign_keys=ON: удаление уносит журнал, зеркало обязано повторить."""
        from app.db import delete_session, get_logs_sync
        _fill({"s1": 3, "s2": 3})
        delete_session("s2")
        out = get_logs_sync(after_id=0, tail=20)
        assert [s["id"] for s in out["live_sessions"]] == ["s1"]
        assert {r["session_id"] for r in out["logs"]} == {"s1"}


class TestRoute:
    def test_endpoint_clamps_arguments(self, db, monkeypatch):
        """tail и cap приходят из URL — их нельзя пускать в SQL как есть."""
        # Логин выключаем явно: на машине, где .env с DASHBOARD_* попал в окружение,
        # любой запрос к /api/ отвечает 401, и тест зеленел бы или краснел от того,
        # чей это компьютер, а не от кода.
        monkeypatch.delenv("DASHBOARD_USER", raising=False)
        monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
        seen = {}
        import app.routes.sessions as routes

        def fake(after_id, tail, cap):
            seen.update(after_id=after_id, tail=tail, cap=cap)
            return {"max_log_id": 0, "live_sessions": [], "logs": []}

        monkeypatch.setattr(routes, "get_logs_sync", fake)
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            # lifespan подтягивает .env обратно в os.environ — гасим логин уже после старта
            monkeypatch.delenv("DASHBOARD_USER", raising=False)
            monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
            r = client.get("/api/logs/sync?after_id=-5&tail=99999&cap=1")
        assert r.status_code == 200, r.text
        assert seen == {"after_id": 0, "tail": 200, "cap": 256}


class TestHistoryChunkBudget:
    """#72 — страница истории едет порциями, ограниченными БАЙТАМИ, а не только строками."""

    def test_budget_cuts_the_chunk_by_bytes(self, db):
        from app.db import add_log, get_logs_before, save_session
        save_session(_session("s1", "back"))
        for i in range(10):
            add_log("s1", datetime.now(timezone.utc), "text", "x" * 1000)
        rows = get_logs_before("s1", 2 ** 31 - 1, limit=10, max_bytes=3500)
        assert len(rows) == 3          # четвёртая перебрала бы бюджет
        assert [r["content"] for r in rows] == ["x" * 1000] * 3

    def test_row_bigger_than_budget_still_comes_alone(self, db):
        """Иначе жирная строка даёт пустой ответ, и клиентский добор зациклится на ней."""
        from app.db import add_log, get_logs_before, save_session
        save_session(_session("s1", "back"))
        add_log("s1", datetime.now(timezone.utc), "text", "y" * 100)
        add_log("s1", datetime.now(timezone.utc), "text", "z" * 50000)
        rows = get_logs_before("s1", 2 ** 31 - 1, limit=10, max_bytes=1000)
        assert [len(r["content"]) for r in rows] == [50000]

    def test_no_budget_means_no_limit(self, db):
        from app.db import add_log, get_logs_before, save_session
        save_session(_session("s1", "back"))
        for i in range(5):
            add_log("s1", datetime.now(timezone.utc), "text", "x" * 10000)
        assert len(get_logs_before("s1", 2 ** 31 - 1, limit=10)) == 5

    def test_chunks_walk_back_without_gaps_or_repeats(self, db):
        """Клиент ходит назад по firstId — проверяем, что склейка порций даёт ровный ряд."""
        from app.db import add_log, get_logs_before, save_session
        save_session(_session("s1", "back"))
        for i in range(20):
            add_log("s1", datetime.now(timezone.utc), "text", f"m{i}" + "x" * 900)
        seen, before = [], 2 ** 31 - 1
        for _ in range(10):
            rows = get_logs_before("s1", before, limit=25, max_bytes=3000)
            if not rows:
                break
            seen = [r["content"] for r in rows] + seen
            before = min(r["id"] for r in rows)
        assert seen == [f"m{i}" + "x" * 900 for i in range(20)]


class TestFatRowCap:
    """#74 — одиночная жирная строка не должна ехать ответом на полмегабайта."""

    def test_cap_truncates_row_and_marks_it(self, db):
        from app.db import add_log, get_logs_before, save_session
        save_session(_session("s1", "back"))
        add_log("s1", datetime.now(timezone.utc), "tool_result", "b" * 50000)
        rows = get_logs_before("s1", 2 ** 31 - 1, limit=10, max_bytes=0, cap=1024)
        assert len(rows[0]["content"].encode()) == 1024
        assert rows[0]["trunc"] == 50000          # исходная длина в байтах — её показывает маркер

    def test_image_generation_projects_path_and_prompt_instead_of_base64_prefix(self, db):
        """Истории нужен результат генерации, а не мегабайты уже сохранённого PNG."""
        from app.db import add_log, get_logs_before, get_logs_sync, save_session

        save_session(_session("s1", "back"))
        source = json.dumps({
            "result": "A" * 50000,
            "saved_path": "/tmp/generated.png",
            "status": "completed",
            "revised_prompt": "Product hero: exact item on a warm neutral background",
        })
        add_log(
            "s1", datetime.now(timezone.utc), "tool_result", source,
            tool_use_id="image-1", tool_name="ImageGeneration",
        )

        page_row = get_logs_before(
            "s1", 2 ** 31 - 1, limit=10, max_bytes=4096, cap=1024,
        )[0]
        sync_row = get_logs_sync(after_id=0, tail=10, cap=1024)["logs"][0]

        for row in (page_row, sync_row):
            projected = json.loads(row["content"])
            assert projected == {
                "status": "completed",
                "saved_path": "/tmp/generated.png",
                "revised_prompt": "Product hero: exact item on a warm neutral background",
            }
            assert row["projection"] == "image_generation"
            assert row["source_bytes"] > 50000
            assert "trunc" not in row
            assert "result" not in projected

    def test_capped_row_no_longer_blows_the_budget(self, db):
        """Потолок строки и бюджет порции должны работать вместе, а не по отдельности."""
        from app.db import add_log, get_logs_before, save_session
        save_session(_session("s1", "back"))
        for _ in range(5):
            add_log("s1", datetime.now(timezone.utc), "tool_result", "b" * 50000)
        rows = get_logs_before("s1", 2 ** 31 - 1, limit=5, max_bytes=4096, cap=1024)
        assert sum(len(r["content"].encode()) for r in rows) <= 4096
        assert len(rows) == 4                     # 4 × 1024 укладывается в бюджет, пятая нет

    def test_no_cap_means_full_row(self, db):
        from app.db import add_log, get_logs_before, save_session
        save_session(_session("s1", "back"))
        add_log("s1", datetime.now(timezone.utc), "tool_result", "b" * 50000)
        rows = get_logs_before("s1", 2 ** 31 - 1, limit=10)
        assert len(rows[0]["content"]) == 50000
        assert "trunc" not in rows[0]

    def test_get_log_returns_the_row_whole(self, db):
        """Кнопка «загрузить целиком» обязана приносить ИСХОДНУЮ строку, а не ту же обрезку."""
        from app.db import add_log, get_log, get_logs_before, save_session
        save_session(_session("s1", "back"))
        add_log("s1", datetime.now(timezone.utc), "tool_result", "b" * 50000)
        capped = get_logs_before("s1", 2 ** 31 - 1, limit=10, cap=1024)[0]
        full = get_log(capped["id"])
        assert len(full["content"]) == 50000
        assert "trunc" not in full

    def test_get_log_missing_is_none(self, db):
        from app.db import get_log
        assert get_log(10 ** 9) is None


class TestColdSyncWithoutPrefetch:
    """#72 — дашборд ходит с tail=0: карта сессий есть, строк журнала нет."""

    def test_tail_zero_returns_map_without_logs(self, db):
        from app.db import get_logs_sync
        _fill({"s1": 30, "s2": 5})
        out = get_logs_sync(after_id=0, tail=0)
        assert out["logs"] == []
        assert {s["id"] for s in out["live_sessions"]} == {"s1", "s2"}
        assert out["max_log_id"] > 0


class TestStreamHandshake:
    @pytest.mark.asyncio
    async def test_stream_names_its_session_before_any_history(self, db):
        """Клиент держит историю по session_id. До первого события он знает его лишь по
        своей карте, которая могла устареть, — правду обязан назвать сервер, и первым.

        Генератор потока бесконечный, поэтому тянем ровно два события напрямую из
        body_iterator и закрываем: любое чтение «до конца» тут висло бы вечно.
        """
        import asyncio
        from app.db import add_log, save_session
        from app.deps import manager
        from app.routes.sessions import stream_session_logs
        save_session(_session("s1", "back", scope="/proj"))
        add_log("s1", datetime.now(timezone.utc), "text", "первая строка истории")
        manager.sessions.clear()

        class _Req:
            async def is_disconnected(self):
                return False

        resp = await stream_session_logs("back", "/proj", _Req(), after_id=0)
        it = resp.body_iterator
        try:
            events = [json.loads((await asyncio.wait_for(it.__anext__(), 5))[6:])
                      for _ in range(2)]
        finally:
            await it.aclose()
        assert events[0] == {
            "type": "__session",
            "session_id": "s1",
            "agent_status": "idle",
        }
        assert events[1]["content"] == "первая строка истории"
