import asyncio
import base64
import json
import stat

import pytest

from app import acp_mux, db
from app.antigravity_acp import AcpProfile
from app.native_requests import bind_session


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "stand.sqlite")
    return tmp_path


async def message(reader):
    return json.loads(await asyncio.wait_for(reader.readline(), 2))


def send(writer, ident, method, **params):
    writer.write((json.dumps({"id": ident, "method": method, "params": params}) + "\n").encode())


@pytest.mark.asyncio
async def test_mux_is_passive_and_never_attaches_an_orchestra_session(home, monkeypatch):
    owner = AcpProfile(home)
    bind_session(owner, "orchestra-native", "orchestra-owner")
    monkeypatch.setattr(acp_mux, "get_profile", lambda _: owner)
    started = []

    async def start():
        started.append(True)

    monkeypatch.setattr(owner, "start", start)
    mux = acp_mux.AcpMux(home)
    await mux.start()
    try:
        assert stat.S_IMODE(mux.path.stat().st_mode) == 0o600
        reader, writer = await asyncio.open_unix_connection(mux.path)
        for origin, sid in (("inbox", None), ("telegram", "orchestra-native")):
            send(writer, 1, "session/open", origin=origin, sessionId=sid, cwd=str(home),
                 token="a" * 64)
            assert "error" in await message(reader)
        assert not started
        writer.close()
        await writer.wait_closed()
    finally:
        await mux.close()


@pytest.mark.asyncio
async def test_mux_audio_shared_slot_updates_cancel_and_reconnect(home, monkeypatch):
    owner = AcpProfile(home)
    monkeypatch.setattr(acp_mux, "get_profile", lambda _: owner)

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(acp_mux, "_egress", noop)
    monkeypatch.setattr(owner, "_check_settings", lambda: None)
    monkeypatch.setattr(owner, "start", noop)
    cancelled = asyncio.Event()
    calls = []

    async def request(method, params, **kwargs):
        calls.append(method)
        sid = "kesha-native"
        if method == "session/new":
            return {"sessionId": sid, "models": {
                "currentModelId": "gemini-4-neon-high",
                "availableModels": [{"modelId": "gemini-4-neon-high"}],
            }}
        if method == "session/prompt":
            assert owner.turn_semaphore._value == owner.max_concurrent_turns - 1
            assert params["prompt"][-1]["mimeType"] == "audio/ogg"
            kwargs["on_written"]()
            owner.listeners[sid]({"sessionUpdate": "agent_thought_chunk", "content": {"text": "hidden"}})
            owner.listeners[sid]({"sessionUpdate": "usage_update", "used": 2, "size": 10,
                                  "cost": {"currency": "USD", "amount": 0.2}})
            decision = await owner.client_request_handlers[sid](
                "fs/read_text_file", {"sessionId": sid, "path": "/example"})
            assert "error" in decision
            await asyncio.wait_for(cancelled.wait(), 2)
            return {"stopReason": "cancelled", "usage": {"input_tokens": 2}}
        raise AssertionError(method)

    async def cancel(method, params):
        assert method == "session/cancel" and params == {"sessionId": "kesha-native"}
        cancelled.set()

    monkeypatch.setattr(owner, "request", request)
    monkeypatch.setattr(owner, "notify", cancel)
    mux = acp_mux.AcpMux(home)
    await mux.start()
    try:
        reader, writer = await asyncio.open_unix_connection(mux.path)
        open_params = {"origin": "telegram", "cwd": str(home), "token": "ab" * 32}
        send(writer, 1, "session/open", **open_params)
        assert (await message(reader))["result"] == {"sessionId": "kesha-native"}
        send(writer, 2, "session/prompt", sessionId="wrong", model="gemini-4-neon-high", blocks=[])
        assert "error" in await message(reader)
        send(writer, 3, "session/prompt", sessionId="kesha-native", model="gemini-4-neon-high", origin="telegram",
             blocks=[{"type": "audio", "mimeType": "audio/ogg",
                      "data": base64.b64encode(b"OggS" + b"a" * (1024 * 1024)).decode()}])
        assert (await message(reader))["method"] == "session/submitted"
        assert (await message(reader))["params"]["update"]["sessionUpdate"] == "usage_update"
        native = await message(reader)
        assert native["method"] == "fs/read_text_file"
        writer.write((json.dumps({"id": native["id"], "optionId": None}) + "\n").encode())
        send(writer, 4, "session/cancel", sessionId="kesha-native")
        replies = {reply["id"]: reply for reply in [await message(reader), await message(reader)]}
        assert replies[3]["result"] == {"stopReason": "cancelled", "accounting": {
            "input_tokens": 2, "cost_usd": 0.2,
        }}
        assert replies[4]["result"]["submitted"]
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(asyncio.gather(*mux.connections), 2)
        assert owner.turn_semaphore._value == owner.max_concurrent_turns

        reader, writer = await asyncio.open_unix_connection(mux.path)
        send(writer, 5, "session/open", **{**open_params, "token": "cd" * 32}, sessionId="kesha-native")
        assert "error" in await message(reader)
        send(writer, 6, "session/open", **open_params, sessionId="kesha-native")
        assert (await message(reader))["result"] == {"sessionId": "kesha-native"}
        assert calls == ["session/new", "session/prompt"]
        writer.close()
        await writer.wait_closed()
    finally:
        await mux.close()


@pytest.mark.asyncio
async def test_lock_contention_never_runs_fallback_preflight_or_spawn(home, monkeypatch):
    import fcntl

    from app import backend_antigravity
    from app.antigravity_acp import AcpError

    owner = AcpProfile(home)
    monkeypatch.setattr(owner, "_check_settings", lambda: None)
    monkeypatch.setattr(backend_antigravity, "_has_cached_credentials", lambda _: True)
    called = []

    async def prohibited(*args, **kwargs):
        called.append(True)
        raise AssertionError("Fallback must not probe or spawn while lock is held")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", prohibited)
    with (home / ".orchestra-acp.lock").open("w") as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(AcpError):
            await owner.start(before_spawn=prohibited, executable="unused")
        assert not called
