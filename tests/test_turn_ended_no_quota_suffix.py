"""#277: turn ended keeps cost/turns/ctx, drops the quota-percent tail."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    from app.session import AgentSession
    return AgentSession(
        id="test-277", name="w1", scope="/test", cwd="/tmp",
        model="claude-opus-5[1m]", system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_turn_ended_line_has_cost_and_ctx_but_no_quota_percents(
    session, monkeypatch,
):
    from app.events import AgentEvent
    from app.routes import system

    sampled_at = 2_000_000_000.0
    monkeypatch.setattr(system, "_usage_cache", {
        "data": {
            "five_hour": {"utilization": 67, "resets_at": "2033-05-18T05:04:00+00:00"},
            "seven_day": {"utilization": 86, "resets_at": "2033-05-22T17:33:20+00:00"},
        },
        "ts": sampled_at,
        "token": None,
    })
    monkeypatch.setattr("app.session_turns.time.time", lambda: sampled_at + 1)
    logs = []
    session.backend_type = "claude"
    session.model = "claude-opus-5[1m]"
    session._last_context["percentage"] = 35
    session._cost.update_context_from_turn = lambda *_a, **_k: (True, None)
    session._log = lambda kind, content, **_kwargs: logs.append((kind, content))
    session._spawn_bg = lambda coro: coro.close()
    session._hibernate.schedule = MagicMock()

    session._turns.handle_turn_end(AgentEvent(type="turn_end", metadata={
        "ok": True, "stop_reason": "end_turn", "num_turns": 18,
    }))

    ended = next(c for k, c in logs if k == "status" and c.startswith("turn ended"))
    assert "18 turns" in ended
    assert "turn" in ended and "$" in ended
    assert "ctx:35%" in ended
    assert "5h:" not in ended
    assert "7d:" not in ended
    assert " reset " not in ended
