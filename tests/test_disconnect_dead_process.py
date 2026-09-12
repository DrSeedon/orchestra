"""#V-560: мёртвый процесс не должен блокировать смену модели.

Краснеет, если вернуть безусловный `raise` в `ClaudeBackend.disconnect`: тогда
`AttributeError` из SDK (у транспорта уже нет процесса, обращение к `.returncode`
приходит на None) поднимается в `_change_runtime_chat_locked` и тот отвечает
`text_tail_source_release_failed` — ровно то, что 12.09.2026 не дало владельцу
переключить оркестратора на другую модель.
"""
import asyncio

import pytest

from app.backend_claude import ClaudeBackend


class _DeadClient:
    async def disconnect(self):
        raise AttributeError("'NoneType' object has no attribute 'returncode'")


class _BrokenClient:
    async def disconnect(self):
        raise RuntimeError("transport refused to close")


def _backend(client):
    backend = ClaudeBackend.__new__(ClaudeBackend)
    backend._client = client
    backend._remove_mcp_config = lambda: None
    return backend


def test_missing_process_is_a_successful_release():
    backend = _backend(_DeadClient())
    asyncio.run(backend.disconnect())
    assert backend._client is None, "ресурс обязан быть освобождён"


def test_real_failure_still_propagates():
    backend = _backend(_BrokenClient())
    with pytest.raises(RuntimeError):
        asyncio.run(backend.disconnect())
    assert backend._client is None
