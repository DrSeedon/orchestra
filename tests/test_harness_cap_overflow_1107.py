"""V-1107: bounded head/tail output and one context recovery per turn, offline."""

import json
import re
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.harness import llm as llm_module, tools
from app.harness.llm import LLMEvent, OpenRouterClient
from app.harness.loop import AgentLoop


@pytest.mark.parametrize("cap", [100, 999, 30_000])
def test_cap_preserves_head_tail_and_exact_omission_count(monkeypatch, cap):
    monkeypatch.setenv("HARNESS_OUTPUT_CAP", str(cap))
    text = "COMMAND START\n" + "ж" * (cap * 2) + "\nFAILED: final error"
    result = tools._cap(text)
    assert len(result) <= cap
    assert result.startswith("COMMAND START\n")
    assert result.endswith("\nFAILED: final error")
    marker = re.search(r"\n\.\.\. \(truncated, (\d+) chars omitted from middle\) \.\.\.\n", result)
    assert marker
    head, tail = result[:marker.start()], result[marker.end():]
    assert int(marker[1]) == len(text) - len(head) - len(tail)
    assert abs(len(head) - len(tail)) <= 1


@pytest.mark.parametrize("text", ["", "короткий вывод", "x" * 100])
def test_cap_leaves_short_and_boundary_outputs_unchanged(monkeypatch, text):
    monkeypatch.setenv("HARNESS_OUTPUT_CAP", "100")
    assert tools._cap(text) == text


@pytest.mark.parametrize("cap", [0, 1, 20, 50])
def test_tiny_caps_never_exceed_budget(monkeypatch, cap):
    monkeypatch.setenv("HARNESS_OUTPUT_CAP", str(cap))
    assert len(tools._cap("x" * 300)) <= cap


def test_default_cap_keeps_the_end(monkeypatch):
    monkeypatch.delenv("HARNESS_OUTPUT_CAP", raising=False)
    text = "x" * tools.OUTPUT_CAP + "final error"
    assert len(tools._cap(text)) <= tools.OUTPUT_CAP
    assert tools._cap(text).endswith("final error")


def _history():
    history = [{"role": "system", "content": "system rules"},
               {"role": "user", "content": "original task"}]
    for i in range(8):
        history.extend([
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call-{i}", "type": "function",
                "function": {"name": "read", "arguments": "{}"},
            }]},
            {"role": "tool", "tool_call_id": f"call-{i}", "content": "x" * 1000},
        ])
    return history


def _assert_protocol(messages):
    calls = {tc["id"] for m in messages for tc in m.get("tool_calls", [])}
    assert calls == {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    assert [m["content"] for m in messages if m["role"] in ("system", "user")] == [
        "system rules", "original task", "latest task",
    ]


OVERFLOW = {"error": {"code": "context_length_exceeded", "message":
    "This model's maximum context length is 8192 tokens; you requested 9000 tokens."}}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected_requests,expected_ok", [
    (OVERFLOW, 2, True),
    ({"error": {"message": "Input exceeds the context window"}}, 2, True),
    ({"error": {"message": "Context length exceeded"}}, 2, True),
    ({"error": {"message": "upstream failure", "metadata": {
        "padding": "x" * 600, "raw": "maximum context length exceeded"}}}, 2, True),
    ({"error": {"message": "invalid tool arguments"}}, 1, False),
    ({"error": {"message": "context length must be a positive integer"}}, 1, False),
    ({"error": {"message": "requested context length must be a positive integer"}}, 1, False),
])
async def test_real_http_400_recovery(monkeypatch, tmp_path, failure,
                                      expected_requests, expected_ok):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content)["messages"])
        if len(requests) == 1:
            return httpx.Response(400, json=failure)
        return httpx.Response(200, content=(
            'data: {"choices":[{"delta":{"content":"recovered"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        ))

    # Provider bookkeeping and route admission are outside this HTTP/history contract.
    monkeypatch.setattr(llm_module, "_counter", SimpleNamespace(
        record_attempt_start=lambda: None, record_attempt_status=lambda *args: None))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OpenRouterClient("test", "test/model:free", http=http)
        monkeypatch.setattr(client, "_validate_route", lambda: None)
        loop = AgentLoop(client, None, str(tmp_path), _history(), [], max_context=100_000)
        compact = Mock(wraps=loop._fit_context)
        monkeypatch.setattr(loop, "_fit_context", compact)
        events = [event async for event in loop.run("latest task")]

    assert len(requests) == expected_requests
    assert loop.ok is expected_ok
    assert sum("token_budget" in c.kwargs for c in compact.call_args_list) == expected_requests - 1
    if expected_ok:
        assert len(requests[1]) < len(requests[0])
        _assert_protocol(requests[1])
        assert any(m.get("tool_call_id") == "call-7" for m in requests[1])
        assert any(event.type == "warning" and "retrying once" in event.content for event in events)
        assert [e.content for e in events if e.type == "text"] == ["recovered"]
        assert loop.truncated_dropped > 0
    else:
        assert loop.stop_reason == "error"
        assert "llm_error" in loop.error_detail
        assert loop.truncated_dropped == 0


def _overflow(status=400):
    request = httpx.Request("POST", "https://provider.invalid/chat")
    response = httpx.Response(status, json=OVERFLOW, request=request)
    return httpx.HTTPStatusError("provider rejected request", request=request, response=response)


class _ScriptedLLM:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    async def stream(self, *args, **kwargs):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        yield outcome
        yield LLMEvent("final", finish_reason="stop")


@pytest.mark.asyncio
async def test_second_overflow_fails_without_another_compaction(tmp_path, monkeypatch):
    llm = _ScriptedLLM([_overflow(), _overflow(), AssertionError("third request")])
    loop = AgentLoop(llm, None, str(tmp_path), _history(), [], max_context=100_000)
    compact = Mock(wraps=loop._fit_context)
    monkeypatch.setattr(loop, "_fit_context", compact)
    events = [event async for event in loop.run("latest task")]
    assert llm.calls == 2
    assert sum("token_budget" in c.kwargs for c in compact.call_args_list) == 1
    assert not loop.ok and loop.stop_reason == "context_limit"
    assert "after one compaction retry" in loop.error_detail
    assert len([e for e in events if e.type == "error"]) == 1
    assert all(m["role"] != "assistant" or m.get("tool_calls") for m in loop.history)


@pytest.mark.asyncio
async def test_recovery_budget_is_per_turn_not_per_round(tmp_path):
    call = LLMEvent("tool_call_done", tool_id="next", tool_name="unknown", arguments="{}")
    llm = _ScriptedLLM([_overflow(), call, _overflow()])
    loop = AgentLoop(llm, SimpleNamespace(has_tool=lambda name: False,
                                         display_name=lambda name: name),
                     str(tmp_path), _history(), [], max_context=100_000)
    events = [e async for e in loop.run("latest task")]
    assert llm.calls == 3
    assert not loop.ok and "after one compaction retry" in loop.error_detail
    assert len([e for e in events if e.type == "warning" and "retrying once" in e.content]) == 1


@pytest.mark.asyncio
async def test_anchor_only_history_fails_clearly_without_useless_retry(tmp_path):
    llm = _ScriptedLLM([_overflow()])
    loop = AgentLoop(llm, None, str(tmp_path), [{"role": "system", "content": "rules"}],
                     [], max_context=100_000)
    _ = [e async for e in loop.run("latest task")]
    assert llm.calls == 1
    assert not loop.ok and loop.stop_reason == "context_limit"
    assert "no history can be safely reduced" in loop.error_detail


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [_overflow(422), RuntimeError("context length exceeded")])
async def test_non_400_errors_are_not_retried(tmp_path, error):
    llm = _ScriptedLLM([error])
    loop = AgentLoop(llm, None, str(tmp_path), _history(), [], max_context=100_000)
    _ = [e async for e in loop.run("latest task")]
    assert llm.calls == 1
    assert not loop.ok and loop.stop_reason == "error"
    assert loop.truncated_dropped == 0


@pytest.mark.asyncio
async def test_interrupt_after_compaction_prevents_retry(tmp_path):
    llm = _ScriptedLLM([_overflow(), AssertionError("request after interrupt")])
    aborted = False
    loop = AgentLoop(llm, None, str(tmp_path), _history(), [], max_context=100_000,
                     abort=lambda: aborted)
    async for event in loop.run("latest task"):
        if event.type == "warning":
            aborted = True
    assert llm.calls == 1
    assert not loop.ok and loop.stop_reason == "aborted"
    _assert_protocol(loop.history)


@pytest.mark.asyncio
async def test_each_new_turn_gets_its_own_single_retry(tmp_path):
    answer = LLMEvent("text_delta", text="recovered")
    llm = _ScriptedLLM([_overflow(), answer, _overflow(), answer])
    loop = AgentLoop(llm, None, str(tmp_path), _history(), [], max_context=100_000)
    for _ in range(2):
        _ = [e async for e in loop.run("latest task")]
        assert loop.ok
    assert llm.calls == 4
