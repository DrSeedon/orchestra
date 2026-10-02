"""Отправка MP4 в Telegram видеосообщением, а не документом.

Документ в ленте — иконка файла: чтобы посмотреть ролик, его надо скачать.
`sendVideo` с длительностью, размерами, превью и `supports_streaming` даёт
проигрывание прямо в ленте, как у фото (решение владельца 02.10.2026, V-681).
Клиенты Telegram проигрывают только MPEG4, остальное Bot API велит слать
документом — поэтому видео решается по расширению.

Без width/height клиент рисует квадрат, без превью — чёрный прямоугольник до
загрузки, поэтому параметры снимаются `ffprobe`/`ffmpeg`. Их недоступность не
мешает отправке: видео уходит без метаданных. Отказ Telegram (400/403 — сообщение
не создано, исход известен) откатывается в документ; таймаут и сетевая ошибка
НЕ откатываются: исход неизвестен, и повтор документом мог бы задвоить файл.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

logger = logging.getLogger("orchestra.tg_video")

_PROBE_TIMEOUT = 20.0


@dataclass(frozen=True)
class VideoMeta:
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    thumbnail_path: str | None = None


async def _run(*argv: str) -> bytes | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.warning(f"tg_video: {argv[0]} unavailable: {exc}")
        return None
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT):
            out, _ = await proc.communicate()
    except TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning(f"tg_video: {argv[0]} timed out")
        return None
    return out if proc.returncode == 0 else None


async def probe_video(path: str, thumb_dir: str) -> VideoMeta:
    """Длительность, размеры и JPEG-превью ≤320 px; что не снялось — None."""
    raw = await _run(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json", path,
    )
    duration = width = height = None
    if raw:
        try:
            info = json.loads(raw)
            stream = (info.get("streams") or [{}])[0]
            width = int(stream["width"]) if stream.get("width") else None
            height = int(stream["height"]) if stream.get("height") else None
            seconds = float((info.get("format") or {}).get("duration") or 0)
            duration = max(1, round(seconds)) if seconds > 0 else None
        except (ValueError, TypeError, KeyError, IndexError):
            logger.warning(f"tg_video: unparsable ffprobe output for {path}")
    # Кадр из середины: у объясняющего ролика первая секунда часто пустая.
    at = f"{duration / 2:.2f}" if duration else "0"
    thumb = os.path.join(thumb_dir, "thumb.jpg")
    made = await _run(
        "ffmpeg", "-v", "error", "-y", "-ss", at, "-i", path, "-frames:v", "1",
        "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
        "-q:v", "5", thumb,
    )
    has_thumb = made is not None and os.path.isfile(thumb) and os.path.getsize(thumb) > 0
    return VideoMeta(duration, width, height, thumb if has_thumb else None)


@asynccontextmanager
async def video_meta(path: str):
    """Метаданные видео с превью во временном каталоге, убираемом после отправки."""
    with tempfile.TemporaryDirectory(prefix="tg-video-") as thumb_dir:
        yield await probe_video(path, thumb_dir)


def video_kwargs(meta: VideoMeta) -> dict:
    from aiogram.types import FSInputFile

    kwargs: dict = {"supports_streaming": True}
    if meta.duration:
        kwargs["duration"] = meta.duration
    if meta.width and meta.height:
        kwargs["width"] = meta.width
        kwargs["height"] = meta.height
    if meta.thumbnail_path:
        kwargs["thumbnail"] = FSInputFile(meta.thumbnail_path, filename="thumb.jpg")
    return kwargs


def is_rejection(exc: BaseException) -> bool:
    return isinstance(exc, (TelegramBadRequest, TelegramForbiddenError))


async def send_video_or_document(
    bot, chat_id: int, path: str, *, filename: str, caption: str | None,
    thread_id: int | None,
):
    """Одно видеосообщение; при отказе Telegram — тот же файл документом."""
    from aiogram.types import FSInputFile

    async with video_meta(path) as meta:
        try:
            return await bot.send_video(
                chat_id,
                FSInputFile(path, filename=filename),
                caption=caption,
                message_thread_id=thread_id,
                **video_kwargs(meta),
            )
        except Exception as exc:
            if not is_rejection(exc):
                raise
            logger.warning(f"tg_video: send_video rejected, sending document: {exc}")
    return await bot.send_document(
        chat_id,
        FSInputFile(path, filename=filename),
        caption=caption,
        message_thread_id=thread_id,
    )


async def send_group_with_video_fallback(
    send_group: Callable, items: list[dict], build_media: Callable,
):
    """Альбом с видео; отказ Telegram — повтор того же альбома с видео документами.

    `build_media(item, meta_or_None)` строит элемент альбома; `None` значит
    «видео как документ». Отказ альбома атомарен — ни одно сообщение не создано.
    """
    with tempfile.TemporaryDirectory(prefix="tg-video-") as root:
        metas = []
        for index, item in enumerate(items):
            if item["kind"] != "video":
                metas.append(None)
                continue
            thumb_dir = os.path.join(root, str(index))
            Path(thumb_dir).mkdir()
            metas.append(await probe_video(item["snapshot_path"], thumb_dir))
        try:
            return await send_group([
                build_media(item, meta) for item, meta in zip(items, metas, strict=True)
            ])
        except Exception as exc:
            if not is_rejection(exc) or all(meta is None for meta in metas):
                raise
            logger.warning(f"tg_video: video album rejected, sending documents: {exc}")
    return await send_group([build_media(item, None) for item in items])
