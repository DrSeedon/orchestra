"""Regression tests for preserving Claude rate-limit telemetry (task #441)."""

import builtins
import importlib
import json

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

try:
    from claude_agent_sdk import RateLimitEvent
    from claude_agent_sdk.types import RateLimitInfo
except ImportError:
    RateLimitEvent = None
    RateLimitInfo = None

import app.backend_claude as backend_claude
from app.backend_claude import ClaudeBackend


def _backend() -> ClaudeBackend:
    return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")


def test_rate_limit_event_preserves_exact_raw_utilization_and_all_fields():
    if RateLimitEvent is None or RateLimitInfo is None:
        pytest.skip("SDK does not expose rate-limit event types")
    utilization = 0.16327272727272726
    raw = {
        "status": "allowed_warning",
        "resetsAt": 1760000000,
        "rateLimitType": "seven_day",
        "utilization": utilization,
        "unifiedWindows": {
            "five_hour": {"utilization": 0.125, "resetsAt": 1759990000},
            "seven_day": {"utilization": utilization, "resetsAt": 1760000000},
        },
        "providerField": {"preserved": True},
    }
    message = RateLimitEvent(
        rate_limit_info=RateLimitInfo(
            status="allowed_warning",
            utilization=utilization,
            raw=raw,
        ),
        uuid="rate-limit-uuid",
        session_id="session-id",
    )

    events = _backend()._convert(message)

    assert len(events) == 1
    assert events[0].type == "status"
    assert events[0].content.startswith("RATE_LIMIT_RAW ")
    assert "0.16327272727272726" in events[0].content
    assert json.loads(events[0].content.removeprefix("RATE_LIMIT_RAW ")) == raw


def test_missing_rate_limit_event_class_does_not_break_import_or_dispatch():
    original_import = builtins.__import__

    def import_without_rate_limit_event(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "claude_agent_sdk" and "RateLimitEvent" in fromlist:
            raise ImportError("simulated old SDK")
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = import_without_rate_limit_event
    try:
        importlib.reload(backend_claude)
        assert backend_claude.RateLimitEvent is None
        events = _backend()._convert(AssistantMessage(
            content=[TextBlock("ordinary message")],
            model="claude-sonnet-5[1m]",
        ))
        assert events[0].content == "ordinary message"
    finally:
        builtins.__import__ = original_import
        importlib.reload(backend_claude)
