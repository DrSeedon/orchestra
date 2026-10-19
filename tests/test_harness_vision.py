"""Vision request boundary: catalog capability, upload validation and resumable text tags."""

import base64
from io import BytesIO
import json

import httpx
import pytest

from app.harness.llm import OpenRouterClient
from app.harness.loop import AgentLoop
from app.harness.sessions import SessionStore
from app.model_catalog import normalize_catalog_model


@pytest.fixture(autouse=True)
def _init_db():
    from app.db import init_db

    init_db()


def _png(marker=b"sample"):
    from PIL import Image

    image = Image.new("RGB", (2, 2), color=(sum(marker) % 255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _image(fmt):
    from PIL import Image

    image = Image.new("RGB", (2, 2), color="purple")
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def _client(root, *, modalities=("text", "image")):
    return OpenRouterClient(
        "test", "vendor/vision:free", supported_parameters=("tools",),
        input_modalities=modalities, attachments_root=root,
    )


def test_catalog_capability_is_preserved_for_the_model_owner():
    model = normalize_catalog_model({
        "id": "vendor/vision:free", "supported_parameters": ["tools"],
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
    })
    assert model["input_modalities"] == ["text", "image"]


def test_multiple_private_images_follow_text_as_separate_data_uri_parts(tmp_path):
    first = tmp_path / "one.png"
    second = tmp_path / "two.png"
    first.write_bytes(_png(b"first"))
    second.write_bytes(_png(b"second"))
    text = f"Please inspect these: [photo: {first}] then [file: {second} | two.png]"

    content = _client(tmp_path)._prepare_messages([{"role": "user", "content": text}])[0]["content"]

    assert content[0] == {"type": "text", "text": text}
    assert [part["type"] for part in content] == ["text", "image_url", "image_url"]
    assert content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(_png(b"first")).decode()
    assert content[2]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(_png(b"second")).decode()


def test_real_openrouter_request_boundary_keeps_photo_tag_and_orders_text_first(tmp_path):
    photo = tmp_path / "telegram.jpg"
    from PIL import Image
    image = Image.new("RGB", (2, 2), color="blue")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    photo.write_bytes(buffer.getvalue())
    handoff_text = f"[photo: {photo}]\nwhat is shown?"
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
            b'data: {"choices":[{"delta":{"content":"a cat"},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"))

    async def run():
        client = OpenRouterClient(
            "test", "vendor/vision:free", supported_parameters=("tools",),
            input_modalities=("text", "image"), attachments_root=tmp_path,
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        events = [ev async for ev in client.stream([{"role": "user", "content": handoff_text}], [])]
        await client.aclose()
        return events

    import asyncio
    assert asyncio.run(run())[-1].kind == "final"
    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": handoff_text}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64," + base64.b64encode(photo.read_bytes()).decode())
    assert "telegram.jpg" not in content[1]["image_url"]["url"]


def test_nonvision_route_keeps_original_text_fallback_without_reading_file(tmp_path):
    missing = tmp_path / "not-there.png"
    text = f"[photo: {missing}]"
    message = {"role": "user", "content": text}
    assert _client(tmp_path, modalities=("text",))._prepare_messages([message]) == [message]


def test_retarget_updates_image_capability_with_the_selected_model(tmp_path):
    photo = tmp_path / "retarget.png"
    photo.write_bytes(_png())
    message = {"role": "user", "content": f"[photo: {photo}]"}
    client = _client(tmp_path)

    client.retarget("vendor/text-only:free", ("tools",), ("text",))

    assert client._prepare_messages([message]) == [message]


@pytest.mark.parametrize(("fmt", "mime"), [
    ("PNG", "image/png"), ("JPEG", "image/jpeg"),
    ("WEBP", "image/webp"), ("GIF", "image/gif"),
])
def test_supported_image_formats_are_detected_from_validated_bytes(tmp_path, fmt, mime):
    path = tmp_path / f"sample.{fmt.lower()}"
    path.write_bytes(_image(fmt))
    url = _client(tmp_path)._prepare_messages([
        {"role": "user", "content": f"[photo: {path}]"}
    ])[0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:" + mime + ";base64,")


@pytest.mark.parametrize("data", [b"", b"not an image", b"\x89PNG\r\n\x1a\ntruncated-ish"])
def test_invalid_or_empty_image_bytes_are_not_claimed_as_supported_mime(tmp_path, data):
    photo = tmp_path / "bad.png"
    photo.write_bytes(data)
    with pytest.raises(ValueError, match="valid supported image|MIME is not a supported"):
        _client(tmp_path)._prepare_messages([{"role": "user", "content": f"[photo: {photo}]"}])


def test_path_escape_and_missing_upload_fail_before_request(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png())
    client = _client(root)
    with pytest.raises(ValueError, match="outside the Telegram uploads"):
        client._prepare_messages([{"role": "user", "content": f"[photo: {outside}]"}])
    traversal = root / ".." / "outside.png"
    with pytest.raises(ValueError, match="outside the Telegram uploads"):
        client._prepare_messages([{"role": "user", "content": f"[photo: {traversal}]"}])
    with pytest.raises(ValueError, match="unavailable"):
        client._prepare_messages([{"role": "user", "content": f"[photo: {root / 'gone.png'}]"}])


def test_inline_image_size_limit_is_explicit_and_bounds_base64_expansion(tmp_path, monkeypatch):
    from app.harness import images

    photo = tmp_path / "bounded.png"
    photo.write_bytes(_png())
    monkeypatch.setattr(images, "MAX_INLINE_IMAGE_BYTES", 8)
    with pytest.raises(ValueError, match="exceeds 8 bytes"):
        _client(tmp_path)._prepare_messages([{"role": "user", "content": f"[photo: {photo}]"}])


def test_image_symlink_cannot_escape_upload_root(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png())
    link = root / "linked.png"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="outside the Telegram uploads"):
        _client(root)._prepare_messages([{"role": "user", "content": f"[photo: {link}]"}])


@pytest.mark.asyncio
async def test_workspace_read_image_tool_reaches_openrouter_without_persisting_base64(tmp_path):
    from app.harness import tools

    workspace = tmp_path / "repo"
    assets = workspace / "assets"
    assets.mkdir(parents=True)
    image_path = assets / "logo.png"
    image_path.write_bytes(_png(b"workspace"))
    result, changed = await tools.dispatch("read_image", {"path": "assets/logo.png"}, str(workspace))
    assert result == "[workspace image: assets/logo.png]"
    assert changed is False
    assert "read_image" in tools.READONLY_NAMES

    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call-image", "type": "function", "function": {
                "name": "read_image", "arguments": "{\"path\":\"assets/logo.png\"}",
            },
        }]},
        {"role": "tool", "tool_call_id": "call-image", "content": result},
    ]
    store = SessionStore(str(tmp_path / "sessions"))
    await store.append_messages(messages)
    history = SessionStore(str(tmp_path / "sessions"), session_id=store.session_id).load()
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
            b'data: {"choices":[{"delta":{"content":"It is a logo."},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"))

    client = OpenRouterClient(
        "test", "vendor/vision:free", supported_parameters=("tools",),
        input_modalities=("text", "image"), workspace_root=workspace,
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    events = [event async for event in client.stream(history, tools.tool_schemas())]
    await client.aclose()

    assert events[-1].kind == "final"
    request_messages = captured["messages"]
    assert request_messages[0] == history[0]
    assert request_messages[1]["role"] == "tool"
    assert request_messages[1]["content"] == "Image read from workspace file: assets/logo.png"
    assert request_messages[1]["tool_call_id"] == "call-image"
    assert request_messages[2]["role"] == "user"
    assert request_messages[2]["content"][0]["type"] == "text"
    assert request_messages[2]["content"][1]["type"] == "image_url"
    assert request_messages[2]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert any(schema["function"]["name"] == "read_image" for schema in captured["tools"])
    assert history[1]["content"] == result
    assert "base64," not in json.dumps(history)
    assert SessionStore(str(tmp_path / "sessions"), session_id=store.session_id).load() == history


@pytest.mark.asyncio
async def test_workspace_read_image_rejects_outside_paths_and_symlinks(tmp_path, monkeypatch):
    from app.harness import images
    from app.harness import tools

    workspace = tmp_path / "repo"
    workspace.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png())
    link = workspace / "outside.png"
    link.symlink_to(outside)
    validated_sizes = []
    original_validate = images._validated_mime

    def observe_validation(data):
        validated_sizes.append(len(data))
        return original_validate(data)

    monkeypatch.setattr(images, "_validated_mime", observe_validation)
    result, _ = await tools.dispatch("read_image", {"path": str(outside)}, str(workspace))
    assert result.startswith("[read_image error]")
    assert validated_sizes == []
    assert "outside the workspace" in result
    linked, _ = await tools.dispatch("read_image", {"path": "outside.png"}, str(workspace))
    assert linked.startswith("[read_image error]")
    assert "outside the workspace" in linked
    assert validated_sizes == []


def test_read_image_tool_schema_follows_model_vision_capability(tmp_path):
    from types import SimpleNamespace

    from app.backend_harness import HarnessBackend
    from app.harness import tools

    backend = HarnessBackend("vendor/text-only:free", str(tmp_path))
    backend._tool_schemas = tools.tool_schemas()
    backend._llm = SimpleNamespace(input_modalities=("text",))
    text_tools = backend._turn_tool_schemas("low", allow_review=False)
    assert all(schema["function"]["name"] != "read_image" for schema in text_tools)

    backend._llm = SimpleNamespace(input_modalities=("text", "image"))
    vision_tools = backend._turn_tool_schemas("low", allow_review=False)
    assert any(schema["function"]["name"] == "read_image" for schema in vision_tools)


def test_session_resume_keeps_the_tag_and_never_persists_inline_base64(tmp_path):
    async def run():
        store = SessionStore(str(tmp_path / "sessions"))
        tag = "[photo: /srv/app/data/uploads/photo.png]"
        await store.append_messages([{"role": "user", "content": tag}])
        resumed = SessionStore(str(tmp_path / "sessions"), session_id=store.session_id)
        return tag, resumed.load()

    import asyncio
    tag, history = asyncio.run(run())
    assert history[-1]["content"] == tag
    assert "base64," not in json.dumps(history)


def test_context_compaction_keeps_image_tag_and_complete_tool_result_group():
    tag = "[photo: /srv/app/data/uploads/photo.png]"
    history = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": tag},
        {"role": "assistant", "content": "old answer " + ("x" * 3000)},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call-1", "type": "function",
            "function": {"name": "read", "arguments": "{}"},
        }]},
        {"role": "tool", "tool_call_id": "call-1", "content": "tool result"},
        {"role": "user", "content": "follow-up"},
    ]
    loop = AgentLoop(
        llm=None, mcp=None, cwd=".", history=history, tool_schemas=[], max_context=300,
    )

    assert loop._fit_context()
    assert any(message.get("content") == tag for message in history)
    assistant_index = next(i for i, message in enumerate(history) if message.get("tool_calls"))
    assert history[assistant_index + 1] == {
        "role": "tool", "tool_call_id": "call-1", "content": "tool result",
    }
    assert all("base64," not in json.dumps(message) for message in history)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected", [("stop", "empty completion"), ("length", "truncated")])
async def test_empty_and_length_responses_have_distinct_errors(tmp_path, reason, expected):
    payload = f'data: {{"choices":[{{"delta":{{}},"finish_reason":"{reason}"}}]}}\n\ndata: [DONE]\n\n'.encode()
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload)))
    client = OpenRouterClient("test", "vendor/vision:free", supported_parameters=("tools",), http=http)
    with pytest.raises(RuntimeError, match=expected):
        async for _ in client.stream([{"role": "user", "content": "hi"}], []):
            pass
    await http.aclose()


@pytest.mark.asyncio
async def test_truncated_tool_calls_are_rejected_before_tool_execution(tmp_path):
    payload = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1",'
        b'"type":"function","function":{"name":"write","arguments":"{\\"path\\":\\"x\\"}"}}]},'
        b'"finish_reason":"length"}]}\n\ndata: [DONE]\n\n'
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload)))
    client = OpenRouterClient("test", "vendor/vision:free", supported_parameters=("tools",), http=http)
    emitted = []
    with pytest.raises(RuntimeError, match="truncated"):
        async for event in client.stream([{"role": "user", "content": "hi"}], []):
            emitted.append(event.kind)
    assert "tool_call_done" not in emitted
    await http.aclose()


@pytest.mark.asyncio
async def test_reasoning_only_length_limit_preserves_usage_and_is_not_empty_or_retried():
    attempts = 0
    payload = (
        b'data: {"choices":[{"delta":{},"finish_reason":"length"}],"usage":'
        b'{"completion_tokens":700,"completion_tokens_details":{"reasoning_tokens":700}}}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenRouterClient("test", "vendor/vision:free", supported_parameters=("tools",), http=http)
    seen = []
    with pytest.raises(RuntimeError, match="truncated"):
        async for event in client.stream([{"role": "user", "content": "hi"}], []):
            seen.append(event)
    assert attempts == 1
    assert seen[-1].kind == "final"
    assert seen[-1].finish_reason == "length"
    assert seen[-1].usage["completion_tokens_details"]["reasoning_tokens"] == 700
    assert seen[-1].usage["_provider_source_record"]["endpoint"] == (
        "https://openrouter.ai/api/v1/chat/completions")
    assert all(event.kind != "tool_call_done" for event in seen)
    await http.aclose()
