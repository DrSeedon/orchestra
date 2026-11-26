from secrets import token_urlsafe
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app import db
from app.backend_codex import CodexBackend, _codex_cost
from app.session import AgentSession


def save_chat(session_id, model, runtime="codex", status="idle"):
    session = AgentSession(id=session_id, name=session_id, scope="/project", cwd="/project",
                           model=model, backend_type=runtime)
    db.save_session({**session._to_db_dict(), "status": status})
    return session


def test_codex_speed_dashboard_auth_and_persistence(monkeypatch):
    from app.auth import create_session
    from app.deps import manager
    from app.main import app

    db.init_db()
    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", token_urlsafe(16))
    internal_token = token_urlsafe(16)
    monkeypatch.setenv("INTERNAL_TOKEN", internal_token)
    stored = save_chat("stored", "gpt-6.2-sol")
    live = save_chat("live", "gpt-6.2-sol")
    live.loaded = True
    monkeypatch.setitem(manager.sessions, live.id, live)
    save_chat("hub", "hub-gpt-6.2-sol", "hub")
    save_chat("archived", "gpt-6.2-sol", status="archived")
    client = TestClient(app)
    payload = {"scope": "/project", "speed": "fast"}
    path = "/api/sessions/stored/codex-speed"
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, json=payload, headers={
        "Authorization": f"Bearer {internal_token}",
    }).status_code == 403
    client.cookies.set("session", create_session("operator"))
    assert client.post(path, json={**payload, "speed": "ultrafast"}).status_code == 422
    assert client.post("/api/sessions/hub/codex-speed", json=payload).status_code == 409
    assert client.post("/api/sessions/archived/codex-speed", json=payload).status_code == 404
    assert client.post(path, json=payload).json() == {"codex_speed": "fast"}
    assert manager.get_by_name("stored", "/project").codex_speed == "fast"
    db.save_session(stored._to_db_dict())
    assert db.get_session(stored.id)["codex_speed"] == "fast"

    assert client.post("/api/sessions/live/codex-speed", json=payload).json() == {"codex_speed": "fast"}
    assert live.codex_speed == "fast"
    sessions = {s["name"]: s for s in client.get("/api/sessions?scope=/project").json()}
    assert sessions["live"]["codex_fast_allowance_multiplier"] == 2
    assert sessions["live"]["codex_speed"] == "fast"
    assert sessions["hub"]["codex_fast_allowance_multiplier"] is None
    assert client.post(path, json={**payload, "speed": "standard"}).json() == {"codex_speed": "standard"}
    assert db.get_session(stored.id)["codex_speed"] == "standard"


def test_codex_speed_migration_preserves_old_rows():
    db.init_db()
    save_chat("existing", "gpt-6.2-sol")
    with db._conn() as conn:
        conn.execute("ALTER TABLE sessions DROP COLUMN codex_speed")
        conn.execute("ALTER TABLE turn_usage DROP COLUMN codex_speed")
    db.init_db()
    db.init_db()
    assert db.get_session("existing")["codex_speed"] == "standard"
    with db._conn() as conn:
        assert "codex_speed" in {row[1] for row in conn.execute("PRAGMA table_info(turn_usage)")}


@pytest.mark.asyncio
async def test_native_codex_speed_pins_turn_prices_and_is_recorded(monkeypatch):
    monkeypatch.setattr("app.provider_safety.verify_provider_egress", AsyncMock())
    monkeypatch.setattr("app.provider_safety.record_provider_activity", MagicMock())
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    db.init_db()
    session = save_chat("codex-speed", "gpt-6.2-sol")
    session._log = MagicMock()
    session._persist = MagicMock()
    session._submit_db_write = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    session._spawn_bg = lambda coro: coro.close()
    session._hibernate.schedule = MagicMock()
    backend = CodexBackend(model=session.model, cwd="/project", speed_source=lambda: session.codex_speed)
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "same-thread"
    backend._request = AsyncMock(side_effect=[
        {"turn": {"id": "fast-turn"}}, {}, {"turn": {"id": "standard-turn"}},
    ])

    for index, speed in enumerate(("fast", "standard"), 1):
        session.codex_speed = speed
        turn_id = f"{speed}-turn"
        await backend.send("next")
        request = backend._request.await_args.args
        assert request[0] == "turn/start"
        assert request[1]["threadId"] == "same-thread"
        assert request[1]["serviceTierForTurn"] == ("priority" if speed == "fast" else "default")
        if speed == "fast":
            session.codex_speed = "standard"
            await backend.send("steer")
            assert backend._request.await_args.args[0] == "turn/steer"
            assert "serviceTierForTurn" not in backend._request.await_args.args[1]
        backend._thread_usage_total = {
            "input_tokens": 1000 * index,
            "cached_input_tokens": 800 * index,
            "cache_write_input_tokens": 100 * index,
            "output_tokens": 20 * index,
        }
        events = backend._convert_notification({
            "method": "turn/completed",
            "params": {"threadId": "same-thread", "turn": {"id": turn_id, "status": "completed"}},
        })
        event = next(event for event in events if event.type == "turn_end")
        standard_cost = (100 * 2 + 800 * 0.10 + 100 * 2.5 + 20 * 10) / 1e6
        assert event.metadata["codex_speed"] == speed
        assert event.metadata["cost_usd"] == pytest.approx(standard_cost * (2 if speed == "fast" else 1))
        session._turns.handle_turn_end(event)

    with db._conn() as conn:
        rows = conn.execute("SELECT codex_speed, billing_mode, cost_usd FROM turn_usage ORDER BY id").fetchall()
    assert [tuple(row) for row in rows] == [
        ("fast", "subscription", pytest.approx(standard_cost * 2)),
        ("standard", "subscription", pytest.approx(standard_cost)),
    ]
    assert any("Codex Fast" in call.args[1] for call in session._log.call_args_list)
    assert session.cost_usd == pytest.approx(standard_cost * 3)

    from app.main import app

    monkeypatch.setenv("OWNER_MODE", "1")
    data = TestClient(app).get("/api/usage/turns?scope=/project").json()["turns"]
    assert [turn["codex_speed"] for turn in data] == ["standard", "fast"]


def test_fast_pricing_keeps_cached_input_discount():
    standard = _codex_cost("gpt-6.2-sol", 1000, 900, 0, 20)
    assert _codex_cost("gpt-6.2-sol", 1000, 900, 0, 20, speed="fast") == pytest.approx(2 * standard)
