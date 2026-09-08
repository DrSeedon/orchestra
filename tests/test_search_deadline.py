"""#18: дедлайн и полезный отказ search_memory.

Тесты бьют по трём швам: приём заявок (busy), отбраковка протухших (stale) и тексты,
которые видит агент. Главное требование ко всем текстам — из ответа понятно следующее
действие; поэтому в каждом отказе проверяется наличие подсказки про grep.
"""
import asyncio
import time

import pytest


# ── T2: серверная сторона ───────────────────────────────────────────────────













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
    assert "rg -n -i -F" in out
    assert "как чинили таймаут" in out
    assert ".orchestra/kb/" in out




def test_unknown_error_is_never_empty(mcp, monkeypatch):
    err = mcp.ApiToolError(code="http_4xx", message="")
    out = _call(mcp, monkeypatch, raises=err)
    assert out.strip() and "http_4xx" in out and "rg " in out


def test_empty_result_differs_from_timeout(mcp, monkeypatch):
    out = _call(mcp, monkeypatch, returns={"results": [], "index": {"pending_files": 12}})
    assert "No memory matches" in out
    assert "не уложился" not in out, "пустой ответ не должен выглядеть как таймаут"
    assert "No memory matches" in out




def test_successful_search_keeps_old_format(mcp, monkeypatch):
    out = _call(mcp, monkeypatch, returns={
        "results": [{"source": "file", "path": ".orchestra/tasks/3/research.md", "content": "текст"}],
        "index": {"pending_files": 0}})
    assert out.startswith("[file: .orchestra/tasks/3/research.md]")
    assert "rg " not in out, "в успешный ответ подсказку про grep пихать не надо"
