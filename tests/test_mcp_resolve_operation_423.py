import pytest


@pytest.mark.asyncio
async def test_resolved_unknown_with_legacy_error_reaches_tool_as_success(monkeypatch):
    import app.mcp_stdio as m

    operation_id = "op-423"
    payload = {
        "operation_id": operation_id,
        "operation_state": "UNKNOWN",
        "error": {
            "code": "SERVER_RESTARTED",
            "message": "Server restarted while merge operation was running",
        },
        "resolution": {"reason": "checked target branch"},
    }

    async def fake_api(*_args, **_kwargs):
        raise m.ApiToolError(
            code="domain_error",
            message="Server restarted while merge operation was running",
            status=200,
            result=payload,
        )

    monkeypatch.setattr(m, "_api", fake_api)
    result = await m.resolve_merge_operation(operation_id, "checked target branch")

    assert result.isError is False
    assert result.structuredContent["error"] is None
    assert "resolved" in result.content[0].text
    assert result.structuredContent["result"]["resolution"]["previous_error"]["code"] == "SERVER_RESTARTED"
