"""#V-544: тяжёлая картинка доходит, детерминированный отказ не прячется в UNKNOWN."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from aiogram.exceptions import TelegramBadRequest

from app.upload_limits import MAX_PHOTO_BYTES

EVENT = "00000000-0000-4000-8000-000000000544"
SECOND_EVENT = "00000000-0000-4000-8000-000000000545"
CHAT = -100544001
THREAD = 5441


class _RecordingBot:
    """Bot-API seam: пишет, чем именно ушёл файл, и умеет отбиваться заданной ошибкой."""

    def __init__(self, failure: BaseException | None = None):
        self.failure = failure
        self.groups: list[dict] = []
        self.singles: list[tuple[str, str, int]] = []
        self.lease_seen: list[str] = []
        self.db_path: Path | None = None
        self._message_id = 54400

    def _message(self, chat_id):
        self._message_id += 1
        return SimpleNamespace(
            message_id=self._message_id, chat=SimpleNamespace(id=chat_id),
        )

    def _observe_lease(self):
        if self.db_path is None:
            return
        with sqlite3.connect(str(self.db_path)) as connection:
            row = connection.execute(
                "SELECT lease_expires_at FROM tg_file_chat_leases WHERE chat_id=?",
                (CHAT,),
            ).fetchone()
        if row:
            self.lease_seen.append(row[0])

    async def send_media_group(self, chat_id, media, message_thread_id=None):
        self._observe_lease()
        if self.failure is not None:
            raise self.failure
        self.groups.append({
            "types": [type(item).__name__ for item in media],
            "names": [Path(item.media.path).name for item in media],
        })
        return [self._message(chat_id) for _item in media]

    async def send_photo(self, chat_id, photo, caption=None, message_thread_id=None):
        self._observe_lease()
        if self.failure is not None:
            raise self.failure
        self.singles.append(("photo", Path(photo.path).name, os.path.getsize(photo.path)))
        return self._message(chat_id)

    async def send_document(
        self, chat_id, document, caption=None, message_thread_id=None,
    ):
        self._observe_lease()
        if self.failure is not None:
            raise self.failure
        self.singles.append(
            ("document", Path(document.path).name, os.path.getsize(document.path))
        )
        return self._message(chat_id)


@pytest.fixture
def world(tmp_path, monkeypatch):
    from app import db
    import app.tg_bridge as bridge
    import app.tg_file_deliveries as deliveries

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "v544.db")
    db.init_db()
    monkeypatch.setattr(deliveries, "SPOOL_ROOT", tmp_path / "outbox")
    monkeypatch.setattr(deliveries, "ensure_chat_runner", lambda _chat_id: None)
    deliveries._chat_runner_tasks.clear()
    bot = _RecordingBot()
    bot.db_path = db.DB_PATH
    monkeypatch.setattr(bridge, "bot", bot)
    return SimpleNamespace(
        db=db, deliveries=deliveries, bridge=bridge, bot=bot, root=tmp_path,
    )


def _file(root: Path, name: str, size: int) -> str:
    path = root / name
    with path.open("wb") as handle:
        handle.truncate(size)
    return str(path)


async def _accept_batch(world, paths, *, event_id=EVENT):
    return await world.deliveries.accept_file_batch(
        event_id=event_id,
        source_session_id="source-544",
        source_name="worker-544",
        source_scope="/scope-544",
        source_paths=paths,
        caption="album",
        as_document=False,
        orch_name="orch-544",
        targets=[{"target_kind": "primary", "chat_id": CHAT, "thread_id": THREAD}],
    )


async def _accept_one(world, path, *, event_id=EVENT):
    return await world.deliveries.accept_file_delivery(
        event_id=event_id,
        source_session_id="source-544",
        source_name="worker-544",
        source_scope="/scope-544",
        source_path=path,
        caption="single",
        as_document=False,
        orch_name="orch-544",
        targets=[{"target_kind": "primary", "chat_id": CHAT, "thread_id": THREAD}],
    )


def _states(world) -> list[tuple[str, str]]:
    with world.db._conn() as connection:
        return [
            (row["original_name"], row["state"])
            for row in connection.execute(
                "SELECT d.original_name, t.state FROM tg_file_delivery_targets AS t "
                "JOIN tg_file_deliveries AS d ON d.event_id=t.event_id "
                "ORDER BY d.accept_seq"
            ).fetchall()
        ]


@pytest.mark.asyncio
async def test_heavy_photo_goes_as_document_and_leaves_the_album_alive(world):
    """10.09: одна картинка на 10.5 МБ отбила альбом из семи вложений целиком."""
    paths = [
        _file(world.root, "light-a.png", 1024),
        _file(world.root, "heavy.png", MAX_PHOTO_BYTES + 1),
        _file(world.root, "light-b.png", 2048),
    ]

    _accepted, status, _headers = await _accept_batch(world, paths)
    assert status == 202
    await world.deliveries.run_chat_deliveries(CHAT)

    assert [(group["types"], group["names"]) for group in world.bot.groups] == [
        (["InputMediaPhoto"] * 2, ["light-a.png", "light-b.png"]),
    ]
    assert world.bot.singles == [
        ("document", "heavy.png", MAX_PHOTO_BYTES + 1),
    ]
    assert _states(world) == [
        ("light-a.png", "SENT"), ("heavy.png", "SENT"), ("light-b.png", "SENT"),
    ]


@pytest.mark.asyncio
async def test_single_heavy_photo_is_submitted_as_a_document(world):
    path = _file(world.root, "solo-heavy.jpg", MAX_PHOTO_BYTES + 1)

    _accepted, status, _headers = await _accept_one(world, path)
    assert status == 202
    await world.deliveries.run_chat_deliveries(CHAT)

    assert world.bot.singles == [
        ("document", "solo-heavy.jpg", MAX_PHOTO_BYTES + 1),
    ]
    assert _states(world) == [("solo-heavy.jpg", "SENT")]


@pytest.mark.asyncio
async def test_photo_at_the_cap_still_travels_as_a_photo(world):
    path = _file(world.root, "exactly-at-cap.png", MAX_PHOTO_BYTES)

    await _accept_one(world, path)
    await world.deliveries.run_chat_deliveries(CHAT)

    assert world.bot.singles == [("photo", "exactly-at-cap.png", MAX_PHOTO_BYTES)]


@pytest.mark.asyncio
async def test_provider_rejection_is_terminal_with_a_reason(world):
    world.bot.failure = TelegramBadRequest(
        method=SimpleNamespace(),
        message=(
            "Bad Request: file of size 10562238 bytes is too big for a photo; "
            "the maximum size is 10485760 bytes"
        ),
    )
    path = _file(world.root, "rejected.png", 4096)

    await _accept_one(world, path)
    await world.deliveries.run_chat_deliveries(CHAT)

    assert _states(world) == [("rejected.png", "FAILED")]
    resource = world.deliveries.get_file_delivery(EVENT, "source-544")
    assert resource["delivery_state"] == "FAILED"
    error = resource["children"]["primary"]["error"]
    assert error["code"] == "PROVIDER_REJECTED"
    assert error["outcome_unknown"] is False
    assert error["retryable"] is False
    assert "too big for a photo" in error["message"]
    assert resource["next_action"]["code"] == "DELIVERY_REJECTED"


@pytest.mark.asyncio
async def test_unclear_provider_failure_stays_unknown(world):
    world.bot.failure = TimeoutError()
    path = _file(world.root, "timed-out.png", 4096)

    await _accept_one(world, path)
    await world.deliveries.run_chat_deliveries(CHAT)

    assert _states(world) == [("timed-out.png", "UNKNOWN")]
    resource = world.deliveries.get_file_delivery(EVENT, "source-544")
    assert resource["delivery_state"] == "UNKNOWN"
    assert resource["children"]["primary"]["error"]["outcome_unknown"] is True
    assert resource["next_action"]["code"] == "CHECK_DELIVERY_STATUS"


@pytest.mark.asyncio
async def test_terminal_failure_does_not_hide_a_delivered_sibling(world):
    """FAILED одного вложения не должен читаться как SENT всей группы."""
    world.bot.failure = TelegramBadRequest(
        method=SimpleNamespace(), message="Bad Request: PHOTO_INVALID_DIMENSIONS",
    )
    paths = [
        _file(world.root, "pair-a.png", 1024), _file(world.root, "pair-b.png", 1024),
    ]

    await _accept_batch(world, paths)
    await world.deliveries.run_chat_deliveries(CHAT)

    resource = world.deliveries.get_file_delivery(EVENT, "source-544")
    assert resource["delivery_state"] == "FAILED"
    assert [item["delivery_state"] for item in resource["files"]] == ["FAILED"] * 2


@pytest.mark.asyncio
async def test_lease_outlives_the_upload_it_authorises(world, monkeypatch):
    """Истёкший посреди загрузки лизинг превращает доставленный файл в UNKNOWN.

    Базовый лизинг укорочен до секунды, чтобы порог заведомо пересекался:
    на длинной загрузке ровно так же не хватает штатных 120 с.
    """
    monkeypatch.setattr(world.deliveries, "LEASE_SECONDS", 1)
    size = 4 * 1024 * 1024
    path = _file(world.root, "slow.bin", size)

    await _accept_one(world, path)
    await world.deliveries.run_chat_deliveries(CHAT)

    assert world.bot.singles and world.bot.lease_seen
    expires = datetime.fromisoformat(world.bot.lease_seen[0])
    headroom = (expires - datetime.now(timezone.utc)).total_seconds()
    needed = world.bridge.file_submit_timeout(size)
    assert headroom > needed, (
        f"lease expires in {headroom:.0f}s, upload may take {needed:.0f}s"
    )


def test_upload_timeout_scales_with_the_file_size():
    """200 МБ ушли за 18.8 с (замер #V-544) — фиксированные 30 с резали канал."""
    from app.tg_bridge import file_submit_timeout

    assert file_submit_timeout(0) == pytest.approx(30.0)
    assert file_submit_timeout(200 * 1024 * 1024) >= 5 * 18.8
    assert file_submit_timeout(2000 * 1024 * 1024) > file_submit_timeout(
        200 * 1024 * 1024
    )


def test_durable_schema_accepts_a_document_far_above_the_old_50mb_cap(tmp_path, monkeypatch):
    """Схема с CHECK <= 52428800 отбивала любую доставку крупнее 50 МБ."""
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "schema-544.db")
    db.init_db()
    with db._conn() as connection:
        connection.execute(
            "INSERT INTO tg_file_deliveries (event_id, schema_version, source_name, "
            "source_scope, source_path, original_name, snapshot_path, size_bytes, "
            "content_sha256, caption, outbound_caption, as_document, payload_hash, "
            "created_at, updated_at) VALUES (?, 1, 'w', '/s', '/p', 'big.bin', "
            "'/snap', ?, ?, '', '', 0, ?, 't', 't')",
            (EVENT, 209_715_200, "a" * 64, "b" * 64),
        )
        connection.execute(
            "INSERT INTO tg_file_delivery_targets (event_id, target_kind, chat_id, "
            "state, updated_at) VALUES (?, 'primary', ?, 'FAILED', 't')",
            (EVENT, CHAT),
        )
