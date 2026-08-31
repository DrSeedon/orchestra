"""Focused contracts for #418 portfolio MCP tools."""

from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_project_goal_and_wait_use_durable_portfolio_routes(monkeypatch):
    from app import mcp_stdio as mcp

    calls: list[tuple[str, str, dict]] = []

    async def api(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/goal"):
            return {"goal": {"id": "goal-1", "objective": "Ship"}}
        if path.endswith("/progress"):
            return {"goal": {"id": "goal-1", "stall_generation": 2}}
        if path.endswith("/waits"):
            return {"id": "wait-1", "question": "Choose A or B", "status": "open"}
        return {"id": "goal-1", "objective": "Ship"}

    monkeypatch.setattr(mcp, "_api", api)
    created = json.loads(
        await mcp.project_goal("alpha", action="set", objective="Ship")
    )
    progressed = json.loads(
        await mcp.project_goal("alpha", action="progress", note="Checkpoint")
    )
    waiting = await mcp.project_wait(
        "alpha", action="open", question="Choose A or B"
    )

    assert created["id"] == "goal-1"
    assert progressed["goal"]["stall_generation"] == 2
    assert waiting.startswith("PROJECT_WAIT_DURABLE:wait-1\n")
    assert calls == [
        (
            "POST",
            "/api/portfolio/projects/alpha/goals",
            {"json": {"objective": "Ship"}},
        ),
        ("GET", "/api/portfolio/projects/alpha/goal", {}),
        (
            "POST",
            "/api/portfolio/projects/alpha/goals/goal-1/progress",
            {"json": {"note": "Checkpoint"}},
        ),
        (
            "POST",
            "/api/portfolio/projects/alpha/waits",
            {"json": {"question": "Choose A or B", "task_ref": ""}},
        ),
    ]


@pytest.mark.asyncio
async def test_task_update_can_link_without_changing_task_binding(monkeypatch):
    from app import mcp_stdio as mcp

    calls: list[tuple[str, str, dict]] = []

    async def api(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/tm/tasks/42":
            return {"par": "ORC-42", "project": "orchestra", "status": "new"}
        return {
            "project_id": "alpha",
            "task_namespace_id": "orchestra",
            "task_display_number": 42,
        }

    monkeypatch.setattr(mcp, "_api", api)
    result = json.loads(await mcp.task_update("42", portfolio_project="alpha"))

    assert result["task"]["status"] == "new"
    assert result["portfolio_link"]["project_id"] == "alpha"
    assert len(calls) == 2
    assert calls[0][0:2] == ("GET", "/api/tm/tasks/42")
    assert calls[1] == (
        "POST",
        "/api/portfolio/projects/alpha/tasks",
        {"json": {"task_project": "orchestra", "task_ref": "42"}},
    )


@pytest.mark.asyncio
async def test_task_update_error_never_falls_through_to_portfolio_link(monkeypatch):
    from app import mcp_stdio as mcp

    calls = []

    async def api(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return {"error": "task update refused"}

    monkeypatch.setattr(mcp, "_api", api)
    result = await mcp.task_update(
        "42", title="changed", project="orchestra", portfolio_project="alpha"
    )

    assert result == "Error: task update refused"
    assert len(calls) == 1
    assert calls[0][0:2] == ("PUT", "/api/tm/tasks/42")


def test_portfolio_tools_are_full_access_only_and_search_memory_stays_registered():
    from app import mcp_stdio as mcp

    registered = {tool.name for tool in mcp.mcp._tool_manager.list_tools()}
    assert {"project_goal", "project_wait", "search_memory"} <= registered
    assert "project_goal" not in mcp.READ_ONLY_MCP_TOOLS
    assert "project_wait" not in mcp.READ_ONLY_MCP_TOOLS
