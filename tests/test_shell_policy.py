import json
import os
import subprocess
from unittest.mock import AsyncMock

import pytest

from app.backend_claude import _classify_bash_payload, _pretool_output
from app.backend_codex import CodexBackend
from app.backend_grok import GrokBackend
from app.events import AgentEvent
from app.harness.tools import dispatch
from app.session import AgentSession
from app.shell_policy import (
    classify_shell_command,
    codex_wrapper_rule,
    violation_message,
)


@pytest.fixture
def rg_available(monkeypatch):
    monkeypatch.setattr(
        "app.shell_policy.shutil.which",
        lambda command: "/usr/bin/rg" if command == "rg" else None,
    )


@pytest.mark.parametrize("command", [
    "sleep 6",
    "sleep 1; sleep 10; tail log",
    "while true; do sleep 20; done",
    "timeout 60 sleep 60",
    "env MODE=test sleep 90",
    "bash -c 'sleep 30'",
    'sleep 5.5 "',
    'sleep "$DURATION"',
])
def test_long_shell_wait_is_blocked(command):
    assert classify_shell_command(command) == "long_sleep"


@pytest.mark.parametrize("command", [
    "kill -TERM 12; sleep 1; ps -p 12",
    "sleep 5",
    "timeout 5 sleep 60",
    "printf 'sleep 600'",
    "python - <<'PY'\nimport time\ntime.sleep(600)\nPY",
    "rg --files --hidden --no-ignore .",
    "rg -n TODO app",
    "printf x | grep x",
    "find . -mtime -2 -type f",
    "find . -newer marker -type f",
    "find . -exec rg -n TODO {} +",
    "find . -exec echo 'sleep 600' {} +",
    "find . -exec sleep 1 {} +",
    "find . -printf '%p\\n'",
    "find . -maxdepth 2 -type f",
    "find . -delete",
    "rg -n TODO app | grep generated",
])
def test_permitted_shell_commands_keep_their_semantics(command):
    assert classify_shell_command(command) is None


@pytest.mark.parametrize("command,rule", [
    ("find /workspace -name '*.py'", "recursive_find"),
    ("grep -R TODO .", "recursive_grep"),
    ("grep -rn TODO app", "recursive_grep"),
    ("find . -exec sleep 600 {} +", "long_sleep"),
])
def test_recursive_path_searches_are_classified(command, rule, rg_available):
    assert classify_shell_command(command) == rule


@pytest.mark.parametrize("command", [
    "find . -name '*.py'",
    "grep -R TODO .",
])
def test_recursive_search_fallback_passes_when_rg_is_unavailable(command, monkeypatch):
    monkeypatch.setattr("app.shell_policy.shutil.which", lambda _command: None)
    assert classify_shell_command(command) is None


@pytest.mark.parametrize("command,rule", [
    ("sleep 30; tail log", "long_sleep"),
    ("find . -name '*.py'", "recursive_find"),
    ("grep -R TODO .", "recursive_grep"),
])
def test_claude_pretooluse_denies_policy_violations(command, rule, rg_available):
    got = _classify_bash_payload({"command": command})
    assert got == rule
    output = _pretool_output(got)["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert violation_message(rule) in output["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "kill -TERM 12; sleep 1; ps -p 12",
    "printf x | grep x",
    "rg -n TODO app",
])
def test_claude_pretooluse_allows_permitted_commands(command):
    assert _classify_bash_payload({"command": command}) is None


def test_codex_managed_home_installs_path_policy_wrappers(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backend_codex._CODEX_HOME_ROOT", tmp_path / "managed-codex")
    backend = CodexBackend(model="gpt-6-luna", cwd="/tmp", mcp_servers={
        "orchestra": {"command": "python", "args": [], "env": {"ORCHESTRA_SESSION_ID": "sess-policy"}},
    })
    home = backend._prepare_codex_home()
    policy_bin = home / "policy-bin"
    assert "features.hooks=true" not in backend._codex_command()
    assert (policy_bin / "sleep").is_file()
    assert (policy_bin / "find").is_file()
    env = backend._build_env()
    assert env["PATH"].split(os.pathsep)[0] == str(policy_bin)
    shell_env = dict(env, PATH=env["PATH"])

    for command in (
        "sleep 1",
        "printf x | grep x",
        "printf ok",
        "echo ok && sleep 1",
        "python -c 'import subprocess; subprocess.run([\"sleep\", \"0.1\"], check=True)'",
    ):
        result = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=tmp_path,
            env=shell_env,
            text=True,
            capture_output=True,
            timeout=4,
        )
        assert result.returncode == 0, result.stderr

    script = tmp_path / "fixture.sh"
    script.write_text("#!/bin/sh\nsleep 0.1\n", encoding="utf-8")
    script.chmod(0o700)
    result = subprocess.run(
        ["/bin/bash", "-lc", "./fixture.sh"], cwd=tmp_path,
        env=shell_env, text=True, capture_output=True, timeout=4,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command,rule", [
    ("sleep 10", "long_sleep"),
    ("find . -name '*.py' | head -3", "recursive_find"),
    ("grep -R TODO .", "recursive_grep"),
])
def test_codex_direct_tool_shell_commands_are_classified(command, rule, rg_available):
    got = codex_wrapper_rule(
        command,
        [("/usr/lib/codex", ["codex", "app-server", "--stdio"])],
    )
    assert got == rule

    shell_command = codex_wrapper_rule(
        "sleep 10",
        [
            ("/bin/bash", ["/bin/bash", "-c", command]),
            ("/usr/lib/codex", ["codex", "app-server", "--stdio"]),
        ],
    )
    assert shell_command == rule

    nested_shell_command = codex_wrapper_rule(
        "sleep 10",
        [
            ("/bin/bash", ["/bin/bash", "-c", "sleep 10"]),
            ("/bin/bash", ["/bin/bash", "-lc", command]),
            ("/usr/lib/codex", ["codex", "app-server", "--stdio"]),
        ],
    )
    assert nested_shell_command == rule


@pytest.mark.parametrize("caller,argv,parent,parent_argv", [
    ("/usr/bin/python3", ["python3", "-c", "subprocess.run(...)"], "/usr/lib/codex", ["codex", "app-server"]),
    ("/bin/sh", ["/bin/sh", "./x.sh"], "/usr/lib/codex", ["codex", "app-server"]),
    ("/bin/bash", ["/bin/bash", "-c", "sleep 10"], "/usr/bin/make", ["make", "test"]),
    ("/bin/bash", ["/bin/bash", "-c", "sleep 10"], "/usr/bin/node", ["node", "runner.js"]),
])
def test_codex_wrapper_ignores_application_and_script_children(caller, argv, parent, parent_argv):
    assert codex_wrapper_rule(
        "sleep 10", [(caller, argv), (parent, parent_argv), ("/usr/lib/codex", ["codex", "app-server"])],
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("command,rule", [
    ("sleep 100; tail log", "long_sleep"),
    ("find . -name '*.py'", "recursive_find"),
    ("grep -R TODO .", "recursive_grep"),
])
async def test_grok_permission_gate_rejects_policy_violations(command, rule, rg_available):
    backend = GrokBackend(model="grok-4.5", cwd="/tmp")
    backend._write = AsyncMock()
    request = {
        "method": "session/request_permission",
        "params": {
            "toolCall": {
                "toolCallId": "tool-1", "title": "Bash",
                "rawInput": {"command": command},
            },
            "options": [
                {"kind": "allow-once", "optionId": "allow"},
                {"kind": "reject-once", "optionId": "reject"},
            ],
        },
    }
    await backend._answer_server_request("request-1", request)
    violation = backend._convert(backend._notifications.get_nowait())
    assert violation[0].type == "policy_violation"
    assert violation[0].metadata["rule"] == rule
    backend._write.assert_awaited_once()
    assert backend._write.await_args.args[0]["result"]["outcome"]["optionId"] == "reject"
    events = backend._tool_call_update({
        "toolCallId": "tool-1", "status": "failed", "content": "denied",
    })
    assert events[0].type == "tool_result"
    assert events[0].metadata["is_error"]
    assert violation_message(rule) in events[0].content
    assert classify_shell_command("printf x | grep x") is None


@pytest.mark.asyncio
async def test_grok_permitted_shell_uses_one_time_approval_only():
    backend = GrokBackend(model="grok-4.5", cwd="/tmp")
    backend._write = AsyncMock()
    await backend._answer_server_request("request-2", {
        "method": "session/request_permission",
        "params": {
            "toolCall": {
                "toolCallId": "tool-2", "title": "Bash",
                "rawInput": {"command": "sleep 1; ps"},
            },
            "options": [
                {"kind": "allow-always", "optionId": "persistent"},
                {"kind": "allow-once", "optionId": "once"},
                {"kind": "reject-once", "optionId": "reject"},
            ],
        },
    })
    assert backend._write.await_args.args[0]["result"]["outcome"]["optionId"] == "once"


@pytest.mark.asyncio
@pytest.mark.parametrize("command,blocked", [
    ("sleep 100; tail log", True),
    ("sleep 1; ps", False),
    ("printf x | grep x", False),
    ("rg -n TODO app", False),
])
async def test_harness_bash_guard(command, blocked):
    output, _ = await dispatch("bash", {"command": command}, "/tmp")
    if blocked:
        assert violation_message("long_sleep") == output
    else:
        assert not output.startswith("POLICY VIOLATION")


@pytest.mark.asyncio
@pytest.mark.parametrize("command,rule", [
    ("find . -name '*.py'", "recursive_find"),
    ("grep -R TODO .", "recursive_grep"),
])
async def test_harness_blocks_recursive_search(command, rule, rg_available):
    output, _ = await dispatch("bash", {"command": command}, "/tmp")
    assert output == violation_message(rule)


@pytest.mark.asyncio
async def test_harness_allows_find_when_rg_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("app.shell_policy.shutil.which", lambda _command: None)
    match = tmp_path / "result.py"
    match.write_text("ok\n", encoding="utf-8")

    output, _ = await dispatch(
        "bash", {"command": f"find {tmp_path} -name result.py"}, str(tmp_path),
    )

    assert output.splitlines()[-1] == str(match)


@pytest.mark.asyncio
async def test_session_journal_records_violation_rule_for_counts(monkeypatch):
    session = AgentSession(id="id", name="worker", scope="scope", cwd="/tmp")
    rows = []
    monkeypatch.setattr(session, "_log", lambda kind, content, **kwargs: rows.append((kind, content)))
    monkeypatch.setattr(session, "_submit_db_write", lambda *args, **kwargs: None)
    message = violation_message("long_sleep")
    session._handle_event(AgentEvent(
        "policy_violation", message,
        metadata={"tool_use_id": "tool-1", "tool_name": "Bash", "rule": "long_sleep"},
    ))
    session._handle_event(AgentEvent(
        "tool_result", violation_message("long_sleep"),
        metadata={"tool_use_id": "tool-1", "tool_name": "Bash", "is_error": True},
    ))
    records = [content for kind, content in rows if kind == "policy_violation"]
    assert len(records) == 1
    record = records[0]
    assert json.loads(record)["rule"] == "long_sleep"
    assert any(kind == "tool_result" for kind, _ in rows)


@pytest.mark.asyncio
async def test_session_counts_provider_prefixed_hook_refusal(monkeypatch):
    session = AgentSession(id="id-prefix", name="worker-prefix", scope="scope", cwd="/tmp")
    rows = []
    monkeypatch.setattr(session, "_log", lambda kind, content, **kwargs: rows.append((kind, content)))
    monkeypatch.setattr(session, "_submit_db_write", lambda *args, **kwargs: None)
    session._handle_event(AgentEvent(
        "tool_result", f"PreToolUse:Bash hook error: {violation_message('long_sleep')}",
        metadata={"tool_use_id": "tool-prefix", "tool_name": "Bash", "is_error": True},
    ))
    records = [content for kind, content in rows if kind == "policy_violation"]
    assert len(records) == 1
    assert json.loads(records[0])["rule"] == "long_sleep"
