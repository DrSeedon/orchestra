from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("is_error,reported", [(True, False), (False, True)])
async def test_explicit_send_message_counts_only_after_success(is_error, reported):
    from app.events import AgentEvent
    from app.session import AgentSession, AgentStatus

    session = AgentSession(
        id="report-result", name="worker", scope="/scope", cwd="/tmp",
        parent_name="parent", created_at=datetime.now(timezone.utc),
    )
    session.status = AgentStatus.IDLE
    session._turn_logs = ["result was produced"]
    session.on_idle = AsyncMock()
    session._log = Mock()
    session._submit_db_write = Mock()

    session._handle_event(AgentEvent(
        "tool_use", "send_message", {"tool_name": "mcp__orchestra__send_message", "tool_use_id": "call-1"},
    ))
    assert session._did_report is False

    session._handle_event(AgentEvent(
        "tool_result", "delivery result", {"tool_use_id": "call-1", "is_error": is_error},
    ))
    assert session._did_report is reported

    session._turns.fire_auto_report()
    if session._auto_report_task:
        await session._auto_report_task
    assert session.on_idle.await_count == (0 if reported else 1)
