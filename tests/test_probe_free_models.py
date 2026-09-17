"""#V-582 — the probe's verdict, with no network involved.

The whole point of the tool is that advertising tools is not passing: a route that calls
the tool and then answers without its result must be classified as a failure. That is the
exact defect that kept `nvidia/nemotron-3-ultra-550b-a55b:free` in our catalog.
"""

import json

from scripts import probe_free_models as probe_tool

TOOL_CALL = {
    "id": "call_1",
    "function": {"name": "line_count", "arguments": json.dumps({"path": "app/quota_gate.py"})},
}


def _responses(monkeypatch, *rounds):
    calls = []

    def fake_post(key, model, messages, timeout):
        calls.append(messages)
        return rounds[len(calls) - 1]

    monkeypatch.setattr(probe_tool, "_post", fake_post)
    return calls


def test_route_answering_from_the_tool_result_passes(monkeypatch):
    _responses(
        monkeypatch,
        (200, {"choices": [{"message": {"tool_calls": [TOOL_CALL]}}]}, 1.0),
        (200, {"choices": [{"message": {"content": "4242"}}]}, 0.5),
    )

    row = probe_tool.probe("k", "vendor/good:free", timeout=10, max_requests=2)

    assert row["status"] == "ok"
    assert (row["tool_call"], row["argument_ok"], row["used_result"]) == (True, True, True)
    assert row["requests"] == 2
    assert row["seconds"] == 1.5


def test_route_ignoring_the_tool_result_fails(monkeypatch):
    _responses(
        monkeypatch,
        (200, {"choices": [{"message": {"tool_calls": [TOOL_CALL]}}]}, 1.0),
        (200, {"choices": [{"message": {"content": "I cannot read files."}}]}, 0.5),
    )

    row = probe_tool.probe("k", "vendor/ignores:free", timeout=10, max_requests=2)

    assert row["status"] == "result_ignored"
    assert row["tool_call"] is True and row["used_result"] is False


def test_route_never_calling_the_tool_fails_after_one_request(monkeypatch):
    _responses(
        monkeypatch,
        (200, {"choices": [{"message": {"content": "sure, 12 lines"}}]}, 0.3),
    )

    row = probe_tool.probe("k", "vendor/chat:free", timeout=10, max_requests=2)

    assert row["status"] == "no_tool_call"
    assert row["requests"] == 1


def test_provider_error_is_reported_apart_from_a_model_failure(monkeypatch):
    _responses(
        monkeypatch,
        (429, {"error": {"message": "temporarily rate-limited upstream"}}, 0.2),
    )

    row = probe_tool.probe("k", "vendor/busy:free", timeout=10, max_requests=2)

    assert row["status"] == "rate_limited"
    assert "rate-limited" in row["detail"]


def test_request_ceiling_is_never_exceeded(monkeypatch):
    calls = _responses(
        monkeypatch,
        (429, {"error": {"message": "busy"}}, 0.1),
        (200, {"choices": [{"message": {"tool_calls": [TOOL_CALL]}}]}, 1.0),
        (200, {"choices": [{"message": {"content": "4242"}}]}, 0.5),
    )
    monkeypatch.setattr(probe_tool.time, "sleep", lambda _seconds: None)

    row = probe_tool.probe("k", "vendor/busy:free", timeout=10, max_requests=3)

    assert len(calls) == 3 and row["requests"] == 3
    assert row["status"] == "ok"
