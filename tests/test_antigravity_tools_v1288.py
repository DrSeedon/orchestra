"""Offline stream/card regressions, with negative mutation controls (V-1288)."""

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app import backend_antigravity as agy
from app.session_turns import TurnManager


ROOT = Path(__file__).resolve().parents[1]


def step(name="read_file", args=None, *, state="ACTIVE", conv="conversation-a", index=1, **info):
    return {"event": "step_update", "step_update": {
        "step_type": "tool", "tool_name": name, "conversation_id": conv,
        "step_index": index, "state": state,
        "tool_info": {"parameters": {} if args is None else args, **info},
    }}


async def consume(tmp_path, monkeypatch, rows, *, resume=None, backend_cls=None):
    monkeypatch.setattr(agy, "ANTIGRAVITY_HOME_ROOT", tmp_path)
    context = SimpleNamespace(
        model="antigravity/test", cwd=str(tmp_path), system_prompt="test",
        mcp_servers={"orchestra": {"env": {"ORCHESTRA_SESSION_ID": "synthetic"}},
                     "docs": {}, "docs_extra": {}},
        context_limit=128000, resume_session_id=resume,
    )
    backend = (backend_cls or agy.AntigravityBackend)(context)
    backend.home = tmp_path / "synthetic"
    backend.home.mkdir(exist_ok=True)
    stdout = asyncio.StreamReader()
    for row in rows:
        stdout.feed_data((json.dumps(row, ensure_ascii=False) + "\n").encode())
    stdout.feed_data(b'{"event":"result","result":{"status":"SUCCESS"}}\n')
    stdout.feed_eof()
    stderr = asyncio.StreamReader()
    stderr.feed_eof()

    async def wait():
        return 0

    backend._process = SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0, wait=wait)
    await backend._consume()
    return [event async for event in backend.events()]


def tools(events):
    return [e for e in events if e.type in {"tool_use", "tool_result"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{}, {"Path": "/пример.py", "StartLine": 3}, None, []])
async def test_persistable_unicode_arguments_and_result_metadata(tmp_path, monkeypatch, args):
    events = tools(await consume(tmp_path, monkeypatch, [
        step(args=args), step(args=args, state="DONE", output="file body"),
    ]))
    use, result = events
    expected = args if isinstance(args, dict) else {}
    assert use.content == f"read_file: {json.dumps(expected, ensure_ascii=False)}"
    assert json.loads(use.content.partition(":")[2]) == expected
    assert use.metadata == {"tool_use_id": "agy-conversation-a-step-1",
                            "tool_name": "read_file", "short_name": "read_file", "input": expected}
    assert result.metadata == {**use.metadata, "is_error": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args,canonical,expected", [
    ("call_mcp_tool", {"ServerName": "orchestra", "ToolName": "send_message",
                       "Arguments": {"to": "parent", "message": "Полный отчёт"}},
     "mcp__orchestra__send_message", {"to": "parent", "message": "Полный отчёт"}),
    ("call_mcp_tool", {"ServerName": "orchestra", "ToolName": "list_agents", "Arguments": {}},
     "mcp__orchestra__list_agents", {}),
    ("mcp_orchestra_notify_user", {"reason": "review"}, "mcp__orchestra__notify_user", {"reason": "review"}),
    ("mcp_docs_extra_read_resource", {"uri": "test"}, "mcp__docs_extra__read_resource", {"uri": "test"}),
    ("mcp_unknown_read_resource", {}, "mcp_unknown_read_resource", {}),
    ("mcp__orchestra__list_agents", {}, "mcp__orchestra__list_agents", {}),
])
async def test_lazy_eager_mcp_identity_and_inputs(tmp_path, monkeypatch, name, args, canonical, expected):
    use, result = tools(await consume(tmp_path, monkeypatch, [
        step(name, args), step(name, state="DONE", output="Message sent"),
    ]))
    assert use.content == f"{canonical}: {json.dumps(expected, ensure_ascii=False)}"
    for event in (use, result):
        assert event.metadata["tool_name"] == canonical
        assert event.metadata["short_name"] == canonical.split("__", 2)[-1]
        assert event.metadata["input"] == expected
    if canonical == "mcp__orchestra__send_message":
        session = SimpleNamespace(parent_name="parent", parent_id="p-id", last_task_sender=None,
                                  _report_calls={}, _turn_gen=4, _did_report=False)
        manager = TurnManager(session)
        manager.track_parent_report(use, canonical)
        manager.track_parent_report(result, canonical)
        assert session._did_report is True


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"ServerName": "", "ToolName": "x", "Arguments": {}},
    {"ServerName": " ", "ToolName": "x", "Arguments": {}},
    {"ServerName": 1, "ToolName": "x", "Arguments": {}},
    {"ServerName": "orchestra", "ToolName": "", "Arguments": {}},
    {"ServerName": "orchestra", "ToolName": "x", "Arguments": []},
    {"ServerName": "orchestra", "ToolName": "x"},
])
async def test_malformed_lazy_envelopes_remain_visible(tmp_path, monkeypatch, bad):
    use, result = tools(await consume(tmp_path, monkeypatch, [
        step("call_mcp_tool", bad, state="DONE", output="raw"),
    ]))
    assert use.metadata["tool_name"] == result.metadata["tool_name"] == "call_mcp_tool"
    assert json.loads(use.content.partition(":")[2]) == bad


@pytest.mark.asyncio
async def test_repeated_updates_terminal_only_and_compaction_ids(tmp_path, monkeypatch):
    events = await consume(tmp_path, monkeypatch, [
        step(args={"Path": "a.py"}), step(args={"Path": "a.py"}),
        step(state="DONE", output="a"), step(state="DONE", output="a"),
        step(conv="conversation-b", state="DONE", output="b"),
        step(conv="conversation-c", state="ERROR", error={"message": "edit failed"}),
    ])
    emitted = tools(events)
    assert [e.type for e in emitted] == ["tool_use", "tool_result"] * 3
    assert [e.metadata["tool_use_id"] for e in emitted[::2]] == [
        "agy-conversation-a-step-1", "agy-conversation-b-step-1", "agy-conversation-c-step-1"]
    assert emitted[1].metadata["input"] == {"Path": "a.py"}
    assert emitted[-1].metadata["is_error"] is True
    assert "edit failed" in emitted[-1].content
    assert not any(e.type == "error" for e in events)
    end = next(e for e in events if e.type == "turn_end")
    assert end.metadata["ok"] is True
    assert end.metadata["stop_reason"] == "end_turn"
    assert "model_error" not in end.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("resume,expected", [(None, "agy-step-1"), ("resumed", "agy-resumed-step-1")])
async def test_id_fallback_and_resume(tmp_path, monkeypatch, resume, expected):
    use, result = tools(await consume(tmp_path, monkeypatch, [step(conv=None, state="DONE")], resume=resume))
    assert use.metadata["tool_use_id"] == result.metadata["tool_use_id"] == expected


@pytest.mark.asyncio
async def test_unicode_redaction_applies_to_content_and_both_metadata(tmp_path, monkeypatch):
    # Use synthetic environment values only; redaction must happen before serialization escapes Unicode.
    cls = agy.AntigravityBackend

    class WithSyntheticSecret(cls):
        def __init__(self, context):
            super().__init__(context)
            self._secrets = ["секрет-тест"]

    use, result = tools(await consume(tmp_path, monkeypatch, [
        step(args={"Path": "секрет-тест"}), step(state="DONE", output="секрет-тест"),
    ], backend_cls=WithSyntheticSecret))
    assert use.metadata["input"] == result.metadata["input"] == {"Path": "[redacted]"}
    assert "секрет-тест" not in json.dumps([vars(use), vars(result)], ensure_ascii=False)


def run_frontend(scenario="all", mutations=None):
    node = shutil.which("node")
    assert node, "Node is required for offline dashboard renderer checks"
    return subprocess.run(
        [node, str(ROOT / "tests/antigravity_tools_v1288_node.cjs"), scenario],
        input=json.dumps(mutations or {}), text=True, capture_output=True,
        cwd=ROOT, timeout=20,
    )


@pytest.mark.parametrize("scenario", ["aliases", "mcp", "bash", "read", "edit", "legacy"])
def test_frontend_production_renderers(scenario):
    result = run_frontend(scenario)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("before,after,probe", [
    ('f"{name}: {json.dumps(args, ensure_ascii=False)}"', 'name', "serialization"),
    ('f"agy-{conv}-step-{step.get(\'step_index\')}"', 'f"agy-step-{step.get(\'step_index\')}"', "identity"),
    ('if tool_id not in emitted_tools:', 'if True:', "deduplication"),
    ('name == "call_mcp_tool"', 'name == "disabled_call_mcp_tool"', "mcp"),
])
async def test_backend_mutation_controls(tmp_path, monkeypatch, before, after, probe):
    source = (ROOT / "app/backend_antigravity.py").read_text()
    assert before in source
    namespace = vars(agy).copy()
    exec(compile(source.replace(before, after, 1), agy.__file__, "exec"), namespace)
    events = tools(await consume(tmp_path, monkeypatch, [
        step("call_mcp_tool", {"ServerName": "orchestra", "ToolName": "list_agents", "Arguments": {}}),
        step("call_mcp_tool"), step("call_mcp_tool", state="DONE"),
    ], backend_cls=namespace["AntigravityBackend"]))

    def contract():
        use = events[0]
        if probe == "serialization":
            assert use.content == 'mcp__orchestra__list_agents: {}'
        elif probe == "identity":
            assert use.metadata["tool_use_id"] == "agy-conversation-a-step-1"
        elif probe == "deduplication":
            assert len(events) == 2
        else:
            assert use.metadata["tool_name"] == "mcp__orchestra__list_agents"

    with pytest.raises(AssertionError):
        contract()


@pytest.mark.parametrize("scenario,filename,before,after", [
    ("aliases", "tool-renderers.js", "'run_command': 'Bash'", "'run_command': 'Other'"),
    ("mcp", "tool-renderers.js", "name === 'call_mcp_tool'", "name === 'disabled_call_mcp_tool'"),
    ("bash", "chat.js", "exitCode: match ? Number(match[1]) : null", "exitCode: null"),
    ("read", "chat.js", "if (readResult.stat)", "if (false)"),
    ("edit", "chat.js", "const isToolError = Boolean(toolErrorMatch) || payload?.tool_is_error === true || payload?.tool_is_error === 1;",
     "const isToolError = Boolean(toolErrorMatch);"),
    ("aliases", "live-activity.js", "input = call.input;", "input = {};"),
])
def test_frontend_mutation_controls(scenario, filename, before, after):
    result = run_frontend(scenario, {filename: [before, after]})
    assert result.returncode != 0, f"mutation survived: {filename}: {before}"
    assert "AssertionError" in result.stderr, result.stdout + result.stderr
