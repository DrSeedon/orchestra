"""Task #39 Fix 6 — ClaudeBackend cleans up client on connect/reconnect failure (no zombie CLI)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import ToolResultBlock, UserMessage

import app.backend_claude as backend_claude
from app.backend_claude import ClaudeBackend
from app.runtime_history import (
    HISTORICAL_TOOL_INSTRUCTION,
    NativeHistoryRejected,
    NativeHistoryUnsupported,
    render_claude_history,
)


def _backend():
    return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")


def _history():
    return render_claude_history(
        [{
            "id": 1,
            "ts": "2026-08-11T10:00:00+00:00",
            "type": "user_message",
            "content": "remember",
        }],
        snapshot_id=1,
        session_id="11111111-2222-4333-8444-555555555555",
        cwd="/tmp",
        model="claude-sonnet-5[1m]",
    )


def test_imported_resume_uses_session_store_and_current_system_prompt():
    history = _history()
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd="/tmp",
        system_prompt="CURRENT ROLE",
        resume_session_id=history.session_id,
        history_import=history,
    )

    options = backend._make_client().options

    assert options.resume == history.session_id
    assert options.session_store is not None
    assert options.system_prompt["append"] == (
        "CURRENT ROLE\n\n" + HISTORICAL_TOOL_INSTRUCTION
    )


def test_ordinary_resume_options_are_unchanged_without_import_marker():
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd="/tmp",
        system_prompt="CURRENT ROLE",
        resume_session_id="ordinary-session",
    )

    options = backend._make_client().options

    assert options.resume == "ordinary-session"
    assert options.session_store is None
    assert options.system_prompt is None


def test_wrong_history_import_type_fails_loud():
    with pytest.raises(TypeError, match="ClaudeHistoryImport"):
        ClaudeBackend(
            model="claude-sonnet-5[1m]",
            cwd="/tmp",
            history_import={"entries": []},
        )


@pytest.mark.asyncio
async def test_history_import_rejects_unpinned_sdk_before_cli_spawn():
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd="/tmp",
        resume_session_id=_history().session_id,
        history_import=_history(),
    )

    with (
        patch("app.backend_claude.importlib.metadata.version", return_value="0.2.999"),
        patch("app.backend_claude.asyncio.create_subprocess_exec") as spawn,
        pytest.raises(NativeHistoryUnsupported, match="0.2.999"),
    ):
        await backend._verify_history_versions()

    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_history_import_requires_exact_cli_version():
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd="/tmp",
        resume_session_id=_history().session_id,
        history_import=_history(),
    )
    process = AsyncMock()
    process.communicate = AsyncMock(return_value=(b"2.1.1970 (Claude Code)\n", b""))
    process.returncode = 0

    with (
        patch("app.backend_claude.importlib.metadata.version", return_value="0.2.114"),
        patch(
            "app.backend_claude.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
        pytest.raises(NativeHistoryUnsupported, match="2.1.1970"),
    ):
        await backend._verify_history_versions()


@pytest.mark.asyncio
async def test_history_schema_rejection_does_not_take_stale_resume_fallback():
    failed = AsyncMock()
    failed.connect = AsyncMock(side_effect=RuntimeError("CLI exited"))
    failed.disconnect = AsyncMock()
    history = _history()
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd="/tmp",
        resume_session_id=history.session_id,
        history_import=history,
    )

    def capture_stderr():
        backend._stderr_tail = "No conversation found with session ID: imported"
        return failed

    with (
        patch.object(backend, "_verify_history_versions", new=AsyncMock()),
        patch.object(backend, "_make_client", side_effect=capture_stderr),
        patch.object(backend, "_resume_transcript_exists") as exists,
        pytest.raises(NativeHistoryRejected),
    ):
        await backend.connect()

    exists.assert_not_called()
    assert backend.resume_failed is False


@pytest.mark.asyncio
async def test_history_auth_failure_is_not_misreported_as_schema_fallback():
    failed = AsyncMock()
    failed.connect = AsyncMock(side_effect=RuntimeError("authentication required"))
    failed.disconnect = AsyncMock()
    history = _history()
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd="/tmp",
        resume_session_id=history.session_id,
        history_import=history,
    )

    with (
        patch.object(backend, "_verify_history_versions", new=AsyncMock()),
        patch.object(backend, "_make_client", return_value=failed),
        patch.object(backend, "_resume_transcript_exists") as exists,
        pytest.raises(RuntimeError, match="authentication required"),
    ):
        await backend.connect()

    exists.assert_not_called()


@pytest.mark.asyncio
async def test_connect_timeout_disconnects_client():
    client = AsyncMock()
    client.connect = AsyncMock(side_effect=TimeoutError("connect timed out"))
    client.disconnect = AsyncMock()
    b = _backend()
    with patch.object(b, "_make_client", return_value=client):
        with pytest.raises(TimeoutError):
            await b.connect()
    client.disconnect.assert_awaited_once()
    assert b._client is None


@pytest.mark.asyncio
async def test_connect_cancelled_disconnects_client():
    client = AsyncMock()
    client.connect = AsyncMock(side_effect=asyncio.CancelledError())
    client.disconnect = AsyncMock()
    b = _backend()
    with patch.object(b, "_make_client", return_value=client):
        with pytest.raises(asyncio.CancelledError):
            await b.connect()
    client.disconnect.assert_awaited_once()
    assert b._client is None


@pytest.mark.asyncio
async def test_missing_resume_transcript_falls_back_to_fresh_client():
    failed = AsyncMock()
    failed.connect = AsyncMock(side_effect=RuntimeError("Check stderr output for details"))
    failed.disconnect = AsyncMock()
    fresh = AsyncMock()
    fresh.connect = AsyncMock()
    fresh.disconnect = AsyncMock()
    b = ClaudeBackend(
        model="claude-opus-5[1m]",
        cwd="/tmp",
        resume_session_id="missing-session",
    )

    with (
        patch.object(b, "_make_client", side_effect=[failed, fresh]),
        patch.object(b, "_resume_transcript_exists", return_value=False),
    ):
        await b.connect()

    failed.disconnect.assert_awaited_once()
    fresh.connect.assert_awaited_once()
    assert b.resume_failed is True
    assert b.session_id is None
    assert b._client is fresh


@pytest.mark.asyncio
async def test_existing_resume_transcript_does_not_hide_connect_failure():
    failed = AsyncMock()
    failed.connect = AsyncMock(side_effect=RuntimeError("upstream unavailable"))
    failed.disconnect = AsyncMock()
    b = ClaudeBackend(
        model="claude-opus-5[1m]",
        cwd="/tmp",
        resume_session_id="existing-session",
    )

    with (
        patch.object(b, "_make_client", return_value=failed),
        patch.object(b, "_resume_transcript_exists", return_value=True),
        pytest.raises(RuntimeError, match="upstream unavailable"),
    ):
        await b.connect()

    assert b.resume_failed is False


@pytest.mark.asyncio
async def test_reconnect_timeout_disconnects_client():
    client = AsyncMock()
    client.connect = AsyncMock(side_effect=TimeoutError("reconnect timed out"))
    client.disconnect = AsyncMock()
    b = _backend()
    with patch.object(b, "_make_client", return_value=client):
        with pytest.raises(TimeoutError):
            await b.reconnect()
    assert b._client is None


@pytest.mark.asyncio
async def test_reconnect_version_failure_disconnects_owned_client():
    history = _history()
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd="/tmp",
        resume_session_id=history.session_id,
        history_import=history,
    )
    old_client = AsyncMock()
    backend._client = old_client
    backend._verify_history_versions = AsyncMock(
        side_effect=NativeHistoryUnsupported("version changed")
    )

    with pytest.raises(NativeHistoryUnsupported, match="version changed"):
        await backend.reconnect()

    old_client.disconnect.assert_awaited_once()
    assert backend._client is None


@pytest.mark.asyncio
async def test_disconnect_failure_propagates_after_local_cleanup(tmp_path):
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]", cwd=str(tmp_path), system_prompt="test",
    )
    client = AsyncMock()
    client.disconnect.side_effect = RuntimeError("transport still owned")
    config_path = tmp_path / "mcp.json"
    config_path.write_text("{}")
    backend._client = client
    backend._mcp_config_path = config_path

    with pytest.raises(RuntimeError, match="transport still owned"):
        await backend.disconnect()

    assert backend._client is None
    assert backend._mcp_config_path is None
    assert not config_path.exists()


@pytest.mark.asyncio
async def test_reconnect_materializes_replaced_db_history_store(monkeypatch):
    initial = _history()
    refreshed = render_claude_history(
        [
            {
                "id": 1,
                "ts": "2026-08-11T10:00:00+00:00",
                "type": "user_message",
                "content": "remember",
            },
            {
                "id": 2,
                "ts": "2026-08-11T10:01:00+00:00",
                "type": "text",
                "content": "new durable answer",
            },
        ],
        snapshot_id=2,
        session_id=initial.session_id,
        cwd="/tmp",
        model="claude-sonnet-5[1m]",
    )
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd="/tmp",
        resume_session_id=initial.session_id,
        history_import=initial,
    )
    old_client = AsyncMock()
    backend._client = old_client
    fresh_client = AsyncMock()
    captured = {}

    def make_client(*, options):
        captured["options"] = options
        return fresh_client

    backend.replace_history_import(refreshed)
    backend._verify_history_versions = AsyncMock()
    monkeypatch.setattr(backend_claude, "ClaudeSDKClient", make_client)
    monkeypatch.setattr(backend_claude.asyncio, "sleep", AsyncMock())

    await backend.reconnect()

    loaded = await captured["options"].session_store.load({
        "session_id": refreshed.session_id,
    })
    assert loaded == list(refreshed.entries)
    assert "new durable answer" in repr(loaded)
    backend._verify_history_versions.assert_awaited_once()
    old_client.disconnect.assert_awaited_once()
    fresh_client.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_returns_true_on_control_ack():
    client = AsyncMock()
    client.interrupt = AsyncMock()
    b = _backend()
    b._client = client

    assert await b.interrupt() is True
    client.interrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_is_bounded_when_control_ack_never_arrives(monkeypatch):
    async def never_returns():
        await asyncio.Event().wait()

    client = AsyncMock()
    client.interrupt = never_returns
    b = _backend()
    b._client = client
    monkeypatch.setattr(backend_claude, "CLAUDE_INTERRUPT_TIMEOUT", 0.02, raising=False)

    result = await asyncio.wait_for(b.interrupt(), timeout=0.2)

    assert result is False


def test_server_error_is_carried_into_terminal_turn_result():
    b = _backend()

    error_events = b._convert(AssistantMessage(
        content=[TextBlock("API Error: Response stalled mid-stream.")],
        model="claude-opus-5",
        error="server_error",
    ))
    result_events = b._convert(ResultMessage(
        subtype="result",
        duration_ms=301_000,
        duration_api_ms=301_000,
        is_error=True,
        num_turns=1,
        session_id="sdk-server-error",
        stop_reason="stop_sequence",
        errors=[],
    ))

    assert error_events[-1].type == "error"
    assert error_events[-1].metadata["model_error"] == "server_error"
    turn_end = result_events[-1]
    assert turn_end.type == "turn_end"
    assert turn_end.metadata["ok"] is False
    assert turn_end.metadata["model_error"] == "server_error"
    assert turn_end.metadata["errors"] == ["server_error"]

    next_result = b._convert(ResultMessage(
        subtype="result",
        duration_ms=10,
        duration_api_ms=10,
        is_error=False,
        num_turns=1,
        session_id="sdk-server-error",
        stop_reason="stop_sequence",
    ))[-1]
    assert next_result.metadata["model_error"] == ""
    assert next_result.metadata["errors"] == []


def test_result_uuid_is_carried_as_durable_turn_event_id():
    event = _backend()._convert(ResultMessage(
        subtype="result",
        duration_ms=10,
        duration_api_ms=10,
        is_error=False,
        num_turns=1,
        session_id="sdk-session",
        stop_reason="end_turn",
        uuid="result-uuid-1",
    ))[-1]

    assert event.metadata["event_id"] == "result-uuid-1"


def test_result_uses_deferred_context_without_losing_aggregate_usage():
    from app.usage_contract import DeferredContext

    event = _backend()._convert(ResultMessage(
        subtype="result",
        duration_ms=10,
        duration_api_ms=10,
        is_error=False,
        num_turns=2,
        session_id="sdk-session",
        stop_reason="end_turn",
        usage={
            "input_tokens": 12_000,
            "output_tokens": 500,
            "cache_read_input_tokens": 8_000,
            "cache_creation_input_tokens": 1_000,
        },
    ))[-1]

    assert event.usage.aggregate.input_tokens == 12_000
    assert event.usage.aggregate.model_calls == 2
    assert isinstance(event.usage.current, DeferredContext)
    assert event.metadata["context_deferred"] is True
    assert event.metadata["context_known"] is False


def test_tool_failure_preserves_stable_use_id_and_explicit_error():
    backend = _backend()
    started = backend._convert(AssistantMessage(
        content=[ToolUseBlock(id="tool-1", name="Read", input={"file_path": "/x"})],
        model="claude-sonnet-5[1m]",
    ))
    completed = backend._convert(UserMessage(
        content=[ToolResultBlock(
            tool_use_id="tool-1",
            content="file not found",
            is_error=True,
        )],
    ))

    assert started[0].metadata["tool_use_id"] == "tool-1"
    assert completed[0].metadata == {
        "tool_use_id": "tool-1",
        "is_error": True,
    }
    assert completed[0].content == "file not found"


# --- #130: big-int tool arguments are flagged before a float64 parse eats them ---

_BIG = 1917704623170653147  # real Yandex.Direct ad id from docs/tasks/129/research.md


def _warnings(caplog, tool_input, name="mcp__yandex-direct__update_text_ad"):
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.backend_claude"):
        _backend()._convert(AssistantMessage(
            content=[ToolUseBlock(id="t-1", name=name, input=tool_input)],
            model="claude-sonnet-5[1m]",
        ))
    return [r.getMessage() for r in caplog.records if "big-int tool arg" in r.getMessage()]


def test_big_int_tool_arg_is_logged_with_tool_name_and_field_path(caplog):
    msgs = _warnings(caplog, {"ad_id": _BIG, "title2": "Договор"})

    assert len(msgs) == 1
    assert "mcp__yandex-direct__update_text_ad" in msgs[0]
    assert ".ad_id" in msgs[0]
    assert str(_BIG) in msgs[0]


def test_big_int_found_inside_nested_dicts_and_lists(caplog):
    msgs = _warnings(caplog, {"batch": [{"ids": [1, _BIG]}, {"ids": [2]}]})

    assert len(msgs) == 1
    assert ".batch[0].ids[1]" in msgs[0]


def test_every_big_int_gets_its_own_line(caplog):
    msgs = _warnings(caplog, {"a": _BIG, "b": -_BIG - 5})

    assert len(msgs) == 2
    assert {".a", ".b"} == {m.split(" = ")[0].rsplit(" ", 1)[-1] for m in msgs}


def test_safe_tool_args_log_nothing(caplog):
    # 2**53 itself is exactly representable; strings, bools and floats are not our business
    assert _warnings(caplog, {
        "ad_id": str(_BIG),
        "campaign_id": 713339200,
        "edge": 2 ** 53,
        "enabled": True,
        "ratio": 1.5,
        "text": f"id {_BIG} came back from list_ads",
    }) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("total_tokens", "expected"), [(10_000, True), (950_000, False)])
async def test_connected_normal_handoff_receipt_uses_live_complete_context(
    total_tokens, expected, monkeypatch,
):
    monkeypatch.delenv("CLAUDE_BASH_HOOK_ENABLED", raising=False)
    backend = ClaudeBackend(
        model="claude-sonnet-5[1m]", cwd="/tmp", system_prompt="current",
        resume_session_id="validated-session",
    )
    prepared = SimpleNamespace(
        packet={"schema_version": 1, "recent_messages": []},
        packet_sha256="a" * 64,
        project_docs=(),
    )
    manifest = backend.build_handoff_manifest(
        prepared, validation_profile=False,
    )
    descriptor = backend.handoff_expected_capabilities()
    backend._client = SimpleNamespace(
        options=SimpleNamespace(
            model=backend.model,
            resume="validated-session",
            system_prompt=None,
            tools=None,
            allowed_tools=[],
            mcp_servers=None,
            disallowed_tools=descriptor["normal_tool_fingerprint"] and [
                "ScheduleWakeup", "CronCreate", "CronDelete", "CronList",
                "Workflow",
            ],
            setting_sources=["user", "project", "local"],
            permission_mode="default",
            can_use_tool=lambda *_args: None,
            hooks=None,
        ),
        _query=SimpleNamespace(
            _initialization_result={
                "commands": [], "agents": [], "models": [],
            },
            get_mcp_status=AsyncMock(return_value={"mcpServers": []}),
        ),
    )
    backend._verify_pinned_versions = AsyncMock(return_value={
        "cli_version": descriptor["cli_version"],
        "sdk_version": descriptor["sdk_version"],
    })
    backend.context_usage = AsyncMock(return_value={
        "total_tokens": total_tokens,
        "max_tokens": 967_000,
    })

    receipt = await backend.verify_handoff_normal_surface(
        prepared=prepared,
        expected_configuration_sha256=manifest.configuration_sha256,
        expected_descriptor=descriptor,
    )

    assert receipt["ok"] is expected
    assert receipt["live_context_preflight"]["counting_method"] == (
        "provider_reported_complete_context"
    )
    assert receipt["live_context_preflight"]["candidate_upper_tokens"] == total_tokens
    if not expected:
        assert receipt["failure"]["kind"] == "context_overflow"
