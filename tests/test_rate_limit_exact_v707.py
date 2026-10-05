from app.routes import system
from app.session_turns import _cached_quota_state


def test_codex_usage_preserves_fractional_percent_and_source_payload():
    source = {
        "rateLimits": {
            "planType": "plus",
            "primary": {
                "usedPercent": 12.375,
                "windowDurationMins": 300,
                "resetsAt": 1791189703,
            },
            "secondary": {
                "usedPercent": 42.125,
                "windowDurationMins": 10080,
                "resetsAt": 1791688420,
            },
            "credits": {"hasCredits": True, "unlimited": False, "balance": "3.25"},
        },
        "rateLimitsByLimitId": {},
    }

    usage = system._normalize_codex_usage(source)

    assert usage["primary"]["utilization"] == 12.375
    assert usage["secondary"]["utilization"] == 42.125
    assert usage["credits"]["balance"] == "3.25"
    assert usage["raw_payload"] == source
    provider = system._provider_usage_snapshot(None, usage)["codex"]
    assert [window["utilization"] for window in provider["windows"]] == [12.375, 42.125]
    assert provider["raw_payload"] == source


def test_claude_cli_fractional_windows_reach_cache_api_and_quota(monkeypatch):
    raw = {
        "status": "allowed_warning",
        "rateLimitType": "seven_day_opus",
        "utilization": 0.16327272727272726,
        "resetsAt": 1791688420,
        "unifiedWindows": {
            "five_hour": {"utilization": 0.123456789, "resetsAt": 1791189703},
            "seven_day": {"utilization": 0.234567891, "resetsAt": 1791688420},
            "seven_day_opus": {"utilization": 0.16327272727272726, "resetsAt": 1791688420},
            "seven_day_sonnet": {"utilization": 0.2718281828459045, "resetsAt": 1791688420},
        },
    }
    monkeypatch.setattr(system, "_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system.time, "time", lambda: 1_790_000_000.0)
    system.record_claude_rate_limit_event({"raw": raw, "event_id": "evt-1"})

    data = system._latest_claude_data({"five_hour": {"utilization": 12}})
    system._usage_cache["data"] = data
    system._usage_cache["ts"] = 1_790_000_000.0
    assert data["five_hour"]["utilization"] == 12.3456789
    assert data["seven_day"]["utilization"] == 23.4567891
    assert data["seven_day_opus"]["utilization"] == 16.327272727272727
    assert data["rate_limit_event"] == raw
    assert _cached_quota_state("claude", "claude-opus-5-5[1m]")[
        "quota_five_hour_pct"
    ] == 12.3456789
    windows = system._provider_usage_snapshot(data, None)["anthropic"]["windows"]
    assert {window["id"]: window["utilization"] for window in windows}["seven_day_sonnet"] == 27.18281828459045


def test_usage_snapshot_database_round_trips_fractional_windows_and_raw(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "usage.db")
    from app.db import init_db, usage_get_history, usage_save_snapshot

    init_db()
    providers = {
        "anthropic": {
            "windows": [{
                "id": "five_hour",
                "utilization": 12.3456789,
                "window_minutes": 300,
                "resets_at": "2026-10-05T05:00:00Z",
            }],
            "rate_limit_event": {"unifiedWindows": {"five_hour": {"utilization": 0.123456789}}},
        },
        "codex": {
            "windows": [{
                "id": "primary",
                "utilization": 12.375,
                "window_minutes": 300,
                "resets_at": "2026-10-05T05:00:00Z",
            }],
            "raw_payload": {"rateLimits": {"primary": {"usedPercent": 12.375}}},
        },
    }

    usage_save_snapshot(None, None, "", "", 0, 0, providers=providers)

    snapshot = usage_get_history(hours=1)[-1]
    assert snapshot["providers"] == providers
    assert snapshot["providers"]["anthropic"]["windows"][0]["utilization"] == 12.3456789
    assert snapshot["providers"]["codex"]["raw_payload"] == providers["codex"]["raw_payload"]
