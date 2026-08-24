"""#298 focused RED checks outside the immutable routing matrix."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_t14_spark_codex_session_failure_handoffs_without_retry(tmp_path, monkeypatch):
    from app import db
    from app.events import AgentEvent
    from app.session import AgentSession, AgentStatus

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "spark-session.db")
    db.init_db()
    class FakeCodex:
        active_turn_id = "spark-turn"
        sends = 0

        async def send(self, _message):
            self.sends += 1

        async def events(self):
            yield AgentEvent(type="error", content="rate_limit")
            yield AgentEvent(type="turn_end", metadata={
                "ok": False, "stop_reason": "rate_limit", "num_turns": 1,
            })

    session = AgentSession(
        id="spark-test", name="spark-test", scope="/test", cwd="/tmp",
        model="gpt-5.3-codex-spark", backend_type="codex",
    )
    session.task_id = "task-298"
    session.routing_metadata = {
        "openness": "closed", "complexity": "deterministic", "task_id": "task-298",
    }
    session.status = AgentStatus.RUNNING
    session._backend = FakeCodex()
    spawned = []

    def capture(coro):
        spawned.append(coro)
        coro.close()

    session._spawn_bg = capture
    session._log = lambda *_args, **_kwargs: None
    session._persist = lambda: None
    await session._backend.send("initial Spark turn")
    await session._turn_event_loop()

    retry_spawns = [
        coro for coro in spawned
        if getattr(coro, "cr_code", None)
        and coro.cr_code.co_name == "_rate_limit_retry"
    ]
    assert retry_spawns == []
    assert session._backend.sends == 1
    assert session._rate_limit_retries == 0
    assert session.status is AgentStatus.IDLE
    assert getattr(session, "routing_status", None) == "handoff_luna"
    assert session.task_id == "task-298"
    assert getattr(session, "routing_metadata", {}).get("handoff_model") == "gpt-5.6-luna"


@pytest.mark.asyncio
async def test_t15_route_admission_serializes_last_lease():
    import importlib.util

    spec = importlib.util.find_spec("app.openrouter_broker")
    assert spec is not None, "#298 OpenRouter broker module is missing"
    broker_module = __import__("app.openrouter_broker", fromlist=["OpenRouterBroker"])
    broker_cls = getattr(broker_module, "OpenRouterBroker", None)
    assert broker_cls is not None, "#298 broker class is missing"
    broker = broker_cls(daily_limit=1, minute_limit=1)
    first, second = await asyncio.gather(
        broker.acquire(
            model="stealth/ox-alpha",
            price_proof={"prompt": 0, "completion": 0},
        ),
        broker.acquire(
            model="stealth/ox-alpha",
            price_proof={"prompt": 0, "completion": 0},
        ),
    )
    assert sorted([first.granted, second.granted]) == [False, True]


@pytest.mark.asyncio
async def test_t17_ox_unknown_price_is_rejected_before_http_lease():
    import importlib.util

    spec = importlib.util.find_spec("app.openrouter_broker")
    assert spec is not None, "#298 OpenRouter broker module is missing"
    broker_module = __import__("app.openrouter_broker", fromlist=["OpenRouterBroker"])
    broker = broker_module.OpenRouterBroker(daily_limit=1, minute_limit=1)
    lease = await broker.acquire(
        model="stealth/ox-alpha",
        price_proof={"prompt": None, "completion": 0},
    )
    assert lease.granted is False
