"""Full-content hub inputs, using local SSH commands and mock MCP only."""

import asyncio
import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import backend_hub as hub, hub_workspace as hw
from app.multicode_client import MultiCodeClient, MultiCodeError
from tests.test_hub_workspace import (
    FakeSsh, _backend, _failed_hub_runs, _offline_hub_pool, _turn, repo,
)


class LocalSsh(FakeSsh):
    def _argv(self, remote):
        return ["/bin/bash", "-c", remote]

    async def run(self, remote, **kwargs):
        return await hw.HubSsh.run(self, remote, **kwargs)


@pytest.fixture
def transport(tmp_path, monkeypatch):
    ws_id = hw.WorkspaceState.new_id()
    remote = tmp_path / ws_id
    remote.mkdir()
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "states")
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [v for v in extra or [] if v])
    backend = hub.HubBackend("hub-gpt-6.1-sol", str(tmp_path))
    backend._ssh = LocalSsh(remote)
    state = hw.WorkspaceState(ws_id, str(tmp_path), str(remote),
                              project_id="project", thread_id="old-thread")
    state.save()
    mc = SimpleNamespace(tool_call=AsyncMock(return_value={"threadId": "new-thread", "runId": "run"}))
    return backend, state, mc


def content(state, wire):
    if not wire.startswith("Read ./"):
        return wire
    rel = wire.split()[1][2:]
    path = Path(state.remote_dir) / rel
    data = path.read_bytes()
    assert path.name == hashlib.sha256(data).hexdigest() + ".txt"
    assert path.stat().st_mode & 0o777 == 0o600
    return data.decode("utf-8")


def units(text):
    return len(text.encode("utf-16-le")) // 2


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["first", "resume", "fallback"])
async def test_native_attachment_survives_full_composition(transport, monkeypatch, tmp_path, route):
    from app import mcp_stdio as m

    backend, state, mc = transport
    attachment = "# Synthetic public docs\nКириллица 😀\r\n" + "x" * 53_659
    attachment += "x" * (53_710 - len(attachment.encode("utf-8")))
    assert len(attachment.encode("utf-8")) == 53_710 < m.MESSAGE_FILE_MAX_BYTES
    report = tmp_path / "publicdocs.md"
    report.write_bytes(attachment.encode("utf-8"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "WORKER_NAME", "synthetic-parent")
    api = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(m, "_api", api)
    await m.send_message("synthetic-worker", "Read the complete attachment.",
                         file_path="publicdocs.md",
                         delivery_id="5bd4f4a6-4925-4192-9711-ff2eff94bc2c")
    accepted = api.await_args.kwargs["json"]["message"]
    assert accepted.endswith(attachment)
    # Session.send injects refreshed rules/context ahead of the durable message;
    # HubBackend adds preamble (first/fallback) and pending steers afterwards.
    system = "<system>\n" + "S" * 42_000 + "\n</system>"
    context = "<context>\n" + "C" * 30_000 + "\n</context>"
    outbound = system + "\n\n" + context + "\n\n" + accepted
    backend._early_steer = ["Apply all acceptance checks.\n" + "U" * 1_000]
    state.thread_id = "" if route == "first" else "old-thread"
    prompt = backend._prompt(outbound, first=route == "first")
    preamble = backend._preamble()
    calls = []

    async def call(name, args):
        calls.append((name, args))
        assert units(args["message"]) <= 120_000
        expected = preamble + prompt if route == "fallback" and name == "t3_thread_launch" else prompt
        assert content(state, args["message"]) == expected
        if route == "fallback" and name == "t3_thread_send":
            raise MultiCodeError("thread is archived")
        return {"threadId": "new-thread", "runId": "run"}

    mc.tool_call = call
    assert await backend._start(mc, state, prompt) == "run"
    assert units(prompt) > 120_000
    assert [name for name, _ in calls] == {
        "first": ["t3_thread_launch"], "resume": ["t3_thread_send"],
        "fallback": ["t3_thread_send", "t3_thread_launch"],
    }[route]
    assert state.thread_id == ("old-thread" if route == "resume" else "new-thread")


@pytest.mark.asyncio
@pytest.mark.parametrize("text,spilled", [
    ("a" * 119_999, False), ("a" * 120_000, False), ("a" * 120_001, True),
    ("я" * 120_000, False), ("я" * 120_001, True),
    ("😀" * 60_000, False), ("😀" * 60_000 + "a", True),
], ids=["ascii-below", "ascii-exact", "ascii-over", "cyrillic-exact", "cyrillic-over",
        "astral-exact", "astral-over"])
async def test_wire_boundary_uses_utf16_not_utf8_bytes_or_codepoints(transport, text, spilled):
    backend, state, mc = transport
    wire = await backend._wire_message(mc, state, text)
    assert (wire != text) is spilled
    assert units(wire) <= 120_000
    assert content(state, wire) == text


@pytest.mark.asyncio
async def test_fallback_checks_added_preamble_and_keeps_old_thread_on_launch_failure(transport, monkeypatch):
    backend, state, mc = transport
    monkeypatch.setattr(backend, "_preamble", lambda: "P" * 5)
    calls = []

    async def call(name, args):
        calls.append((name, args))
        if name == "t3_thread_send":
            assert args["message"] == "x" * 120_000
            raise MultiCodeError("thread cannot accept messages")
        assert content(state, args["message"]) == "P" * 5 + "x" * 120_000
        raise MultiCodeError("launch rejected", invalid_params=True)

    mc.tool_call = call
    with pytest.raises(MultiCodeError, match="launch rejected"):
        await backend._start(mc, state, "x" * 120_000)
    assert len(calls) == 2
    assert state.thread_id == hw.WorkspaceState.load(state.ws_id).thread_id == "old-thread"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["send", "configure", "retarget", "steer"])
@pytest.mark.parametrize("failure", ["rpc", "tool", "http", "uncertain"])
async def test_invalid_parameters_or_uncertain_send_never_replace_thread(
        transport, monkeypatch, operation, failure):
    backend, state, _ = transport
    backend._state = state
    backend._run_id = "active-run"
    backend._turn_active = operation == "steer"
    backend._effort = "high" if operation == "configure" else None
    monkeypatch.setattr(backend, "_model_selection", AsyncMock(return_value={"model": "test"}))
    calls = []

    async def handler(request):
        body = json.loads(request.content)
        calls.append(body["params"]["name"])
        if failure == "uncertain":
            raise httpx.ReadError("uncertain", request=request)
        if failure == "http":
            return httpx.Response(422, text="Expected value length at most 120000 at message; not found")
        if failure == "rpc":
            return httpx.Response(200, json={"id": body["id"], "error": {
                "code": -32602, "message": "Expected value length at most 120000 at message; not found"}})
        return httpx.Response(200, json={"id": body["id"], "result": {
            "isError": True, "content": [{"type": "text", "text": '{"code":"invalid_params"}'}]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        mc = MultiCodeClient("http://mock", "test-token", client=http)
        mc._initialized = True
        monkeypatch.setattr(backend, "_client", AsyncMock(return_value=mc))
        with pytest.raises(MultiCodeError) as error:
            if operation == "retarget":
                await backend.retarget_model("hub-gpt-6-luna")
            elif operation == "steer":
                await backend.send("steer")
            else:
                await backend._start(mc, state, "task")
    assert error.value.retryable if failure == "uncertain" else error.value.invalid_params
    assert not hub._workspace_lost(error.value)
    assert state.thread_id == hw.WorkspaceState.load(state.ws_id).thread_id == "old-thread"
    assert backend.model == "hub-gpt-6.1-sol"
    assert backend._early_steer == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_large_live_steer_delivered_once(transport, monkeypatch):
    backend, state, mc = transport
    backend._state, backend._run_id, backend._turn_active = state, "active-run", True
    monkeypatch.setattr(backend, "_client", AsyncMock(return_value=mc))
    steer = "😀" * 60_001
    await backend.send(steer)
    mc.tool_call.assert_awaited_once()
    name, args = mc.tool_call.await_args.args
    assert name == "t3_thread_send" and args["mode"] == "steer"
    assert content(state, args["message"]) == steer
    assert backend._early_steer == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["upload", "send", "cancel"])
async def test_large_failure_preserves_input_and_thread_without_replay(transport, monkeypatch, failure):
    backend, state, mc = transport
    prompt = "original\n" + "я" * 120_000 + "\nend"
    if failure == "upload":
        monkeypatch.setattr(LocalSsh, "put_prompt", AsyncMock(side_effect=hw.HubWorkspaceError("upload failed")))
        expected = hw.HubWorkspaceError
    else:
        expected = asyncio.CancelledError if failure == "cancel" else MultiCodeError
        mc.tool_call.side_effect = expected() if failure == "cancel" else MultiCodeError("uncertain", retryable=True)
    with pytest.raises(expected):
        await backend._start(mc, state, prompt)
    assert state.thread_id == hw.WorkspaceState.load(state.ws_id).thread_id == "old-thread"
    assert mc.tool_call.await_count == (0 if failure == "upload" else 1)
    if failure != "upload":
        wire = mc.tool_call.await_args.args[1]["message"]
        assert content(state, wire) == prompt  # keep it for an ambiguously accepted run


@pytest.mark.asyncio
async def test_atomic_upload_checksum_symlinks_and_concurrent_inputs(transport, tmp_path):
    backend, state, _ = transport
    ssh = backend._ssh
    scratch_a, scratch_b = tmp_path / "a", tmp_path / "b"
    scratch_a.mkdir()
    scratch_b.mkdir()
    data_a, data_b = b"a" * 120_001, b"b" * 120_001
    rels = await asyncio.gather(ssh.put_prompt(state.remote_dir, data_a, scratch_a),
                               ssh.put_prompt(state.remote_dir, data_b, scratch_b))
    assert [(Path(state.remote_dir) / rel).read_bytes() for rel in rels] == [data_a, data_b]
    assert not list((Path(state.remote_dir) / hw.PROMPT_DIR).glob(".upload-*"))
    outside = tmp_path / "outside"
    outside.write_bytes(b"untouched")
    target = Path(state.remote_dir) / rels[0]
    target.unlink()
    target.symlink_to(outside)
    await ssh.put_prompt(state.remote_dir, data_a, scratch_a)
    assert not target.is_symlink() and outside.read_bytes() == b"untouched"
    remote2 = tmp_path / hw.WorkspaceState.new_id()
    remote2.mkdir()
    (remote2 / hw.PROMPT_DIR).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(hw.HubWorkspaceError):
        await ssh.put_prompt(str(remote2), data_a, scratch_a)


@pytest.mark.asyncio
async def test_corrupt_transfer_does_not_publish_or_submit(transport, monkeypatch):
    backend, state, mc = transport
    original = LocalSsh.run

    async def corrupt(self, remote, **kwargs):
        kwargs["stdin"].write_bytes(b"corrupt")
        return await original(self, remote, **kwargs)

    monkeypatch.setattr(LocalSsh, "run", corrupt)
    with pytest.raises(hw.HubWorkspaceError, match="checksum"):
        await backend._start(mc, state, "a" * 120_001)
    mc.tool_call.assert_not_awaited()
    assert list((Path(state.remote_dir) / hw.PROMPT_DIR).iterdir()) == []


@pytest.mark.asyncio
async def test_spilled_prompt_guards_stay_before_transfer(transport, monkeypatch):
    backend, state, mc = transport
    secret = "synthetic-sensitive-value"
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [secret])
    upload = AsyncMock()
    monkeypatch.setattr(LocalSsh, "put_prompt", upload)
    with pytest.raises(hw.HubWorkspaceError, match="credential"):
        await backend._start(mc, state, "x" * 120_001 + secret)
    upload.assert_not_awaited()
    mc.tool_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_spilled_history_is_masked_without_losing_other_content(transport, monkeypatch):
    backend, state, mc = transport
    secret = "synthetic-sensitive-value"
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [secret])
    history = "<prior-conversation>\nold " + secret + "\n</prior-conversation>\n"
    prompt = history + "x" * 120_001 + "\ncurrent task"
    wire = await backend._wire_message(mc, state, prompt)
    assert content(state, wire) == prompt.replace(secret, "[redacted]")


@pytest.mark.asyncio
async def test_existing_file_size_bound_refuses_before_send(transport, monkeypatch):
    backend, state, mc = transport
    monkeypatch.setattr(hw, "MAX_FILE_BYTES", 120_000)
    with pytest.raises(hw.HubWorkspaceError, match="workspace file limit"):
        await backend._start(mc, state, "x" * 120_001)
    mc.tool_call.assert_not_awaited()
    assert state.thread_id == "old-thread"
    assert not (Path(state.remote_dir) / hw.PROMPT_DIR).exists()


@pytest.mark.asyncio
async def test_fallback_does_not_duplicate_existing_preamble(transport, monkeypatch):
    backend, state, mc = transport
    monkeypatch.setattr(backend, "_preamble", lambda: "preamble\n")
    prompt = "preamble\n" + "x" * 120_001

    async def call(name, args):
        assert content(state, args["message"]) == prompt
        if name == "t3_thread_send":
            raise MultiCodeError("thread is archived")
        return {"threadId": "new-thread", "runId": "new-run"}

    mc.tool_call.side_effect = call
    assert await backend._start(mc, state, prompt) == "new-run"
    assert mc.tool_call.await_count == 2


@pytest.mark.asyncio
async def test_launch_without_run_id_keeps_created_thread_for_reconciliation(transport):
    backend, state, mc = transport
    state.thread_id = ""
    mc.tool_call.return_value = {"threadId": "created-thread"}
    with pytest.raises(MultiCodeError, match="no runId"):
        await backend._start(mc, state, "x" * 120_001)
    assert state.thread_id == hw.WorkspaceState.load(state.ws_id).thread_id == "created-thread"
    mc.tool_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_transport_files_never_import_or_upload_as_source(transport, tmp_path):
    backend, state, mc = transport
    wire = await backend._wire_message(mc, state, "a" * 120_001)
    plan = hw.plan_upload(Path(state.remote_dir), known=[])
    assert not any(hw.PROMPT_DIR in rel for rel in plan.manifest)
    archive = tmp_path / "snapshot.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(state.remote_dir, arcname=".")
        payload = b"useful output"
        info = tarfile.TarInfo("result.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    root = tmp_path / "result"
    root.mkdir()
    result = hw.apply_changes(archive, root, {}, known=[])
    assert (root / "result.txt").read_bytes() == b"useful output"
    assert not (root / hw.PROMPT_DIR).exists()
    assert not any(hw.PROMPT_DIR in rel for rel in result.manifest)
    assert content(state, wire) == "a" * 120_001


@pytest.mark.asyncio
async def test_large_no_work_retry_uses_same_file_and_thread(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    await backend.connect()
    backend._ssh = LocalSsh(ssh.base)
    attempts, sleep = _failed_hub_runs(mc, monkeypatch)
    events = await _turn(backend, "x" * 120_001)
    assert events[-1].metadata["ok"] is True
    assert [name for name, _ in attempts] == ["t3_thread_launch", "t3_thread_send"]
    assert attempts[0][1]["message"] == attempts[1][1]["message"]
    assert attempts[1][1]["threadId"] == backend._state.thread_id == "thr-1"
    assert content(backend._state, attempts[1][1]["message"]).endswith("x" * 120_001)
    sleep.assert_awaited_once_with(1)
    assert not (repo / hw.PROMPT_DIR).exists()


@pytest.mark.asyncio
async def test_early_steers_survive_start_failure_and_new_arrival(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    await backend.connect()
    backend._ssh = LocalSsh(ssh.base)
    backend._early_steer = ["early\n" + "u" * 120_001]
    original = mc.tool_call

    async def fail_start(name, args):
        if name == "t3_thread_launch":
            backend._early_steer.append("arrived during start")
            raise MultiCodeError("invalid parameters", invalid_params=True)
        return await original(name, args)

    mc.tool_call = fail_start
    events = await _turn(backend, "original task")
    assert events[-1].metadata["ok"] is False
    assert backend._early_steer == ["early\n" + "u" * 120_001, "arrived during start"]
    seen = []

    async def succeed_start(name, args):
        if name == "t3_thread_launch":
            seen.append(content(backend._state, args["message"]))
            backend._early_steer.append("arrived during accepted start")
        return await original(name, args)

    mc.tool_call = succeed_start
    events = await _turn(backend, "original task")
    assert events[-1].metadata["ok"] is True
    assert seen[0].count("early\n") == 1 and seen[0].count("arrived during start") == 1
    assert backend._early_steer == ["arrived during accepted start"]
