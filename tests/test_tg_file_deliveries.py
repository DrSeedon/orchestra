from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_EVENT = "00000000-0000-4000-8000-000000000402"
PRIMARY_CHAT = -100402001
PRIMARY_THREAD = 4021
MIRROR_CHAT = -100402002
MIRROR_THREAD = 4022


class _AlbumBot:
    def __init__(self):
        self.groups = []
        self.singles = []
        self._message_id = 40200

    def _message(self, chat_id):
        self._message_id += 1
        return SimpleNamespace(
            message_id=self._message_id,
            chat=SimpleNamespace(id=chat_id),
        )

    async def send_media_group(self, chat_id, media, message_thread_id=None):
        self.groups.append({
            "chat_id": chat_id,
            "thread_id": message_thread_id,
            "types": [type(item).__name__ for item in media],
            "names": [Path(item.media.path).name for item in media],
            "captions": [item.caption for item in media],
        })
        return [self._message(chat_id) for _item in media]

    async def send_photo(self, chat_id, photo, caption=None, message_thread_id=None):
        self.singles.append(("photo", Path(photo.path).name, caption))
        return self._message(chat_id)

    async def send_document(
        self, chat_id, document, caption=None, message_thread_id=None,
    ):
        self.singles.append(("document", Path(document.path).name, caption))
        return self._message(chat_id)


@pytest.fixture
def batch_world(tmp_path, monkeypatch):
    from app import db
    import app.tg_bridge as bridge
    import app.tg_file_deliveries as deliveries

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "batch-402.db")
    db.init_db()
    monkeypatch.setattr(deliveries, "SPOOL_ROOT", tmp_path / "outbox")
    monkeypatch.setattr(deliveries, "ensure_chat_runner", lambda _chat_id: None)
    deliveries._chat_runner_tasks.clear()
    bot = _AlbumBot()
    monkeypatch.setattr(bridge, "bot", bot)
    return SimpleNamespace(
        db=db,
        deliveries=deliveries,
        bridge=bridge,
        bot=bot,
        root=tmp_path,
    )


def _files(root: Path, names: list[str]) -> list[str]:
    paths = []
    for index, name in enumerate(names):
        path = root / name
        path.write_bytes(f"file-{index}-{name}".encode())
        paths.append(str(path))
    return paths


async def _accept(world, paths, *, event_id=ROOT_EVENT, targets=None):
    accept = getattr(world.deliveries, "accept_file_batch", None)
    assert callable(accept), "#402 RED: durable batch admission is missing"
    return await accept(
        event_id=event_id,
        source_session_id="source-402",
        source_name="worker-402",
        source_scope="/scope-402",
        source_paths=paths,
        caption="album caption",
        as_document=False,
        orch_name="orch-402",
        targets=targets or [{
            "target_kind": "primary",
            "chat_id": PRIMARY_CHAT,
            "thread_id": PRIMARY_THREAD,
        }],
    )


@pytest.mark.asyncio
async def test_send_files_12_photos_use_10_plus_2_and_one_caption(batch_world):
    world = batch_world
    paths = _files(world.root, [f"photo-{index:02}.png" for index in range(12)])

    accepted, status, _headers = await _accept(world, paths)
    assert status == 202
    assert accepted["event_id"] == ROOT_EVENT
    assert accepted["delivery_state"] == "QUEUED"
    await world.deliveries.run_chat_deliveries(PRIMARY_CHAT)

    assert [len(group["names"]) for group in world.bot.groups] == [10, 2]
    assert [name for group in world.bot.groups for name in group["names"]] == [
        Path(path).name for path in paths
    ]
    assert all(set(group["types"]) == {"InputMediaPhoto"} for group in world.bot.groups)
    captions = [caption for group in world.bot.groups for caption in group["captions"]]
    assert captions[0] == "📎 worker-402: album caption"
    assert captions[1:] == [None] * 11
    assert world.bot.singles == []


@pytest.mark.asyncio
async def test_send_files_mixed_types_make_stable_homogeneous_groups(batch_world):
    world = batch_world
    names = [
        "photo-0.png", "doc-0.pdf", "photo-1.jpg",
        *[f"doc-{index:02}.txt" for index in range(1, 12)],
        "photo-2.webp",
    ]
    paths = _files(world.root, names)

    _accepted, status, _headers = await _accept(world, paths)
    assert status == 202
    await world.deliveries.run_chat_deliveries(PRIMARY_CHAT)

    assert [len(group["names"]) for group in world.bot.groups] == [3, 10, 2]
    assert all(len(group["names"]) <= 10 for group in world.bot.groups)
    assert [set(group["types"]) for group in world.bot.groups] == [
        {"InputMediaPhoto"}, {"InputMediaDocument"}, {"InputMediaDocument"},
    ]
    assert world.bot.groups[0]["names"] == [
        "photo-0.png", "photo-1.jpg", "photo-2.webp",
    ]
    assert [name for group in world.bot.groups[1:] for name in group["names"]] == [
        "doc-0.pdf", *[f"doc-{index:02}.txt" for index in range(1, 12)],
    ]


@pytest.mark.asyncio
async def test_send_files_bad_path_rejects_whole_batch_before_acceptance(batch_world):
    world = batch_world
    valid = _files(world.root, ["valid-a.png", "valid-b.png"])
    paths = [valid[0], str(world.root / "missing.png"), valid[1]]
    error_type = getattr(world.deliveries, "BatchValidationError", None)
    assert error_type is not None, "#402 RED: batch validation error is missing"

    with pytest.raises(error_type) as caught:
        await _accept(world, paths)

    assert caught.value.invalid == [{
        "index": 1,
        "path": paths[1],
        "error": "FileNotFoundError",
    }]
    with world.db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM tg_file_deliveries").fetchone()[0] == 0
    assert world.bot.groups == []
    assert world.bot.singles == []
    assert not any(path.is_file() for path in (world.root / "outbox").rglob("*"))


@pytest.mark.asyncio
async def test_send_files_root_event_is_idempotent_for_the_ordered_manifest(batch_world):
    world = batch_world
    paths = _files(world.root, ["one.png", "two.png", "three.png"])

    first, first_status, _ = await _accept(world, paths)
    second, second_status, _ = await _accept(world, paths)
    assert (first_status, second_status) == (202, 202)
    assert (first["acceptance"], second["acceptance"]) == (
        "ACCEPTED", "ALREADY_ACCEPTED",
    )
    assert first["event_id"] == second["event_id"] == ROOT_EVENT
    assert first["payload_hash"] == second["payload_hash"]
    with world.db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM tg_file_deliveries").fetchone()[0] == 3

    Path(paths[1]).write_bytes(b"changed")
    conflict, conflict_status, _ = await _accept(world, paths)
    assert conflict_status == 409
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_send_files_mirror_gets_its_own_album(batch_world):
    world = batch_world
    paths = _files(world.root, [f"mirror-{index}.png" for index in range(3)])
    targets = [
        {"target_kind": "primary", "chat_id": PRIMARY_CHAT, "thread_id": PRIMARY_THREAD},
        {"target_kind": "mirror", "chat_id": MIRROR_CHAT, "thread_id": MIRROR_THREAD},
    ]

    await _accept(world, paths, targets=targets)
    await world.deliveries.run_chat_deliveries(PRIMARY_CHAT)
    await world.deliveries.run_chat_deliveries(MIRROR_CHAT)

    assert [(group["chat_id"], group["thread_id"], group["names"]) for group in world.bot.groups] == [
        (PRIMARY_CHAT, PRIMARY_THREAD, ["mirror-0.png", "mirror-1.png", "mirror-2.png"]),
        (MIRROR_CHAT, MIRROR_THREAD, ["mirror-0.png", "mirror-1.png", "mirror-2.png"]),
    ]


@pytest.mark.asyncio
async def test_send_files_mcp_posts_one_batch_event_without_wrapping_send_file(monkeypatch):
    import app.mcp_stdio as mcp

    calls = []
    receipt = {
        "ok": True,
        "acceptance": "ACCEPTED",
        "event_id": ROOT_EVENT,
        "delivery_state": "QUEUED",
        "payload_hash": "a" * 64,
        "files": [{"index": 0}, {"index": 1}],
    }

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return receipt

    monkeypatch.setattr(mcp, "_api", fake_api)
    send_files = getattr(mcp, "send_files", None)
    assert callable(send_files), "#402 RED: MCP send_files tool is missing"

    output = await send_files(
        ["/scope/a.png", "/scope/b.png"], "batch", event_id=ROOT_EVENT,
    )

    assert calls == [(
        "POST",
        "/api/tg/send_file",
        {"json": {
            "paths": ["/scope/a.png", "/scope/b.png"],
            "caption": "batch",
            "scope": mcp.SCOPE,
            "sender": mcp.WORKER_NAME or mcp.ROLE,
            "as_document": False,
            "event_id": ROOT_EVENT,
        }, "timeout": 180},
    )]
    assert "Files accepted" in output
    assert ROOT_EVENT in output
    assert "2 files" in output
