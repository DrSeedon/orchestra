"""Resumed Claude CLIs get the role through the system channel, not a second user-turn copy.

Claude CLI does not keep `--append-system-prompt-file` in its transcript, so the platform
used to replay the whole ~77 KB prompt into the user history after every resume and on
every temporary-rule edit. Now the file is passed on resume too; the user turn carries
the prompt only when the live CLI did not get exactly this text at connect, and a
rules-only change carries only the `<temporary-rules>` block.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.events import MessageProvenance

ROLE = "STATIC ROLE TEXT " * 200
OWNER = MessageProvenance(origin="user", senders=("user",))


class _FakeBackend:
    def __init__(self):
        self.send = AsyncMock()


def _session(tmp_path, monkeypatch, *, prompt_injected, template_hash="same-template",
             rules_fp="current-rules", rules_now="current-rules", current_prompt=ROLE):
    from app import session as session_module

    session = session_module.AgentSession(
        id="sc-1110", name="worker", scope=str(tmp_path), cwd=str(tmp_path),
        model="claude-sonnet-5-5[1m]", backend_type="claude", session_id="resumed-session",
        system_prompt="PROMPT FROM STARTUP", _current_prompt=current_prompt,
        _prompt_injected=prompt_injected, _template_hash=template_hash,
        _temp_rules_fp=rules_fp,
    )
    for name in ("_apply_pending_identity_restart", "_apply_manifest_effort",
                 "_notify_scope_running", "_turn_event_loop"):
        monkeypatch.setattr(session, name, AsyncMock())
    for name in ("_persist", "_start_turn_state", "_ack_pending_facts"):
        monkeypatch.setattr(session, name, Mock())
    logged = []
    monkeypatch.setattr(session, "_log", lambda kind, text, **kw: logged.append((kind, text)))
    monkeypatch.setattr(session, "_attach_pending_facts", lambda message: (message, []))
    monkeypatch.setattr(session._turns, "claim_mailbox_held_after_stop", lambda: [])
    monkeypatch.setattr(session._turns, "complete_mailbox_held_after_stop", Mock())
    monkeypatch.setattr(session_module, "session_requires_quota", lambda *a, **kw: False)
    monkeypatch.setattr(session_module, "prompt_template_hash", lambda role: "same-template")
    monkeypatch.setattr(session_module, "refresh_worker_memory", Mock(return_value=ROLE))
    monkeypatch.setattr(session_module.temp_rules, "fingerprint", lambda **kw: rules_now)
    monkeypatch.setattr(session_module.temp_rules, "block_fingerprint", lambda prompt: rules_now)
    return session, session_module, logged


async def _send(session):
    await session.send("Continue the task", provenance=OWNER)
    if session._listen_task:
        await session._listen_task


@pytest.mark.asyncio
async def test_resume_connect_carries_the_prompt_in_the_system_channel_only(tmp_path, monkeypatch):
    session, session_module, logged = _session(tmp_path, monkeypatch, prompt_injected=False)
    monkeypatch.setattr(session_module.temp_rules, "with_block", lambda prompt, **kw: prompt)
    built = []

    def build_backend(runtime, context):
        backend = _FakeBackend()
        built.append((runtime, context.system_prompt, context.resume_session_id))
        return backend

    monkeypatch.setattr(session_module, "build_backend", build_backend)

    async def ensure_backend(**kwargs):
        session._backend = session._make_backend()
        return session._backend

    monkeypatch.setattr(session, "_ensure_backend", ensure_backend)

    await _send(session)

    runtime, system_prompt, resume_id = built[0]
    assert (runtime, resume_id) == ("claude", "resumed-session")
    assert system_prompt == ROLE, "the CLI starts with the rebuilt prompt, not the startup copy"
    session._backend.send.assert_awaited_once_with("Continue the task")
    assert session._prompt_injected is True and session.system_prompt == ROLE
    assert ("status", "prompt delivered via system channel; not replayed") in logged


@pytest.mark.asyncio
async def test_live_cli_with_an_older_prompt_still_gets_the_full_copy(tmp_path, monkeypatch):
    session, session_module, _logged = _session(tmp_path, monkeypatch, prompt_injected=False)
    monkeypatch.setattr(session_module.temp_rules, "with_block", lambda prompt, **kw: prompt)
    backend = _FakeBackend()
    backend._orchestra_system_channel_prompt = "OLDER PROMPT"
    session._backend = backend
    monkeypatch.setattr(session, "_ensure_backend", AsyncMock(return_value=backend))

    await _send(session)

    sent = backend.send.call_args.args[0]
    assert ROLE in sent and sent.endswith("Continue the task")
    assert sent.startswith("[Orchestra platform note: refreshed context")


@pytest.mark.asyncio
async def test_rules_only_change_sends_the_block_not_the_static_prompt(tmp_path, monkeypatch):
    block = "<temporary-rules>\n- NEW RULE: never merge on Friday\n</temporary-rules>"
    session, session_module, _logged = _session(
        tmp_path, monkeypatch, prompt_injected=True,
        rules_fp="old-rules", rules_now="new-rules",
    )
    monkeypatch.setattr(session_module.temp_rules, "with_block",
                        lambda prompt, **kw: f"{prompt}\n\n{block}")
    backend = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(session, "_ensure_backend", AsyncMock(return_value=backend))

    await _send(session)

    sent = backend.send.call_args.args[0]
    assert "STATIC ROLE TEXT" not in sent
    assert block in sent and sent.endswith("Continue the task")
    assert "role instructions were updated" in sent
    assert session._current_prompt.endswith(block), "the full prompt is still kept for reconnects"
    assert session.system_prompt == session._current_prompt


@pytest.mark.asyncio
async def test_role_change_with_rules_change_resends_the_whole_prompt(tmp_path, monkeypatch):
    session, session_module, _logged = _session(
        tmp_path, monkeypatch, prompt_injected=True, template_hash="old-template",
        rules_fp="old-rules", rules_now="new-rules",
    )
    monkeypatch.setattr(session_module.temp_rules, "with_block", lambda prompt, **kw: prompt)
    backend = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(session, "_ensure_backend", AsyncMock(return_value=backend))

    await _send(session)

    sent = backend.send.call_args.args[0]
    assert ROLE in sent and "your role instructions were updated." in sent


@pytest.mark.asyncio
async def test_memory_only_refresh_sends_updated_memory_without_static_role(tmp_path, monkeypatch):
    old = ROLE + "\n\n<worker-memory>\nold memory\n</worker-memory>"
    new = ROLE + "\n\n<worker-memory>\nnew memory\n</worker-memory>"
    session, session_module, _ = _session(tmp_path, monkeypatch, prompt_injected=False,
                                         current_prompt=old)
    monkeypatch.setattr(session_module, "refresh_worker_memory", Mock(return_value=new))
    monkeypatch.setattr(session_module.temp_rules, "with_block", lambda prompt, **kw: prompt)
    backend = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(session, "_ensure_backend", AsyncMock(return_value=backend))
    await _send(session)
    sent = backend.send.call_args.args[0]
    assert "STATIC ROLE TEXT" not in sent and "old memory" not in sent
    assert "<worker-memory>\nnew memory\n</worker-memory>" in sent
    assert session.system_prompt == new and sent.endswith("Continue the task")


@pytest.mark.asyncio
async def test_rule_update_does_not_hide_another_static_prompt_change(tmp_path, monkeypatch):
    session, session_module, _ = _session(tmp_path, monkeypatch, prompt_injected=True,
                                         rules_fp="old", rules_now="new")
    monkeypatch.setattr(session_module, "refresh_worker_memory", Mock(return_value=ROLE + " NEW STATIC"))
    monkeypatch.setattr(session_module.temp_rules, "with_block", lambda prompt, **kw: prompt)
    backend = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(session, "_ensure_backend", AsyncMock(return_value=backend))
    await _send(session)
    assert ROLE + " NEW STATIC" in backend.send.call_args.args[0]
