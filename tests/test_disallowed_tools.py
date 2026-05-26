"""Оркестратору субагент-инструмент режется через disallowed_tools (CLI),
т.к. запуск субагента обходит can_use_tool. Воркерам — оставляем."""
from app.backend_claude import _disallowed_tools


def test_orchestrator_disallows_subagent_tool():
    d = _disallowed_tools(True)
    assert "Task" in d and "Agent" in d


def test_worker_keeps_subagent_tool():
    assert _disallowed_tools(False) == []
