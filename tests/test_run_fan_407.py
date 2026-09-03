"""#407: one MCP call owns fan open plus spawn/reuse launch plumbing."""

import asyncio
import json

import pytest


@pytest.mark.asyncio
async def test_t3_deadline_closes_fan_and_wakes_parent_without_another_tool_call(
    tmp_path, monkeypatch,
):
    from app import db, fan_barrier

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fan-deadline-407.db")
    db.init_db()
    fan_barrier.open_fan(
        fan_id="deadline-407",
        parent_name="parent-407",
        scope="/repo-407",
        children=["slow-407-a", "slow-407-b"],
        deadline_seconds=0.01,
    )
    delivered = asyncio.Event()
    wakes = []

    class Manager:
        async def ensure_loaded(self, name, scope):
            return type("Parent", (), {"id": "sid-parent-407"})()

        async def send(self, session_id, message, *, provenance):
            assert provenance.origin == "platform"
            wakes.append((session_id, message))
            delivered.set()

    monkeypatch.setattr("app.deps.manager", Manager())
    fan_barrier.schedule_deadline("deadline-407")
    await asyncio.wait_for(delivered.wait(), timeout=2.0)

    assert len(wakes) == 1
    assert "complete=false partial_reason=deadline" in wakes[0][1]
    assert [
        member["state"] for member in fan_barrier.manifest("deadline-407")["members"]
    ] == ["timeout", "timeout"]


@pytest.mark.asyncio
async def test_t3_run_fan_reuses_live_idle_workers_after_opening_barrier(monkeypatch):
    from app import mcp_stdio as mcp

    events = []
    monkeypatch.setattr(mcp, "SCOPE", "/repo-407")
    monkeypatch.setattr(mcp, "WORKER_NAME", "parent-407")

    async def api(method, path, **kwargs):
        events.append(("api", method, path, kwargs))
        if method == "GET" and path == "/api/sessions":
            return [
                {
                    "name": "idle-407-a",
                    "status": "idle",
                    "is_orchestrator": False,
                },
                {
                    "name": "idle-407-b",
                    "status": "idle",
                    "is_orchestrator": False,
                },
            ]
        if method == "POST" and path == "/api/fan/open":
            return {"ok": True, "fan_id": kwargs["json"]["fan_id"]}
        raise AssertionError((method, path, kwargs))

    async def send(name, message, delivery_id=""):
        events.append(("send", name, message))
        return f"sent to {name}"

    async def forbidden_spawn(*args, **kwargs):
        raise AssertionError("reuse mode spawned a replacement worker")

    monkeypatch.setattr(mcp, "_api", api)
    monkeypatch.setattr(mcp, "send_message", send)
    monkeypatch.setattr(mcp, "spawn_worker", forbidden_spawn)

    result = await mcp.run_fan(reuse=[
        {"name": "idle-407-a", "message": "reuse task A"},
        {"name": "idle-407-b", "message": "reuse task B"},
    ])

    open_index = next(
        index for index, event in enumerate(events)
        if event[:3] == ("api", "POST", "/api/fan/open")
    )
    sends = [
        (index, event) for index, event in enumerate(events) if event[0] == "send"
    ]
    assert [event[1:] for _, event in sends] == [
        ("idle-407-a", "reuse task A"),
        ("idle-407-b", "reuse task B"),
    ]
    assert all(open_index < index for index, _ in sends), events
    assert "started 2/2 workers" in result
    assert not any("archive" in str(event).lower() for event in events)


@pytest.mark.asyncio
async def test_t3_run_fan_opens_before_spawning_all_task_specs(monkeypatch):
    from app import mcp_stdio as mcp

    events = []
    monkeypatch.setattr(mcp, "SCOPE", "/repo-407")
    monkeypatch.setattr(mcp, "WORKER_NAME", "parent-407")

    async def api(method, path, **kwargs):
        events.append(("api", method, path, kwargs))
        assert (method, path) == ("POST", "/api/fan/open")
        return {"ok": True}

    async def spawn(**kwargs):
        events.append(("spawn", kwargs))
        return "spawned"

    monkeypatch.setattr(mcp, "_api", api)
    monkeypatch.setattr(mcp, "spawn_worker", spawn)

    specs = [
        {
            "name": "new-407-a",
            "model": "gpt-5.6-luna",
            "role": "worker",
            "task": "task A",
            "owned_dirs": ["app/a/"],
        },
        {
            "name": "new-407-b",
            "model": "gpt-5.6-sol",
            "role": "worker",
            "task": "task B",
            "owned_dirs": ["app/b/"],
        },
    ]
    result = await mcp.run_fan(tasks=specs)

    assert events[0][0:3] == ("api", "POST", "/api/fan/open")
    spawns = [event[1] for event in events[1:]]
    assert [call["name"] for call in spawns] == ["new-407-a", "new-407-b"]
    assert all(call["repo_path"] == "/repo-407" for call in spawns)
    assert [json.loads(call["owned_dirs"]) for call in spawns] == [
        ["app/a/"], ["app/b/"],
    ]
    assert "started 2/2 workers" in result


@pytest.mark.asyncio
async def test_run_fan_spawns_children_into_the_named_repository(monkeypatch):
    """Дети веера идут в `repo_path`, а не в scope родителя.

    Без этого веер физически не мог работать по ДРУГОМУ репозиторию: `spawn_worker`
    умеет `repo_path`, а `run_fan` жёстко подставлял `SCOPE`. 28.08.2026 у `pitch-game`
    три отработавших воркера легли в comfy-image-pipeline вместо pitch-ball, и
    `merge_worker` отвечал "task '1' not found in session project" — работу пришлось
    переносить руками.
    """
    from app import mcp_stdio as mcp

    spawns = []
    monkeypatch.setattr(mcp, "SCOPE", "/scope-of-the-parent")
    monkeypatch.setattr(mcp, "WORKER_NAME", "parent-407")

    async def api(method, path, **kwargs):
        # Барьер намеренно остаётся на scope РОДИТЕЛЯ: он будит вызывающего.
        assert kwargs["json"]["scope"] == "/scope-of-the-parent"
        return {"ok": True}

    async def spawn(**kwargs):
        spawns.append(kwargs)
        return "spawned"

    monkeypatch.setattr(mcp, "_api", api)
    monkeypatch.setattr(mcp, "spawn_worker", spawn)

    specs = [
        {"name": "child-a", "model": "gpt-5.6-luna", "role": "worker",
         "task": "A", "owned_dirs": []},
        {"name": "child-b", "model": "gpt-5.6-luna", "role": "worker",
         "task": "B", "owned_dirs": []},
    ]
    await mcp.run_fan(tasks=specs, repo_path="/another/repository")

    assert [call["repo_path"] for call in spawns] == [
        "/another/repository", "/another/repository",
    ]


@pytest.mark.asyncio
async def test_run_fan_without_repo_path_still_uses_the_caller_scope(monkeypatch):
    """Обратная сторона: пустой `repo_path` не должен ломать обычный веер."""
    from app import mcp_stdio as mcp

    spawns = []
    monkeypatch.setattr(mcp, "SCOPE", "/scope-of-the-parent")
    monkeypatch.setattr(mcp, "WORKER_NAME", "parent-407")

    async def api(method, path, **kwargs):
        return {"ok": True}

    async def spawn(**kwargs):
        spawns.append(kwargs)
        return "spawned"

    monkeypatch.setattr(mcp, "_api", api)
    monkeypatch.setattr(mcp, "spawn_worker", spawn)

    specs = [
        {"name": "child-a", "model": "gpt-5.6-luna", "role": "worker",
         "task": "A", "owned_dirs": []},
        {"name": "child-b", "model": "gpt-5.6-luna", "role": "worker",
         "task": "B", "owned_dirs": []},
    ]
    await mcp.run_fan(tasks=specs)

    assert [call["repo_path"] for call in spawns] == [
        "/scope-of-the-parent", "/scope-of-the-parent",
    ]
