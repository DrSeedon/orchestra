"""#18: дедлайн и полезный отказ search_memory.

Тесты бьют по трём швам: приём заявок (busy), отбраковка протухших (stale) и тексты,
которые видит агент. Главное требование ко всем текстам — из ответа понятно следующее
действие; поэтому в каждом отказе проверяется наличие подсказки про grep.
"""
import asyncio
import time

import pytest


# ── T2: серверная сторона ───────────────────────────────────────────────────

@pytest.fixture
def ready_rag(monkeypatch):
    from app import rag_service
    monkeypatch.setattr(rag_service, "_RAG_ENABLED", True)
    monkeypatch.setattr(rag_service, "_initialized", True)
    monkeypatch.setattr(rag_service, "_search_queued", 0)
    return rag_service


@pytest.mark.asyncio
async def test_search_rejects_when_queue_full_without_touching_executor(ready_rag, monkeypatch):
    """33-я заявка при потолке 32 обязана отлететь СРАЗУ и не дойти до rag.run."""
    from app import rag
    called = []
    monkeypatch.setattr(rag, "run", lambda *a, **k: called.append(a))
    monkeypatch.setattr(ready_rag, "_search_queued", ready_rag.SEARCH_QUEUE_MAX)

    t = time.perf_counter()
    with pytest.raises(ready_rag.SearchBusy):
        await ready_rag.search("/scope", "q")
    assert (time.perf_counter() - t) < 0.05, "отказ обязан быть мгновенным, а не после очереди"
    assert called == [], "при переполненной очереди executor трогать нельзя"


@pytest.mark.asyncio
async def test_queue_counter_released_after_failure(ready_rag, monkeypatch):
    """Счётчик, не убывающий при исключении, залипает навсегда → busy на всё подряд.
    Мутационная проверка: без finally этот тест краснеет со второго вызова."""
    from app import rag

    async def boom(*a, **k):
        raise RuntimeError("embedder упал")

    monkeypatch.setattr(rag, "run", boom)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await ready_rag.search("/scope", "q")
    assert ready_rag._search_queued == 0


@pytest.mark.asyncio
async def test_stale_request_raises_instead_of_returning_empty(monkeypatch):
    """Протухшая заявка → ошибка, НЕ пустой список: пустой неотличим от «не найдено»."""
    from app import rag
    embedder_calls = []
    monkeypatch.setattr(rag, "get_rag_ro",
                        lambda: embedder_calls.append("dont") or object())
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(rag, "_read_executor", None)  # None → executor по умолчанию

    with pytest.raises(rag.StaleRequest):
        await rag.run(loop, "search", "/scope", "q", deadline=time.monotonic() - 1)
    assert embedder_calls == [], "для протухшей заявки embedder звать нельзя"


@pytest.mark.asyncio
async def test_fresh_request_runs_normally(monkeypatch):
    """Живой дедлайн не мешает: обычный запрос доходит до RagMemory."""
    from app import rag

    class FakeRag:
        def search(self, *a):
            return [{"path": "docs/x.md"}]

    monkeypatch.setattr(rag, "get_rag_ro", FakeRag)
    monkeypatch.setattr(rag, "_read_executor", None)
    loop = asyncio.get_running_loop()
    out = await rag.run(loop, "search", "/scope", "q", deadline=time.monotonic() + 60)
    assert out == [{"path": "docs/x.md"}]


def test_server_deadline_is_not_taken_from_client(ready_rag):
    """Требование приёмки: дедлайн считает СЕРВЕР от прихода запроса. Мусор от клиента
    в тело запроса не пролезает — модель его игнорирует, лишних полей в контракте нет."""
    from app.routes.memory import MemorySearchRequest
    req = MemorySearchRequest(scope="/s", query="q", deadline_ms=10 ** 9, timeout=0)
    assert not hasattr(req, "deadline_ms")
    assert not hasattr(req, "timeout")
    assert ready_rag.SEARCH_DEADLINE_S == 5.0


# ── T1: тексты, которые видит агент ─────────────────────────────────────────

@pytest.fixture
def mcp(monkeypatch):
    from app import mcp_stdio
    monkeypatch.setattr(mcp_stdio, "SCOPE", "/home/kesha/orchestra")
    return mcp_stdio


def _call(mcp, monkeypatch, *, raises=None, returns=None):
    async def fake_api(method, path, **kw):
        assert kw.get("timeout") == mcp.SEARCH_DEADLINE_S, "дедлайн обязан уходить в _api"
        if raises:
            raise raises
        return returns

    monkeypatch.setattr(mcp, "_api", fake_api)
    return asyncio.run(mcp.search_memory("как чинили таймаут"))


@pytest.mark.parametrize(("code", "marker"), [
    ("transport_timeout", "не уложился"),
    ("search_busy", "очередь поиска переполнена"),
    ("search_stale", "протух в очереди"),
])
def test_timeout_busy_stale_tell_agent_to_stop_waiting(mcp, monkeypatch, code, marker):
    err = mcp.ApiToolError(code=code, message="x")
    out = _call(mcp, monkeypatch, raises=err)
    assert marker in out
    assert "Не жди и не повторяй" in out
    assert 'rg "как чинили таймаут"' in out


def test_disabled_rag_names_the_flag(mcp, monkeypatch):
    err = mcp.ApiToolError(code="http_5xx", message="RAG disabled (set RAG_ENABLED=true)")
    out = _call(mcp, monkeypatch, raises=err)
    assert "RAG_ENABLED=false" in out and "rg " in out


def test_unknown_error_is_never_empty(mcp, monkeypatch):
    err = mcp.ApiToolError(code="http_4xx", message="")
    out = _call(mcp, monkeypatch, raises=err)
    assert out.strip() and "http_4xx" in out and "rg " in out


def test_empty_result_differs_from_timeout_and_admits_index_debt(mcp, monkeypatch):
    out = _call(mcp, monkeypatch, returns={"results": [], "index": {"pending_files": 12}})
    assert "No memory matches" in out
    assert "не уложился" not in out, "пустой ответ не должен выглядеть как таймаут"
    assert "индекс не догнан: 12" in out


def test_empty_result_says_when_index_state_unknown(mcp, monkeypatch):
    """index_status отдаёт {} пока не было прохода — молчание честнее нуля."""
    out = _call(mcp, monkeypatch, returns={"results": [], "index": {}})
    assert "состояние индекса неизвестно" in out
    assert "0 файлов" not in out


def test_successful_search_keeps_old_format(mcp, monkeypatch):
    out = _call(mcp, monkeypatch, returns={
        "results": [{"source": "file", "path": ".orchestra/tasks/3/research.md", "content": "текст"}],
        "index": {"pending_files": 0}})
    assert out.startswith("[file: .orchestra/tasks/3/research.md]")
    assert "rg " not in out, "в успешный ответ подсказку про grep пихать не надо"
