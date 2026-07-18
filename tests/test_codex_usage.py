import json
import time
from unittest.mock import AsyncMock

import pytest

from app.routes import system


def test_normalize_codex_usage_prefers_codex_bucket():
    result = {
        "rateLimits": {"planType": "plus", "primary": None},
        "rateLimitsByLimitId": {
            "codex": {
                "planType": "prolite",
                "primary": {
                    "usedPercent": 6,
                    "windowDurationMins": 10080,
                    "resetsAt": 1784957081,
                },
                "secondary": None,
                "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
            },
        },
        "rateLimitResetCredits": {"availableCount": 2},
    }

    usage = system._normalize_codex_usage(result)

    assert usage == {
        "plan_type": "prolite",
        "primary": {
            "utilization": 6,
            "window_minutes": 10080,
            "resets_at": "2026-07-25T05:24:41Z",
        },
        "secondary": None,
        "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
        "reset_credits": 2,
    }


@pytest.mark.asyncio
async def test_usage_endpoint_adds_codex_without_changing_anthropic(monkeypatch):
    anthropic = {"five_hour": {"utilization": 12}, "seven_day": {"utilization": 34}}
    codex = {
        "plan_type": "prolite",
        "primary": {"utilization": 6, "window_minutes": 10080, "resets_at": None},
        "secondary": None,
    }
    monkeypatch.setattr(system, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(system, "_usage_cache", {"data": anthropic, "ts": time.time(), "token": None})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_fetch_codex_usage", AsyncMock(return_value=codex))
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {"agents_count": 0})

    response = await system.get_usage()

    assert response["anthropic"] is anthropic
    assert response["codex"] is codex
    assert response["orchestra"] == {"agents_count": 0}


@pytest.mark.asyncio
async def test_codex_failure_does_not_break_anthropic_usage(monkeypatch):
    anthropic = {"five_hour": {"utilization": 12}}
    monkeypatch.setattr(system, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(system, "_usage_cache", {"data": anthropic, "ts": time.time(), "token": None})
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(system, "_fetch_codex_usage", AsyncMock(side_effect=RuntimeError("not logged in")))
    monkeypatch.setattr(system, "_get_agents_cost", lambda: {})

    response = await system.get_usage()

    assert response["anthropic"] is anthropic
    assert response["codex"] is None


@pytest.mark.asyncio
async def test_fetch_codex_usage_uses_app_server_protocol(monkeypatch):
    class FakeStdin:
        def __init__(self):
            self.messages = []

        def write(self, data):
            self.messages.append(json.loads(data))

        async def drain(self):
            pass

        def close(self):
            pass

    class FakeStdout:
        def __init__(self):
            self.lines = iter([
                b'{"id":1,"result":{"userAgent":"test"}}\n',
                b'{"id":2,"result":{"rateLimits":{"planType":"pro","primary":{"usedPercent":9,"windowDurationMins":300,"resetsAt":1784957081},"secondary":null}}}\n',
            ])

        async def readline(self):
            return next(self.lines, b"")

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    proc = FakeProcess()
    monkeypatch.setattr(system.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))

    usage = await system._fetch_codex_usage()

    assert usage["primary"]["window_minutes"] == 300
    assert [message["method"] for message in proc.stdin.messages] == [
        "initialize", "initialized", "account/rateLimits/read",
    ]
