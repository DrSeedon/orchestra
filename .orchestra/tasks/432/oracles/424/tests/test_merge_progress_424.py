import json
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_running_snapshot_reflects_live_git_and_stage_progress(monkeypatch):
    import app.merge_operations as operations
    import app.mcp_stdio as mcp

    operation_id = "op-424"
    stale = {
        "operation_id": operation_id,
        "operation_state": "RUNNING",
        "commit_point": "NOT_REACHED",
        "git": {
            "status": "NOT_STARTED",
            "target_before": None,
            "target_after": None,
        },
    }
    record = {
        "state": "RUNNING",
        "commit_point": "REACHED",
        "finalization_stage": "PENDING",
        "started_at": (datetime.now(timezone.utc) - timedelta(seconds=42)).isoformat(),
        "finalization_json": json.dumps({
            "target_before": "a" * 40,
            "target_after": "b" * 40,
            "stage": "PENDING",
        }),
        "result": stale,
    }

    current = operations._live_operation_result(record)
    monkeypatch.setattr(mcp, "SCOPE", "/scope")
    monkeypatch.setattr(mcp, "_MERGE_WAIT_SECONDS", 0.01)

    async def fake_api(method, _path, **_kwargs):
        assert method == "POST"
        return {"result": stale, "error": None}

    async def live_status(_operation_id):
        return current

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "_recover_merge_status", live_status)
    formatted = await mcp.merge_worker(name="w", target="main")

    result = formatted.structuredContent["result"]
    assert result["commit_point"] == "REACHED"
    assert result["git"]["status"] != "NOT_STARTED"
    assert result["git"]["target_after"] == "b" * 40
    assert result["progress"]["stage"] == "post-commit finalization"
    assert 40 <= result["progress"]["elapsed_seconds"] < 60
    assert "post-commit finalization" in formatted.content[0].text
    assert "42s" in formatted.content[0].text or "41s" in formatted.content[0].text


def test_running_snapshot_requires_original_payload_on_retry():
    import app.mcp_stdio as mcp

    result = {
        "operation_id": "op-424",
        "operation_state": "RUNNING",
        "commit_point": "NOT_REACHED",
        "git": {"status": "NOT_STARTED"},
        "error": None,
        "next_action": {"code": "CHECK_SAME_OPERATION", "message": "check it"},
        "progress": {"stage": "test-gate / merge preparation", "elapsed_seconds": 7.0},
    }

    text = mcp._merge_tool_result(result).content[0].text

    assert "original payload" in text
    assert "payload differs" in text
