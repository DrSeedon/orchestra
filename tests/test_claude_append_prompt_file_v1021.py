"""V-1021: the appended system prompt goes through a file, never as one argv value.

The SDK turns preset ``append`` into a single ``--append-system-prompt <text>`` argument and
Linux rejects any single argument over MAX_ARG_STRLEN (131072 bytes) with ``[Errno 7]``.
"""

import stat
from pathlib import Path

import pytest

from app.backend_claude import ClaudeBackend
from app.runtime_history import HISTORICAL_TOOL_INSTRUCTION, render_claude_history

MAX_ARG_STRLEN = 131072
FLAG = "--append-system-prompt-file"


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))


def _backend(prompt: str, **kw) -> ClaudeBackend:
    return ClaudeBackend(
        model="claude-sonnet-5-5[1m]", cwd=str(Path.home() / "worktree"),
        system_prompt=prompt, **kw,
    )


def _command(backend: ClaudeBackend) -> list[str]:
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    options = backend._make_client().options
    transport = SubprocessCLITransport(prompt="", options=options)
    transport._cli_path = "claude"
    return transport._build_command()


def _file_arg(cmd: list[str]) -> Path:
    assert cmd.count(FLAG) == 1, cmd[:40]
    return Path(cmd[cmd.index(FLAG) + 1])


# Cyrillic: 2 bytes per character, as in the incident (~70K chars > 131072 bytes).
BIG = "Контекст оркестратора. " * 6000


def test_prompt_over_the_argv_limit_gives_short_args_and_exact_file():
    assert len(BIG.encode("utf-8")) > MAX_ARG_STRLEN
    backend = _backend(BIG)
    cmd = _command(backend)

    assert max(len(a.encode("utf-8")) for a in cmd) < MAX_ARG_STRLEN
    assert "--append-system-prompt" not in cmd
    assert _file_arg(cmd).read_text(encoding="utf-8") == BIG


def test_small_prompt_also_goes_through_the_file_only():
    cmd = _command(_backend("tiny prompt"))

    assert "--append-system-prompt" not in cmd
    assert "tiny prompt" not in cmd
    assert _file_arg(cmd).read_text(encoding="utf-8") == "tiny prompt"


def test_history_import_branch_uses_the_file_with_historical_instruction():
    history = render_claude_history(
        [{"id": 1, "ts": "2026-08-11T10:00:00+00:00", "type": "user_message", "content": "x"}],
        snapshot_id=1, session_id="11111111-2222-4333-8444-555555555555",
        cwd="/tmp", model="claude-sonnet-5-5[1m]",
    )
    backend = _backend(BIG, resume_session_id=history.session_id, history_import=history)
    cmd = _command(backend)

    assert max(len(a.encode("utf-8")) for a in cmd) < MAX_ARG_STRLEN
    assert _file_arg(cmd).read_text(encoding="utf-8") == f"{BIG}\n\n{HISTORICAL_TOOL_INSTRUCTION}"


def test_file_is_private_outside_cwd_and_rewritten_on_every_connect():
    backend = _backend("first")
    path = _file_arg(_command(backend))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not path.is_relative_to(Path.home() / "worktree")

    backend.system_prompt = "second, different"
    again = _file_arg(_command(backend))
    assert again == path
    assert path.read_text(encoding="utf-8") == "second, different"


def test_file_is_removed_on_disconnect():
    import asyncio

    backend = _backend("gone soon")
    path = _file_arg(_command(backend))
    assert path.exists()

    asyncio.run(backend.disconnect())

    assert not path.exists()


def test_telemetry_hashes_the_text_not_the_file():
    import hashlib

    backend = _backend(BIG)
    _command(backend)
    caps = backend.handoff_expected_capabilities()

    assert caps["system_prompt_sha256"] == hashlib.sha256(BIG.encode("utf-8")).hexdigest()
