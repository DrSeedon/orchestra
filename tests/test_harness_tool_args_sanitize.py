"""#V-596 — кривые аргументы вызова инструмента не должны отравлять остаток сессии.

Cohere отвергает ВЕСЬ запрос, если в истории есть вызов, чьи `arguments` — не
объект JSON: «invalid tool call provided in messages[42].tool_calls[0]: tool
arguments must be a stringified JSON object». Один такой вызов модели — и воркер
больше не может сделать ни одного хода (17.09.2026, i18n-guard-cohere).
"""

from app.harness.loop import _sanitize_tool_args


def _call(arguments):
    return {"id": "c1", "type": "function",
            "function": {"name": "bash", "arguments": arguments}}


def test_non_object_arguments_become_empty_object():
    calls = [_call('"строка"'), _call("[1, 2]"), _call("null"), _call("42")]
    _sanitize_tool_args(calls)
    assert [c["function"]["arguments"] for c in calls] == ["{}"] * 4


def test_broken_json_becomes_empty_object():
    calls = [_call('{"command": "ls"'), _call(""), _call("   "), _call(None)]
    _sanitize_tool_args(calls)
    assert [c["function"]["arguments"] for c in calls] == ["{}"] * 4


def test_valid_object_is_left_byte_for_byte():
    """Аргументы уезжают в следующий запрос рядом с подписью рассуждений —
    переформатировать их нельзя, только заменять заведомо негодные."""
    raw = '{"command": "ls -la", "путь": "а/б"}'
    calls = [_call(raw)]
    _sanitize_tool_args(calls)
    assert calls[0]["function"]["arguments"] == raw


def test_malformed_call_entry_does_not_crash():
    calls = [{"id": "c1"}, {"id": "c2", "function": None}, _call("{}")]
    _sanitize_tool_args(calls)
    assert calls[2]["function"]["arguments"] == "{}"
