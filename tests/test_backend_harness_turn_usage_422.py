from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID


def _persist_harness_event(tmp_path, monkeypatch, *, error: bool):
    import app.db as dbmod
    import app.session_turns as session_turns
    from app.backend_harness import HarnessBackend
    from app.session import AgentSession

    isolated_db = tmp_path / "turn-usage.db"
    monkeypatch.setattr(dbmod, "DB_PATH", isolated_db)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(isolated_db))
    assert dbmod.DB_PATH == isolated_db
    assert dbmod.DB_PATH != dbmod._DEFAULT_DB_PATH
    dbmod.init_db()
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr(
        session_turns,
        "_cached_quota_snapshot",
        lambda _runtime, _model: {
            "state": {
                "quota_five_hour_pct": None,
                "quota_seven_day_pct": None,
                "quota_primary_pct": None,
                "quota_sampled_at": None,
            },
            "display": (),
        },
    )

    backend = HarnessBackend(
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        cwd=str(tmp_path),
    )
    if error:
        end = backend._error_turn_end("controlled failure")
    else:
        loop = SimpleNamespace(last_usage={"prompt_tokens": 11})
        end = backend._turn_end(loop, ok=True, stop_reason="end_turn")

    event_id = str(end.metadata.get("event_id") or "")
    UUID(event_id)
    session = AgentSession(
        id=f"session-{'error' if error else 'ok'}",
        name=f"harness-{'error' if error else 'ok'}",
        scope="/test",
        cwd=str(tmp_path),
        model=backend.model,
        backend_type="harness",
    )
    session._log = lambda *_args, **_kwargs: None
    session._persist = lambda: None
    session._spawn_bg = lambda coro: coro.close()
    session._hibernate.schedule = MagicMock()
    session._submit_db_write = (
        lambda operation, *args, **kwargs: operation(*args, **kwargs)
    )
    session._turns.handle_turn_end(end)

    with dbmod._conn() as connection:
        row = connection.execute(
            "SELECT * FROM turn_usage WHERE event_id=?", (event_id,)
        ).fetchone()
    return event_id, row


def test_t422_harness_success_and_error_turns_persist_zero_cost_usage(
    tmp_path, monkeypatch,
) -> None:
    success_id, success = _persist_harness_event(
        tmp_path / "success", monkeypatch, error=False,
    )
    error_id, failure = _persist_harness_event(
        tmp_path / "error", monkeypatch, error=True,
    )

    assert success_id != error_id
    assert success is not None, "Harness success turn is absent from turn_usage"
    assert failure is not None, "Harness error turn is absent from turn_usage"
    assert success["runtime"] == failure["runtime"] == "harness"
    assert success["cost_usd"] == failure["cost_usd"] == 0
    assert success["cost_unaccounted"] == failure["cost_unaccounted"] == 0
    assert success["ok"] == 1
    assert failure["ok"] == 0
