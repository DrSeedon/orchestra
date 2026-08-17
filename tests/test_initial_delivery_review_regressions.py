from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_masked_initial_delivery_excludes_the_persisted_history_row(monkeypatch):
    import app.initial_deliveries as deliveries
    from app.secret_mask import mask_secrets
    from app.session import AgentSession

    delivery_id = "00000000-0000-4000-8000-000000000311"
    original_message = "Deploy with API_TOKEN=abcdefghijklmnop"
    persisted_message = mask_secrets(original_message)
    assert persisted_message != original_message

    monkeypatch.setattr(
        deliveries,
        "prepare_initial_delivery",
        lambda _delivery_id: {
            "delivery_state": "PREPARING",
            "user_log_id": 42,
            "history_user_message": persisted_message,
        },
    )
    monkeypatch.setattr(
        deliveries,
        "_delivery_payload",
        lambda _delivery_id: {
            "session_id": "session-311",
            "message": original_message,
        },
    )
    captured = {}

    class RecordingManager:
        async def send_initial_delivery(self, session_id, message, *, delivery):
            captured.update(
                session_id=session_id,
                message=message,
                delivery=delivery,
            )

    await deliveries.run_initial_delivery(delivery_id, manager=RecordingManager())
    delivery = captured["delivery"]
    assert delivery.history_user_message == persisted_message

    events = []

    class FakeBackend:
        active_turn_id = "native-turn-311"

        async def send(self, message):
            events.append(("backend", message))

    async def ensure_backend(*, exclude_history_users=(), **_kwargs):
        events.append(("history-exclusion", exclude_history_users))
        return FakeBackend()

    delivery.before_submit = AsyncMock()
    delivery.mark_submitted = AsyncMock()
    delivery.mark_unknown = AsyncMock()
    session = AgentSession(
        id="session-311",
        name="worker-311",
        scope="/scope-311",
        cwd="/tmp/worker-311",
        model="claude-sonnet-5[1m]",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
        is_orchestrator=True,
    )
    session._log = MagicMock()
    session._persist = MagicMock()
    session._ensure_backend = ensure_backend
    session._refresh_stale_backend = AsyncMock()
    session._apply_pending_identity_restart = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._shadow_reserve = AsyncMock(return_value=None)
    session._notify_scope_running = AsyncMock()

    await session.send(original_message, delivery=delivery)

    assert captured["message"] == original_message
    assert events == [
        ("history-exclusion", (persisted_message,)),
        ("backend", original_message),
    ]
