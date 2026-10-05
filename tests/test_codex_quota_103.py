from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.backend_codex import CodexBackend
from app.session import AgentSession


def test_exhausted_codex_quota_reports_cached_reset_without_retry(monkeypatch):
    reset = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    reset_text = reset.isoformat().replace("+00:00", "Z")
    from app.routes import system

    monkeypatch.setattr(system, "_codex_usage_cache", {
        "data": {
            "primary": {
                "utilization": 100, "window_minutes": 300,
                "resets_at": reset_text,
            },
            "secondary": {
                "utilization": 99, "window_minutes": 10080,
                "resets_at": "2099-01-01T00:00:00Z",
            },
        },
        "ts": 1.0,
    })
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    event = backend._convert_notification({
        "method": "error",
        "params": {
            "willRetry": True,
            "error": {
                "codexErrorInfo": "usageLimitExceeded",
                "message": "usage limit reached",
            },
        },
    })[0]
    session = AgentSession(
        id="codex-quota-103", name="codex-quota", scope="/tmp", cwd="/tmp",
        backend_type="codex", model="gpt-5.6-sol",
    )
    session._log = MagicMock()
    session._spawn_bg = MagicMock(side_effect=lambda coroutine: coroutine.close())

    session._handle_event(event)

    assert event.metadata["codex_quota_exhausted"] is True
    assert session._session_limit_hit is True
    session._log.assert_called_once()
    assert session._log.call_args.args[0] == "error"
    assert f"5h {reset_text}" in session._log.call_args.args[1]
    assert "2099-01-01T00:00:00Z" not in session._log.call_args.args[1]
    session._spawn_bg.assert_not_called()


def test_quota_classifier_is_limited_to_exhaustion_codes():
    for code in ("usageLimitExceeded", "sessionBudgetExceeded"):
        assert CodexBackend._classify_error({"codexErrorInfo": code}) == "rate_limit"
    assert CodexBackend._classify_error({
        "status": 429, "codexErrorInfo": "tooManyRequests",
    }) == "error"


def test_retryable_codex_429_is_not_terminal_quota():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    event = backend._convert_notification({
        "method": "error",
        "params": {
            "willRetry": True,
            "error": {
                "status": 429,
                "codexErrorInfo": "tooManyRequests",
                "message": "rate limit; retrying",
            },
        },
    })[0]

    assert event.type == "status"
    assert "codex_quota_exhausted" not in event.metadata


def test_unknown_exhausted_codex_window_reports_both_labeled_resets(monkeypatch):
    from app.routes import system

    monkeypatch.setattr(system, "_codex_usage_cache", {
        "data": {
            "primary": {"window_minutes": 300, "resets_at": "2099-01-01T00:00:00Z"},
            "secondary": {"window_minutes": 10080, "resets_at": "2099-02-01T00:00:00Z"},
        },
        "ts": 1.0,
    })
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    event = backend._convert_notification({
        "method": "error",
        "params": {"error": {
            "codexErrorInfo": "sessionBudgetExceeded",
            "message": "usage limit reached",
        }},
    })[0]
    session = AgentSession(
        id="codex-quota-103-unknown", name="codex-quota", scope="/tmp", cwd="/tmp",
        backend_type="codex", model="gpt-5.6-sol",
    )
    session._log = MagicMock()
    session._spawn_bg = MagicMock()

    session._handle_event(event)

    output = session._log.call_args.args[1]
    assert "5h 2099-01-01T00:00:00Z" in output
    assert "7d 2099-02-01T00:00:00Z" in output
