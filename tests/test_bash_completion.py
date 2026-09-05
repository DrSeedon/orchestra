"""Bash completion must retain evidence and report failure to the agent/session."""
import asyncio
import json

import pytest

from app.harness import tools
from app.harness.loop import AgentLoop


@pytest.mark.asyncio
async def test_timeout_retains_partial_output_and_names_outer_budget(tmp_path):
    result = await tools.bash("printf 'checkpoint\\n'; sleep 10", str(tmp_path), timeout=1)
    assert result.startswith("[bash error]")
    assert "checkpoint" in result
    assert "harness" in result and "1s" in result
    assert "bg_create" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("command,failed", [("printf ok", False), ("printf partial; exit 7", True)])
async def test_bash_event_identifies_call_and_exit_status(tmp_path, command, failed):
    loop = AgentLoop(None, None, str(tmp_path), [], [], max_context=10000)
    events = [event async for event in loop._dispatch_tool({
        "id": "bash-probe", "function": {"name": "bash", "arguments": json.dumps({"command": command})},
    })]
    start, result = events
    assert start.metadata["tool_use_id"] == result.metadata["tool_use_id"] == "bash-probe"
    assert result.metadata["tool_name"] == "bash"
    assert result.metadata["is_error"] is failed


@pytest.mark.asyncio
async def test_timeout_event_is_error(tmp_path, monkeypatch):
    async def timeout(*args, **kwargs):
        return "[bash error] harness timeout; partial output"
    monkeypatch.setattr(tools, "bash", timeout)
    loop = AgentLoop(None, None, str(tmp_path), [], [], max_context=10000)
    events = [event async for event in loop._dispatch_tool({
        "id": "timeout-probe", "function": {"name": "bash", "arguments": '{"command":"ignored"}'},
    })]
    assert events[-1].metadata["is_error"] is True


@pytest.mark.asyncio
async def test_cancelling_bash_stops_its_command(tmp_path):
    started = tmp_path / "started"
    escaped = tmp_path / "escaped"
    task = asyncio.create_task(tools.bash(
        "touch started; sleep 1; touch escaped", str(tmp_path), timeout=10,
    ))
    async with asyncio.timeout(5):
        while not started.exists():
            await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(1.1)
    assert not escaped.exists(), "cancelled command continued mutating the workspace"
