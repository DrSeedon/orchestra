"""Offline behavior and protocol checks for V-1059. No live hub/provider calls."""

import asyncio
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app import hub_image as hi
from app import hub_workspace as hw
from app.multicode_client import MultiCodeError

SESSION = "12345678-1234-1234-1234-123456789abc"
ROOT = "/home/test/.codex/generated_images"
RECORD = {"codex_thread_id": SESSION, "generated_root": ROOT}


def png():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(out, format="PNG")
    return out.getvalue()


def archive(path, members):
    with tarfile.open(path, "w") as bundle:
        for name, data, kind in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            member.linkname = "outside.png" if kind != tarfile.REGTYPE else ""
            bundle.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)


def test_discover_orders_images_and_never_extracts_paths(tmp_path):
    path = tmp_path / "images.tar"
    archive(path, [("./image-2.png", png(), tarfile.REGTYPE),
                   ("../../outside", b"evil", tarfile.REGTYPE),
                   ("./image-1.png", png(), tarfile.REGTYPE)])
    assert hi.discover_images(path, 2) == [png(), png()]
    assert not (tmp_path / "image-1.png").exists()


@pytest.mark.parametrize("members,code", [
    ([], "no_image"),
    ([("image-1.png", b"not an image", tarfile.REGTYPE)], "invalid_output"),
    ([("image-1.png", b"", tarfile.SYMTYPE)], "invalid_output"),
    ([("image-1.png", b"", tarfile.LNKTYPE)], "invalid_output"),
    ([("image-1.png", png(), tarfile.REGTYPE)] * 2, "invalid_output"),
])
def test_discovery_rejects_invalid_outputs(tmp_path, members, code):
    path = tmp_path / "images.tar"
    archive(path, members)
    with pytest.raises(hi.ImageError) as exc:
        hi.discover_images(path, 1)
    assert exc.value.code == code


def test_discovery_rejects_oversized_image(tmp_path, monkeypatch):
    path = tmp_path / "images.tar"
    archive(path, [("image-1.png", png(), tarfile.REGTYPE)])
    monkeypatch.setattr(hi, "MAX_IMAGE_BYTES", 1)
    with pytest.raises(hi.ImageError, match="oversized"):
        hi.discover_images(path, 1)


@pytest.mark.parametrize("record", [None, {},
    {**RECORD, "codex_thread_id": "../../other"},
    {**RECORD, "generated_root": "/home/test/.ssh"},
    {**RECORD, "generated_root": ROOT + "/../other"},
])
def test_generated_directory_is_confined(record):
    with pytest.raises(hi.ImageError):
        hi.generated_directory(record, ROOT)


def test_generated_directory_uses_native_session_not_hub_thread():
    assert hi.generated_directory(RECORD, ROOT) == ROOT + "/" + SESSION


class FakeSsh:
    def __init__(self, *, images=1):
        self.commands = []
        self.images = images

    async def dir_for(self, ws_id):
        return "/home/test/orchestra-ws/test/" + ws_id

    async def run(self, command, **kwargs):
        self.commands.append(command)
        if command.startswith("readlink"):
            return (ROOT + "\n").encode()
        if command.startswith("if test -f"):
            return json.dumps(RECORD).encode()
        if command.startswith("tar "):
            archive(kwargs["stdout"], [(f"./image-{i}.png", png(), tarfile.REGTYPE)
                                       for i in range(1, self.images + 1)])
        return b""


class FakeClient:
    def __init__(self, *, status="completed"):
        self.calls = []
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def tool_call(self, name, args):
        self.calls.append((name, args))
        if name == "t3_project_create":
            return {"id": "project-test"}
        if name == "t3_thread_launch":
            return {"threadId": "thread-test"}
        if name == "t3_thread_send":
            return {"runId": "run-test"}
        if name == "t3_thread_wait":
            return {"status": self.status, "timedOut": self.status == "running"}
        if name == "t3_thread_read":
            return {"items": [], "recentRuns": [{"runId": "run-test", "status": self.status}]}
        return {}


@pytest.fixture
def hub(tmp_path, monkeypatch):
    ssh = FakeSsh()
    mc = FakeClient()
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(hi, "RECOVERY_DIR", tmp_path / "recovery")
    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda cls: ssh))
    monkeypatch.setattr(hi.MultiCodeClient, "from_env", classmethod(lambda cls: mc))

    async def released(state, transport, client):
        await client.tool_call("t3_project_delete", {"projectId": state.project_id, "force": True})
        state.path().unlink(missing_ok=True)

    release = AsyncMock(side_effect=released)
    monkeypatch.setattr(hw, "release_workspace", release)
    return ssh, mc, release


@pytest.mark.asyncio
async def test_generation_fetches_and_cleans_up(tmp_path, hub):
    ssh, mc, release = hub
    ssh.images = 2
    progress = []
    result = await hi.generate_image("a blue bird", count=2, size="16:9",
                                     output_dir=str(tmp_path / "output"), progress=progress.append)
    assert result["ok"], result
    assert [Path(p).read_bytes() for p in result["paths"]] == [png(), png()]
    launch = next(args for name, args in mc.calls if name == "t3_thread_launch")
    assert launch["modelSelection"] == {"instanceId": "codex", "model": "gpt-6.1-sol"}
    assert "message" not in launch  # no producer before its thread ID is saved
    send = next(args for name, args in mc.calls if name == "t3_thread_send")
    assert "image_gen__imagegen" in send["message"] and "16:9" in send["message"]
    assert send["message"].index(hi.SESSION_FILE) < send["message"].index("Call image_gen__imagegen")
    assert release.await_count == 1
    assert any("rm -rf" in command and ROOT + "/" + SESSION in command for command in ssh.commands)
    assert not list(hw.STATE_DIR.glob("*.json"))
    assert not list(hi.RECOVERY_DIR.glob("*.json"))
    assert any("thread created" in message for message in progress)
    assert any("fetched path" in message for message in progress)
    assert progress[-1].startswith("cleanup complete")


@pytest.mark.asyncio
async def test_no_image_still_cleans_up(tmp_path, hub):
    ssh, mc, release = hub
    ssh.images = 0
    result = await hi.generate_image("bird", output_dir=str(tmp_path))
    assert result["error"]["code"] == "no_image"
    assert release.await_count == 1


@pytest.mark.asyncio
async def test_provider_limit_still_cleans_up(tmp_path, hub):
    ssh, mc, release = hub
    mc.status = "usage_limit"
    # The cleanup wait observes the interrupted producer as terminal.
    original = mc.tool_call

    async def call(name, args):
        if name == "t3_thread_interrupt":
            mc.status = "interrupted"
        return await original(name, args)

    mc.tool_call = call
    result = await hi.generate_image("bird", output_dir=str(tmp_path))
    assert result["error"]["code"] == "provider_limit"
    assert release.await_count == 1


@pytest.mark.asyncio
async def test_wall_clock_timeout_cleans_up(tmp_path, hub, monkeypatch):
    ssh, mc, release = hub
    monkeypatch.setattr(hi, "validate_request", lambda *args: None)
    original = mc.tool_call

    async def call(name, args):
        if name == "t3_thread_wait" and "runId" in args:
            await asyncio.Event().wait()
        return await original(name, args)

    mc.tool_call = call
    result = await hi.generate_image("bird", timeout_seconds=0.05, output_dir=str(tmp_path))
    assert result["error"]["code"] == "timeout"
    assert release.await_count == 1


@pytest.mark.asyncio
async def test_hub_down_and_lost_send_response_are_bounded(tmp_path, hub):
    ssh, mc, release = hub
    original = mc.tool_call
    sends = 0

    async def call(name, args):
        nonlocal sends
        if name == "t3_thread_send":
            sends += 1
            raise MultiCodeError("transport disconnected private-host")
        return await original(name, args)

    mc.tool_call = call
    result = await hi.generate_image("bird", output_dir=str(tmp_path))
    assert result["error"]["code"] == "hub_unavailable"
    assert "private-host" not in json.dumps(result)
    assert release.await_count == 1
    assert sends == 1  # failing send is not replayed


@pytest.mark.asyncio
async def test_cleanup_failure_preserves_paths_and_can_retry(tmp_path, hub):
    ssh, mc, release = hub
    release.side_effect = hw.HubWorkspaceError("offline")
    result = await hi.generate_image("bird", output_dir=str(tmp_path / "out"))
    assert not result["ok"] and result["error"]["code"] == "cleanup_failed"
    assert Path(result["paths"][0]).exists()
    state_path, = hw.STATE_DIR.glob("*.json")
    assert list(hi.RECOVERY_DIR.glob("*.json"))
    release.side_effect = None
    result = await hi.retry_cleanup(state_path.stem)
    assert result["ok"]
    assert not list(hi.RECOVERY_DIR.glob("*.json"))


@pytest.mark.asyncio
async def test_running_producer_prevents_file_deletion(tmp_path, hub):
    ssh, mc, release = hub
    state = hw.WorkspaceState("hub-0123456789abcdef", "", "/home/test/orchestra-ws/test/hub-0123456789abcdef",
                              project_id="project-test", thread_id="thread-test")
    mc.status = "running"
    with pytest.raises(hi.ImageError, match="not stopped"):
        await hi.cleanup(mc, ssh, state, lambda m: None)
    assert not any("rm -rf" in command for command in ssh.commands)
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_retry_handles_already_deleted_thread(tmp_path, hub):
    ssh, mc, release = hub
    state = hw.WorkspaceState("hub-0123456789abcdef", "", "/home/test/orchestra-ws/test/hub-0123456789abcdef",
                              project_id="project-test", thread_id="thread-test")
    original = mc.tool_call

    async def call(name, args):
        if name == "t3_thread_interrupt":
            raise MultiCodeError("not_found")
        return await original(name, args)

    mc.tool_call = call
    await hi.cleanup(mc, ssh, state, lambda m: None)
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_ambiguous_project_create_is_recovered_for_cleanup(tmp_path, hub):
    ssh, mc, release = hub
    original = mc.tool_call
    remote = None

    async def call(name, args):
        nonlocal remote
        if name == "t3_project_create":
            remote = args["workspaceRoot"]
            raise MultiCodeError("response lost")
        if name == "t3_project_list":
            return {"projects": [{"id": "project-created", "workspaceRoot": remote}], "nextCursor": None}
        return await original(name, args)

    mc.tool_call = call
    result = await hi.generate_image("bird", output_dir=str(tmp_path))
    assert result["error"]["code"] == "hub_unavailable"
    assert "cleanup_error" not in result
    assert release.call_args.args[0].project_id == "project-created"


@pytest.mark.asyncio
async def test_cleanup_has_separate_deadline(tmp_path, hub, monkeypatch):
    ssh, mc, release = hub
    monkeypatch.setattr(hi, "CLEANUP_SECONDS", 0.01)

    async def never_returns(*args):
        await asyncio.Event().wait()

    release.side_effect = never_returns
    result = await hi.generate_image("bird", output_dir=str(tmp_path))
    assert not result["ok"] and result["error"]["code"] == "cleanup_failed"
    assert list(hw.STATE_DIR.glob("*.json"))


@pytest.mark.asyncio
async def test_failed_run_classifies_provider_error_without_exposing_details(tmp_path, hub):
    ssh, mc, release = hub
    mc.status = "failed"
    original = mc.tool_call

    async def call(name, args):
        if name == "t3_thread_read":
            return {"items": [], "recentRuns": [{"id": "run-test", "status": "failed",
                    "error": "429 rate limit for private-account"}]}
        return await original(name, args)

    mc.tool_call = call
    result = await hi.generate_image("bird", output_dir=str(tmp_path))
    assert result["error"]["code"] == "provider_limit"
    assert "private-account" not in json.dumps(result)
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_provider_limit_is_classified(tmp_path, hub):
    ssh, mc, release = hub
    original = mc.tool_call

    async def call(name, args):
        if name == "t3_thread_send":
            raise MultiCodeError("usage_limit: private-account")
        return await original(name, args)

    mc.tool_call = call
    result = await hi.generate_image("bird", output_dir=str(tmp_path))
    assert result["error"]["code"] == "provider_limit"
    assert "private-account" not in json.dumps(result)
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_unconfigured_mcp_needs_no_live_credentials(monkeypatch):
    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda cls: None))
    result = await hi.generate_image("bird")
    assert result["error"]["code"] == "not_configured"


@pytest.mark.asyncio
async def test_image_cleanup_does_not_accept_an_ordinary_worker(tmp_path, hub):
    state = hw.WorkspaceState("hub-0123456789abcdef", "worker", "/home/test/orchestra-ws/test/hub-0123456789abcdef")
    state.save()
    result = await hi.retry_cleanup(state.ws_id)
    assert result["error"]["code"] == "invalid_request"
    assert state.path().exists()
    assert not hub[1].calls


@pytest.mark.asyncio
async def test_corrupted_cleanup_record_returns_error(tmp_path, hub):
    state = hw.WorkspaceState("hub-0123456789abcdef", "", "/home/test/orchestra-ws/test/hub-0123456789abcdef")
    state.save()
    hi.RECOVERY_DIR.mkdir()
    hi._recovery_path(state).write_text("[]")
    result = await hi.retry_cleanup(state.ws_id)
    assert result["error"]["code"] == "invalid_output"
    assert not hub[1].calls


@pytest.mark.parametrize("kwargs", [{"count": 0}, {"count": 5}, {"count": True},
    {"size": "1024; rm"}, {"timeout_seconds": 0}, {"timeout_seconds": 1801}, {"prompt": ""}])
@pytest.mark.asyncio
async def test_invalid_requests_never_contact_hub(kwargs, hub):
    ssh, mc, release = hub
    result = await hi.generate_image(**{"prompt": "bird", **kwargs})
    assert result["error"]["code"] == "invalid_request"
    assert not mc.calls and not ssh.commands


@pytest.mark.asyncio
async def test_ssh_cancellation_reaps_child(tmp_path, monkeypatch):
    ready = asyncio.Event()
    process = type("Process", (), {})()
    process.returncode = None
    process.kill = lambda: setattr(process, "returncode", -9)
    process.wait = AsyncMock(return_value=-9)

    async def communicate():
        ready.set()
        await asyncio.Event().wait()

    process.communicate = communicate
    monkeypatch.setattr(hw.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(hw.HubSsh("test", "key", "").run("true"))
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode == -9
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_mcp_schema_and_error_flag(monkeypatch):
    from app import hub_image_mcp as server
    from mcp.types import CallToolRequest, CallToolRequestParams

    tools = await server.mcp.list_tools()
    assert [tool.name for tool in tools] == ["hub_generate_image"]
    schema = tools[0].inputSchema
    assert schema["required"] == ["prompt"]
    assert schema["properties"]["count"]["maximum"] == 4
    assert schema["properties"]["timeout_seconds"]["maximum"] == 1800
    monkeypatch.setattr(server, "generate_image", AsyncMock(return_value={
        "ok": False, "paths": [], "error": {"code": "provider_limit", "message": "usage limit"}}))
    handler = server.mcp._mcp_server.request_handlers[CallToolRequest]
    wrapped = await handler(CallToolRequest(params=CallToolRequestParams(
        name="hub_generate_image", arguments={"prompt": "bird"})))
    assert wrapped.root.isError
    assert json.loads(wrapped.root.content[0].text)["error"]["code"] == "provider_limit"


@pytest.mark.asyncio
async def test_stdio_tools_list_real_process(tmp_path):
    """A real stdio handshake must list the tool without any hub credentials/network."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {key: value for key, value in os.environ.items() if not key.startswith("MULTICODE_")}
    async with asyncio.timeout(15):
        async with stdio_client(StdioServerParameters(
                command=sys.executable, args=["-m", "app.hub_image_mcp"], env=env)) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                listed = await session.list_tools()
    assert [tool.name for tool in listed.tools] == ["hub_generate_image"]


def test_cli_reports_configuration_error_as_json(tmp_path):
    import subprocess

    env = {key: value for key, value in os.environ.items() if not key.startswith("MULTICODE_")}
    result = subprocess.run([sys.executable, "-m", "app.hub_image", "blue bird"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "not_configured"
    assert "Traceback" not in result.stderr
