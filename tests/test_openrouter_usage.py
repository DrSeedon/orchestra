import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request


def _request(*, headers=(), cookie=""):
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in headers]
    if cookie:
        raw_headers.append((b"cookie", cookie.encode()))
    return Request({
        "type": "http", "method": "GET", "path": "/api/usage/turns",
        "headers": raw_headers, "query_string": b"",
    })


def _record(provider, request_id, api_ms, cost, reasoning):
    provider_usage = {
        "completion_tokens_details": {"reasoning_tokens": reasoning},
    }
    if cost is not None:
        provider_usage["cost"] = cost
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "completion_tokens_details": {"reasoning_tokens": reasoning},
        "_provider_source_record": {
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "response": {"id": request_id, "provider_name": provider},
            "response_headers": {"x-openrouter-generation-id": request_id},
            "usage": provider_usage,
            "api_duration_ms": api_ms,
        },
    }
    if cost is not None:
        usage["cost"] = cost
    return usage


@pytest.mark.parametrize(
    "route_base_url, expected_endpoint",
    [
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/chat/completions"),
        (
            "https://user:secret@router.example:8443/custom/v1?api_key=private#fragment",
            "https://router.example:8443/custom/v1/chat/completions",
        ),
    ],
)
def test_openrouter_stream_preserves_api_source_metadata_and_usage(route_base_url, expected_endpoint):
    from app.harness.llm import OpenRouterClient

    sse = (
        b'data: {"id":"gen-1","model":"deepseek/deepseek-v4.1-flash",'
        b'"provider_name":"DeepInfra","choices":[{"delta":{"content":"ok"}}]}\n\n'
        b'data: {"id":"gen-1","model":"deepseek/deepseek-v4.1-flash",'
        b'"provider_name":"DeepInfra","choices":[],"usage":{"prompt_tokens":10,'
        b'"completion_tokens":4,"cost":0.125,"completion_tokens_details":{"reasoning_tokens":3}}}\n\n'
        b"data: [DONE]\n\n"
    )

    async def run():
        client = OpenRouterClient(
            api_key="test",
            model="deepseek/deepseek-v4.1-flash",
            base_url=route_base_url,
            http=httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream", "x-openrouter-generation-id": "gen-1"},
                content=sse,
            ))),
        )
        try:
            return [event async for event in client.stream([{"role": "user", "content": "hi"}], [])]
        finally:
            await client.aclose()

    final = asyncio.run(run())[-1]
    record = final.usage["_provider_source_record"]
    assert record["endpoint"] == expected_endpoint
    assert final.usage["cost"] == 0.125
    assert record["response"] == {
        "id": "gen-1", "model": "deepseek/deepseek-v4.1-flash", "provider_name": "DeepInfra",
    }
    assert record["response_headers"]["x-openrouter-generation-id"] == "gen-1"
    assert record["usage"]["completion_tokens_details"]["reasoning_tokens"] == 3
    assert isinstance(record["api_duration_ms"], int)


def test_harness_turn_aggregates_each_provider_round_and_reports_billing_timing_reasoning():
    from app.backend_harness import HarnessBackend

    backend = HarnessBackend("deepseek/deepseek-v4.1-flash", "/project")
    first = _record("DeepInfra", "req-1", 20, 0.125, 3)
    second = _record("InferenceNet", "req-2", 35, 0.25, 5)
    backend._accumulate(first)
    backend._accumulate(second)
    loop = SimpleNamespace(last_usage=second, round_usages=[first, second])

    event = backend._turn_end(loop, ok=True, stop_reason="end_turn")

    assert event.metadata["billing_mode"] == "openrouter_credit"
    assert event.metadata["cost_usd"] == pytest.approx(0.375)
    assert event.metadata["cost_unaccounted"] is False
    assert [row["response"]["provider_name"] for row in event.metadata["provider_source_records"]] == [
        "DeepInfra", "InferenceNet",
    ]
    assert [row["response"]["id"] for row in event.metadata["provider_source_records"]] == [
        "req-1", "req-2",
    ]
    assert event.metadata["api_duration_ms"] == 55
    assert event.metadata["reasoning_tokens"] == 8


def test_reasoning_total_remains_unknown_when_any_round_omits_it():
    from app.backend_harness import HarnessBackend

    backend = HarnessBackend("deepseek/deepseek-v4.1-flash", "/project")
    known = _record("DeepInfra", "req-1", 20, 0.1, 4)
    missing = {
        "prompt_tokens": 12,
        "completion_tokens": 2,
        "cost": 0.2,
        "_provider_source_record": {
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "response": {"id": "req-2", "provider_name": "InferenceNet"},
            "usage": {"prompt_tokens": 12, "completion_tokens": 2, "cost": 0.2},
            "api_duration_ms": 30,
        },
    }
    backend._accumulate(known)
    backend._accumulate(missing)

    event = backend._turn_end(
        SimpleNamespace(last_usage=missing, round_usages=[known, missing]), True, "end_turn",
    )

    assert event.metadata["reasoning_tokens"] is None
    assert len(event.metadata["provider_source_records"]) == 2


def test_free_missing_cost_is_known_zero_but_paid_missing_cost_is_unknown():
    from app.backend_harness import HarnessBackend

    free = HarnessBackend("nvidia/nemotron-3-ultra-550b-a55b:free", "/project")
    free_event = free._turn_end(SimpleNamespace(last_usage={}, round_usages=[]), True, "end_turn")
    assert free_event.metadata["billing_mode"] == "free"
    assert free_event.metadata["cost_usd"] == 0
    assert free_event.metadata["cost_unaccounted"] is False

    paid = HarnessBackend("deepseek/deepseek-v4.1-flash", "/project")
    missing = _record("DeepInfra", "req-no-cost", 12, None, 2)
    paid._accumulate(missing)
    paid_event = paid._turn_end(
        SimpleNamespace(last_usage=missing, round_usages=[missing]), True, "end_turn",
    )
    assert paid_event.metadata["billing_mode"] == "openrouter_credit"
    assert paid_event.metadata["cost_usd"] is None
    assert paid_event.metadata["cost_unaccounted"] is True


def test_paid_failure_without_usage_is_unaccounted_and_persists_as_unknown(
    tmp_path, monkeypatch,
):
    from app import auth, db
    from app.backend_harness import HarnessBackend
    from app.routes import system

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "usage.sqlite")
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(auth, "validate_session", lambda token: token == "owner-session")
    db.init_db()
    backend = HarnessBackend("deepseek/deepseek-v4.1-flash", "/project")
    backend._turn_started_at = 123.0
    event = backend._error_turn_end("network failure")
    assert event.metadata["billing_mode"] == "openrouter_credit"
    assert event.metadata["cost_usd"] is None
    assert event.metadata["cost_unaccounted"] is True
    assert event.metadata["ok"] is False

    db.turn_usage_add(
        event_id=event.metadata["event_id"], session_id="session-1", scope="/project",
        runtime="harness", model=backend.model, billing_mode=event.metadata["billing_mode"],
        ok=False, stop_reason="network failure", cost_usd=event.metadata["cost_usd"],
        cost_unaccounted=event.metadata["cost_unaccounted"], input_tokens=0, output_tokens=0,
        cache_read_tokens=0, cache_create_tokens=0, turn_duration_ms=event.metadata["turn_duration_ms"],
        api_duration_ms=event.metadata["api_duration_ms"], reasoning_tokens=None,
        provider_source_records=event.metadata["provider_source_records"],
    )
    result = asyncio.run(system.usage_turns_endpoint(
        _request(cookie="session=owner-session"), scope="/project",
    ))
    row = result["turns"][0]
    assert row["cost_usd"] is None
    assert row["cost_unaccounted"] is True
    assert row["billing_mode"] == "openrouter_credit"
    assert row["provider_source_records"] == []


def test_turn_manager_persists_missing_paid_cost_as_unknown(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from app import db, session_turns
    from app.backend_harness import HarnessBackend
    from app.session import AgentSession

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "usage.sqlite")
    db.init_db()
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr(
        session_turns,
        "_cached_quota_snapshot",
        lambda *_args, **_kwargs: {
            "state": {
                "quota_five_hour_pct": None,
                "quota_seven_day_pct": None,
                "quota_primary_pct": None,
                "quota_sampled_at": None,
            },
            "display": (),
        },
    )
    backend = HarnessBackend("deepseek/deepseek-v4.1-flash", "/project")
    priced = _record("DeepInfra", "req-priced", 20, 0.4, 3)
    missing = _record("DeepInfra", "req-no-cost", 12, None, 2)
    backend._accumulate(priced)
    backend._accumulate(missing)
    event = backend._turn_end(
        SimpleNamespace(last_usage=missing, round_usages=[priced, missing]), True, "end_turn",
    )
    session = AgentSession(
        id="paid-missing", name="paid-missing", scope="/project", cwd=str(tmp_path),
        model=backend.model, backend_type="harness",
    )
    session._log = lambda *_args, **_kwargs: None
    session._persist = lambda: None
    session._spawn_bg = lambda coro: coro.close()
    session._hibernate.schedule = MagicMock()
    session._submit_db_write = lambda operation, *args, **kwargs: operation(*args, **kwargs)
    session._turns.handle_turn_end(event)

    with db._conn() as connection:
        row = connection.execute(
            "SELECT cost_usd, cost_unaccounted, billing_mode, source_records_json "
            "FROM turn_usage WHERE event_id=?",
            (event.metadata["event_id"],),
        ).fetchone()
    assert row["cost_usd"] is None
    assert row["cost_unaccounted"] == 1
    assert row["billing_mode"] == "openrouter_credit"
    source_records = json.loads(row["source_records_json"])
    assert len(source_records) == 2
    assert source_records[0]["usage"]["cost"] == 0.4
    assert "cost" not in source_records[1]["usage"]


def test_provider_records_and_timing_are_accessible_only_by_project_scope(tmp_path, monkeypatch):
    from app import auth, db
    from app.backend_harness import HarnessBackend
    from app.routes import system

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "usage.sqlite")
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(auth, "validate_session", lambda token: token == "owner-session")
    db.init_db()
    backend = HarnessBackend("deepseek/deepseek-v4.1-flash", "/project")
    first = _record("DeepInfra", "req-1", 20, 0.125, 3)
    second = _record("InferenceNet", "req-2", 35, 0.25, 5)
    backend._accumulate(first)
    backend._accumulate(second)
    event = backend._turn_end(
        SimpleNamespace(last_usage=second, round_usages=[first, second]), True, "end_turn",
    )
    meta = event.metadata
    db.turn_usage_add(
        event_id=meta["event_id"], session_id="session-1", scope="/project",
        runtime="harness", model=backend.model, billing_mode=meta["billing_mode"],
        ok=True, stop_reason="end_turn", cost_usd=meta["cost_usd"],
        cost_unaccounted=meta["cost_unaccounted"], input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"], cache_read_tokens=meta["cache_read"],
        cache_create_tokens=meta["cache_create"], turn_duration_ms=17,
        api_duration_ms=meta["api_duration_ms"], reasoning_tokens=meta["reasoning_tokens"],
        duration_basis=meta["duration_basis"],
        provider_source_records=meta["provider_source_records"],
    )
    db.turn_usage_add(
        event_id="other-scope-turn", session_id="session-2", scope="/other-project",
        runtime="harness", model=backend.model, billing_mode="openrouter_credit",
        ok=True, stop_reason="end_turn", cost_usd=8.0, input_tokens=1, output_tokens=1,
        cache_read_tokens=0, cache_create_tokens=0,
        provider_source_records=[{"response": {"provider_name": "OtherProvider"}}],
    )

    result = asyncio.run(system.usage_turns_endpoint(
        _request(cookie="session=owner-session"), scope="/project",
    ))
    assert len(result["turns"]) == 1
    row = result["turns"][0]
    assert row["scope"] == "/project"
    assert row["cost_usd"] == pytest.approx(0.375)
    assert row["cost_unaccounted"] is False
    assert row["api_duration_ms"] == 55
    assert row["reasoning_tokens"] == 8
    assert [record["response"]["provider_name"] for record in row["provider_source_records"]] == [
        "DeepInfra", "InferenceNet",
    ]

    import app.auth as auth
    import app.mcp_proof as mcp_proof

    monkeypatch.setattr(system, "is_owner_mode", lambda: False)
    monkeypatch.setattr(auth, "validate_session", lambda _token: False)
    monkeypatch.setattr(auth, "check_internal_token", lambda header: header == "Bearer internal")
    monkeypatch.setattr(mcp_proof, "check_mcp_proof", lambda sid, proof: (
        sid == "agent-session" and proof == "valid-proof"
    ))
    monkeypatch.setattr(db, "get_session", lambda _sid: {"scope": "/project"})
    agent_result = asyncio.run(system.usage_turns_endpoint(
        _request(headers=(
            ("Authorization", "Bearer internal"),
            ("X-Orchestra-Session-Id", "agent-session"),
            ("X-Orchestra-Mcp-Proof", "valid-proof"),
        )),
        scope="/project",
    ))
    assert len(agent_result["turns"]) == 1
    assert agent_result["turns"][0]["scope"] == "/project"


@pytest.mark.parametrize("scope", [None, "", "  ", "\t "])
def test_usage_turns_requires_nonempty_scope(scope):
    from app.routes.system import usage_turns_endpoint

    response = asyncio.run(usage_turns_endpoint(_request(), scope=scope))
    assert response.status_code == 400
    assert json.loads(response.body) == {"error": "scope is required"}


def test_usage_turns_denies_internal_caller_outside_its_project_scope(monkeypatch):
    from fastapi import HTTPException

    from app import db
    from app.routes import system
    import app.auth as auth
    import app.mcp_proof as mcp_proof

    monkeypatch.setattr(system, "is_owner_mode", lambda: False)
    monkeypatch.setattr(auth, "validate_session", lambda _token: False)
    monkeypatch.setattr(auth, "check_internal_token", lambda _header: True)
    monkeypatch.setattr(mcp_proof, "check_mcp_proof", lambda session_id, proof: (
        session_id == "agent-session" and proof == "valid-proof"
    ))
    monkeypatch.setattr(db, "get_session", lambda _session_id: {"scope": "/agent-project"})
    with pytest.raises(HTTPException) as raised:
        asyncio.run(system.usage_turns_endpoint(
            _request(headers=(
                ("Authorization", "Bearer internal"),
                ("X-Orchestra-Session-Id", "agent-session"),
                ("X-Orchestra-Mcp-Proof", "valid-proof"),
            )),
            scope="/other-project",
        ))
    assert raised.value.status_code == 404


def test_usage_turns_rejects_spoofed_session_scope_without_mcp_proof(monkeypatch):
    from fastapi import HTTPException

    from app import db
    from app.routes import system
    import app.auth as auth
    import app.mcp_proof as mcp_proof

    monkeypatch.setattr(auth, "validate_session", lambda _token: False)
    monkeypatch.setattr(auth, "check_internal_token", lambda _header: True)
    monkeypatch.setattr(mcp_proof, "check_mcp_proof", lambda _sid, _proof: False)
    monkeypatch.setattr(db, "get_session", lambda _sid: {"scope": "/other-project"})
    with pytest.raises(HTTPException) as raised:
        asyncio.run(system.usage_turns_endpoint(
            _request(headers=(
                ("Authorization", "Bearer internal"),
                ("X-Orchestra-Session-Id", "spoofed-session"),
            )),
            scope="/other-project",
        ))
    assert raised.value.status_code == 404


def test_missing_round_cost_is_not_transferred_to_next_turn():
    from app.backend_harness import HarnessBackend
    from app.session_cost import CostTracker

    session = SimpleNamespace(
        session_id=None, _last_cost=0.0, _last_cost_cached=0.0, _context_cost=0.0,
        cost_usd=0.0, cost_usd_cached=0.0, _session_cost=0.0, total_turns=0,
        total_input_tokens=0, total_output_tokens=0, total_cache_read_tokens=0,
        total_cache_create_tokens=0,
    )
    tracker = CostTracker(session)
    backend = HarnessBackend("deepseek/deepseek-v4.1-flash", "/project")
    first = _record("DeepInfra", "req-priced", 20, 0.4, 0)
    missing = _record("DeepInfra", "req-unpriced", 20, None, 0)
    backend._accumulate(first)
    backend._accumulate(missing)
    terminal = backend._turn_end(
        SimpleNamespace(last_usage=missing, round_usages=[first, missing]), True, "end_turn",
    )
    assert terminal.metadata["cost_usd"] is None
    assert terminal.metadata["cost_unaccounted"] is True
    tracker.apply_turn_result(terminal.metadata, terminal.usage)
    assert session.cost_usd == 0
    assert backend._cumulative_cost == pytest.approx(0.4)

    backend._turn_cost_unaccounted = False
    backend._usage_baseline = (
        backend._cumulative_input, backend._cumulative_output, backend._cumulative_cached,
    )
    next_call = _record("DeepInfra", "req-next", 20, 0.2, 0)
    backend._accumulate(next_call)
    next_terminal = backend._turn_end(
        SimpleNamespace(last_usage=next_call, round_usages=[next_call]), True, "end_turn",
    )
    tracker.apply_turn_result(next_terminal.metadata, next_terminal.usage)
    assert session.cost_usd == pytest.approx(0.2)


def test_turn_usage_migration_adds_source_record_storage(tmp_path, monkeypatch):
    import sqlite3
    from app import db

    path = tmp_path / "old.sqlite"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE turn_usage (event_id TEXT PRIMARY KEY, ts TEXT NOT NULL)")
    assert db.ensure_turn_usage_timing_schema() == 12
    with db._conn() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(turn_usage)")}
    assert "source_records_json" in columns
