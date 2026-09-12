"""A barrier deadline wakes its parent without another tool call."""

import asyncio

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
