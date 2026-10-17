# Candidate cand-53

## ORIGIN commit b09a8450ed (2026-10-02): V-681: #V-681: MP4 в Telegram уходит видео с превью и откатом в документ
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 14cefc47c..e090f978d 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1940,17 +1940,17 @@ async def file_delivery_status(event_id: str) -> dict[str, Any]:
 
 @mcp.tool()
 async def send_file(
     path: str,
     caption: str = "",
     as_document: bool = False,
     event_id: str = "",
 ) -> str:
-    """Accept a local file for durable Telegram delivery; returns a status id, not delivery confirmation. Local Bot API: documents up to 2000 MB (200 MB verified); do not substitute cloud's 50 MB cap. Images above 10 485 760 bytes automatically become documents; as_document forces this for smaller images. event_id is an optional UUID; use file_delivery_status after ambiguous delivery, not a new id."""
+    """Accept a local file for durable Telegram delivery; returns a status id, not delivery confirmation. Local Bot API: documents up to 2000 MB (200 MB verified); do not substitute cloud's 50 MB cap. Images above 10 485 760 bytes automatically become documents; MP4 goes as playable video, falling back to a document if Telegram rejects it; as_document forces a document. event_id is an optional UUID; use file_delivery_status after ambiguous delivery, not a new id."""
     event_id = event_id.strip() if isinstance(event_id, str) else ""
     if event_id:
         try:
             event_id = str(uuid.UUID(event_id))
         except ValueError as error:
             raise ApiToolError(
                 code="invalid_argument",
                 message="event_id must be a UUID",
@@ -2010,17 +2010,17 @@ async def send_file(
 
 @mcp.tool()
 async def send_files(
     paths: list[str],
     caption: str = "",
     as_document: bool = False,
     event_id: str = "",
 ) -> str:
-    """Accept an ordered batch for durable Telegram album delivery; returns receipt, not completion. Local Bot API: documents up to 2000 MB (200 MB verified); images above 10 485 760 bytes become documents. Albums hold at most 10 files of one kind; longer/mixed batches split automatically. as_document forces documents. event_id is an optional UUID; resolve ambiguous delivery with file_delivery_status, not a new id."""
+    """Accept an ordered batch for durable Telegram album delivery; returns receipt, not completion. Local Bot API: documents up to 2000 MB (200 MB verified); images above 10 485 760 bytes become documents; MP4 goes as video. Albums hold at most 10 files of one kind; longer/mixed batches split automatically. as_document forces documents. event_id is an optional UUID; resolve ambiguous delivery with file_delivery_status, not a new id."""
 
     if (
         not isinstance(paths, list)
         or not paths
         or not all(isinstance(path, str) and path for path in paths)
     ):
         raise ApiToolError(
             code="invalid_argument",
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 7c2531055..84b99acde 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -37,17 +37,18 @@ from app.turn_markers import (
     SILENT_TURN_MARKER as TG_SILENT_TURN_MARKER,
     is_silent_turn_text,
 )
 from app.user_message_display import (
     add_user_message_time_prefix,
     user_message_display_content,
 )
 from app.transcription import transcribe_audio as _transcribe_audio
-from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, send_as_photo
+from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, send_as_photo, send_as_video
+from app.tg_video import send_group_with_video_fallback, send_video_or_document, video_kwargs
 
 logger = logging.getLogger("tg-bridge")
 logger.setLevel(logging.DEBUG)
 if not logger.handlers:
     logger.addHandler(logging.StreamHandler())
 
 CONFIG_PATH = Path(__file__).parent.parent / "data" / "tg_bridge.json"
 UPLOADS_DIR = Path(__file__).parent.parent / "data" / "uploads"
@@ -2564,17 +2565,17 @@ async def _tg_send_isolated_photo(
     state.image_admission_tasks.add(continuation)
     continuation.add_done_callback(state.image_admission_tasks.discard)
     return asyncio.shield(completion)
 
 
 async def _tg_send_file_safe(
     chat_id: int, path: str, caption: str | None, thread_id: int | None,
     *, is_photo: bool, important: bool, placeholder_text: str | None = None,
-    isolated_preview: bool = False,
+    isolated_preview: bool = False, is_video: bool = False,
 ):
     if is_photo and (not important or isolated_preview):
         return await _tg_send_isolated_photo(
             chat_id,
             path,
             caption,
             thread_id,
             placeholder_text,
@@ -2584,21 +2585,26 @@ async def _tg_send_file_safe(
     from aiogram.types import FSInputFile
 
     async def _send():
         tg_file = FSInputFile(path, filename=Path(path).name)
         if is_photo:
             return await bot.send_photo(
                 chat_id, tg_file, caption=caption, message_thread_id=thread_id,
             )
+        if is_video:
+            return await send_video_or_document(
+                bot, chat_id, path, filename=Path(path).name,
+                caption=caption, thread_id=thread_id,
+            )
         return await bot.send_document(
             chat_id, tg_file, caption=caption, message_thread_id=thread_id,
         )
 
-    label = "send_photo" if is_photo else "send_document"
+    label = "send_photo" if is_photo else "send_video" if is_video else "send_document"
     return await _tg_call_safe(
         chat_id,
         _send,
         important=important,
         label=label,
         best_effort=not important,
         optional_kind=("image" if is_photo else "file") if not important else None,
     )
@@ -2622,31 +2628,37 @@ def _snapshot_bytes(paths: list[str]) -> int:
 
 async def _submit_file_snapshot_once(
     chat_id: int,
     snapshot_path: str,
     caption: str,
     thread_id: int | None,
     *,
     is_photo: bool,
+    is_video: bool = False,
 ):
     """Cross the Bot API boundary once for a durable file-delivery receipt."""
     if bot is None:
         raise RuntimeError("TG bridge not active")
     from aiogram.types import FSInputFile
 
     tg_file = FSInputFile(snapshot_path, filename=Path(snapshot_path).name)
     async with asyncio.timeout(file_submit_timeout(_snapshot_bytes([snapshot_path]))):
         if is_photo:
             return await bot.send_photo(
                 chat_id,
                 tg_file,
                 caption=caption,
                 message_thread_id=thread_id,
             )
+        if is_video:
+            return await send_video_or_document(
+                bot, chat_id, snapshot_path, filename=Path(snapshot_path).name,
+                caption=caption, thread_id=thread_id,
+            )
         return await bot.send_document(
             chat_id,
             tg_file,
             caption=caption,
             message_thread_id=thread_id,
         )
 
 
@@ -2655,39 +2667,44 @@ async def _submit_file_group_once(
     items: list[dict],
     thread_id: int | None,
 ):
     """Cross one Bot API album boundary for already snapshotted durable files."""
     if bot is None:
         raise RuntimeError("TG bridge not active")
     if not 2 <= len(items) <= 10:
         raise ValueError("Telegram media group must contain 2-10 files")
-    from aiogram.types import FSInputFile, InputMediaDocument, InputMediaPhoto
+    from aiogram.types import (
+        FSInputFile, InputMediaDocument, InputMediaPhoto, InputMediaVideo,
+    )
 
-    media = []
-    for item in items:
+    def _media(item: dict, video_meta):
         tg_file = FSInputFile(
             item["snapshot_path"], filename=item["original_name"],
         )
-        media_type = InputMediaPhoto if item["kind"] == "photo" else InputMediaDocument
-        media.append(media_type(
-            media=tg_file,
-            caption=item.get("caption") or None,
-            parse_mode=None,
-        ))
-    timeout = file_submit_timeout(
-        _snapshot_bytes([item["snapshot_path"] for item in items])
-    )
-    async with asyncio.timeout(timeout):
+        common = {"media": tg_file, "caption": item.get("caption") or None, "parse_mode": None}
+        if item["kind"] == "photo":
+            return InputMediaPhoto(**common)
+        if item["kind"] == "video" and video_meta is not None:
+            return InputMediaVideo(**common, **video_kwargs(video_meta))
+        return InputMediaDocument(**common)
+
+    async def _send_group(media: list):
         return await bot.send_media_group(
             chat_id=chat_id,
             media=media,
             message_thread_id=thread_id,
         )
 
+    timeout = file_submit_timeout(
+        _snapshot_bytes([item["snapshot_path"] for item in items])
+    )
+    async with asyncio.timeout(timeout):
+        return await send_group_with_video_fallback(_send_group, items, _media)
+
 
 def is_provider_rejection(exc: BaseException) -> bool:
     """Отклонил ли Bot API сам запрос — то есть исход ИЗВЕСТЕН и он отрицательный.
 
     400/403 отдаются вместо результата: сообщение не создано, повтор того же
     payload вернёт тот же отказ. Такой исход нельзя записывать как UNKNOWN,
     иначе отправитель считает, что доставка, возможно, состоялась (#V-544).
     """
@@ -2863,32 +2880,35 @@ def _find_orch_for_scope(scope: str) -> str | None:
         if role in ("orchestrator", "sub-orchestrator"):
             if not s.get("parent_name"):
                 top_level = s["name"]
             elif any_orch is None:
                 any_orch = s["name"]
     return top_level or any_orch
 
 
-async def _mirror_send_file(orch_name: str, path: str, caption: str, is_photo: bool):
+async def _mirror_send_file(
+    orch_name: str, path: str, caption: str, is_photo: bool, is_video: bool = False,
+):
     mirror = config.get("mirrors", {}).get(orch_name)
     if not mirror or not bot:
         return False
     chat_id = mirror.get("chat_id")
     topic_id = mirror.get("topic_id")
     if not chat_id:
         return False
     return _mirror_submit(
         orch_name,
         _MirrorItem(
             chat_id=chat_id,
             topic_id=topic_id,
             path=path,
             caption=caption,
             is_photo=is_photo,
+            is_video=is_video,
         ),
     )
 
 
 def _resolve_topic(scope: str, sender: str) -> tuple[str | None, int | None]:
     """Куда слать: собственный топик отправителя, иначе топик оркестратора скоупа.
 
     Вынесено из `send_file_to_tg`, чтобы у правила был один владелец: текстовые
@@ -2944,25 +2964,26 @@ async def send_file_to_tg(path: str, caption: str, scope: str, sender: str, as_d
         return {"error": f"file too large (max {MAX_UPLOAD_MB} MB)"}
     orch_name, thread_id = _resolve_topic(scope, sender)
     logger.info(f"send_file: path={path} size={file_size} scope={scope!r} sender={sender!r} orch={orch_name!r} group_id={config['group_id']} thread_id={thread_id}")
     if not thread_id:
         return {"error": f"no TG topic for scope: {scope}"}
     label = f"📎 {sender}: {caption}" if caption else f"📎 {sender}: {fp.name}"
     label = label[:1024]
     is_photo = send_as_photo(fp.name, file_size, as_document)
+    is_video = send_as_video(fp.name, as_document)
     msg = await _tg_send_file_safe(
         config["group_id"], path, label, thread_id,
-        is_photo=is_photo, important=True,
+        is_photo=is_photo, important=True, is_video=is_video,
     )
     if msg is None:
         return {"error": "TG file delivery failed; see tg-bridge logs"}
     logger.info(f"send_file: delivered msg_id={msg.message_id} chat_id={msg.chat.id} thread={getattr(msg, 'message_thread_id', None)}")
     if orch_name:
-        await _mirror_send_file(orch_name, path, label, is_photo)
+        await _mirror_send_file(orch_name, path, label, is_photo, is_video)
     return {"ok": True, "message_id": msg.message_id, "chat_id": msg.chat.id}
 
 
 _topic_status = {}
 
 
 def _any_running_in_scope(scope: str) -> bool:
     if not _manager or not scope:
@@ -3214,31 +3235,33 @@ def _schedule_topic_status(
 class _MirrorItem:
     chat_id: int
     topic_id: int | None
     text: str | None = None
     entities: object = None
     path: str | None = None
     caption: str | None = None
     is_photo: bool = False
+    is_video: bool = False
     important: bool = False
 
 
 async def _mirror_worker(orch_name: str, outbox: asyncio.Queue) -> None:
     while True:
         item = await outbox.get()
         try:
             if item.path is not None:
                 completion = await _tg_send_file_safe(
                     item.chat_id,
                     item.path,
                     item.caption,
                     item.topic_id,
                     is_photo=item.is_photo,
                     important=False,
+                    is_video=item.is_video,
                 )
             else:
                 completion = await _tg_send_safe(
                     item.chat_id,
                     item.text or "",
                     item.topic_id,
                     entities=item.entities,
                     important=item.important,
diff --git a/app/tg_file_deliveries.py b/app/tg_file_deliveries.py
index 3a541d34c..56ac4746a 100644
--- a/app/tg_file_deliveries.py
+++ b/app/tg_file_deliveries.py
@@ -20,17 +20,17 @@ from app import db
 from app.errtext import err_text
 from app.tg_bridge import (
     _reserve_file_snapshot_slot,
     _submit_file_group_once,
     _submit_file_snapshot_once,
     file_submit_timeout,
     is_provider_rejection,
 )
-from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, send_as_photo
+from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, send_as_photo, send_as_video
 
 logger = logging.getLogger("orchestra.tg_file_deliveries")
 
 SCHEMA_VERSION = 1
 SPOOL_ROOT = Path(__file__).parent.parent / "data" / "tg-file-outbox"
 MAX_PENDING_TOTAL = 256
 MAX_PENDING_PER_CHAT = 64
 RETRY_AFTER_SECONDS = 5
@@ -330,17 +330,21 @@ def _payload_hash(
     }
     encoded = json.dumps(
         payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
     ).encode("utf-8")
     return hashlib.sha256(encoded).hexdigest()
 
 
 def _batch_kind(path: str, size_bytes: int, as_document: bool) -> str:
-    return "photo" if send_as_photo(path, size_bytes, as_document) else "document"
+    if send_as_photo(path, size_bytes, as_document):
+        return "photo"
+    if send_as_video(path, as_document):
+        return "video"
+    return "document"
 
 
 def _plan_batch(prepared: list[dict[str, Any]], as_document: bool) -> None:
     buckets: dict[str, list[dict[str, Any]]] = {}
     kind_order: list[str] = []
     for index, item in enumerate(prepared):
         kind = _batch_kind(item["original_name"], item["size_bytes"], as_document)
         item["batch_index"] = index
@@ -1492,30 +1496,32 @@ async def run_chat_deliveries(chat_id: int) -> None:
             if not _claim_group_submitting(
                 chat_id, owner_token, generation, ready,
                 max(LEASE_SECONDS, submit_timeout + LEASE_SECONDS),
             ):
                 return
             try:
                 if len(ready) == 1:
                     candidate = ready[0]
+                    kind = (
+                        candidate["batch_kind"]
+                        if candidate["batch_id"]
+                        else _batch_kind(
+                            candidate["original_name"],
+                            candidate["size_bytes"],
+                            bool(candidate["as_document"]),
+                        )
+                    )
                     result = await _submit_file_snapshot_once(
                         candidate["chat_id"],
                         candidate["snapshot_path"],
                         candidate["outbound_caption"],
                         candidate["thread_id"],
-                        is_photo=(
-                            candidate["batch_kind"] == "photo"
-                            if candidate["batch_id"]
-                            else send_as_photo(
-                                candidate["original_name"],
-                                candidate["size_bytes"],
-                                bool(candidate["as_document"]),
-                            )
-                        ),
+                        is_photo=kind == "photo",
+                        is_video=kind == "video",
                     )
                     results = [result]
                 else:
                     results = await _submit_file_group_once(
                         ready[0]["chat_id"],
                         [{
                             "snapshot_path": candidate["snapshot_path"],
                             "original_name": candidate["original_name"],
diff --git a/app/tg_video.py b/app/tg_video.py
new file mode 100644
index 000000000..c4bedec9d
--- /dev/null
+++ b/app/tg_video.py
@@ -0,0 +1,172 @@
+"""Отправка MP4 в Telegram видеосообщением, а не документом.
+
+Документ в ленте — иконка файла: чтобы посмотреть ролик, его надо скачать.
+`sendVideo` с длительностью, размерами, превью и `supports_streaming` даёт
+проигрывание прямо в ленте, как у фото (решение владельца 02.10.2026, V-681).
+Клиенты Telegram проигрывают только MPEG4, остальное Bot API велит слать
+документом — поэтому видео решается по расширению.
+
+Без width/height клиент рисует квадрат, без превью — чёрный прямоугольник до
+загрузки, поэтому параметры снимаются `ffprobe`/`ffmpeg`. Их недоступность не
+мешает отправке: видео уходит без метаданных. Отказ Telegram (400/403 — сообщение
+не создано, исход известен) откатывается в документ; таймаут и сетевая ошибка
+НЕ откатываются: исход неизвестен, и повтор документом мог бы задвоить файл.
+"""
+
+from __future__ import annotations
+
+import asyncio
+import json
+import logging
+import os
+import tempfile
+from collections.abc import Callable
+from contextlib import asynccontextmanager
+from dataclasses import dataclass
+from pathlib import Path
+
+from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
+
+logger = logging.getLogger("orchestra.tg_video")
+
+_PROBE_TIMEOUT = 20.0
+
+
+@dataclass(frozen=True)
+class VideoMeta:
+    duration: int | None = None
+    width: int | None = None
+    height: int | None = None
+    thumbnail_path: str | None = None
+
+
+async def _run(*argv: str) -> bytes | None:
+    try:
+        proc = await asyncio.create_subprocess_exec(
+            *argv,
+            stdout=asyncio.subprocess.PIPE,
+            stderr=asyncio.subprocess.DEVNULL,
+        )
+    except OSError as exc:
+        logger.warning(f"tg_video: {argv[0]} unavailable: {exc}")
+        return None
+    try:
+        async with asyncio.timeout(_PROBE_TIMEOUT):
+            out, _ = await proc.communicate()
+    except TimeoutError:
+        proc.kill()
+        await proc.wait()
+        logger.warning(f"tg_video: {argv[0]} timed out")
+        return None
+    return out if proc.returncode == 0 else None
+
+
+async def probe_video(path: str, thumb_dir: str) -> VideoMeta:
+    """Длительность, размеры и JPEG-превью ≤320 px; что не снялось — None."""
+    raw = await _run(
+        "ffprobe", "-v", "error", "-select_streams", "v:0",
+        "-show_entries", "stream=width,height:format=duration",
+        "-of", "json", path,
+    )
+    duration = width = height = None
+    if raw:
+        try:
+            info = json.loads(raw)
+            stream = (info.get("streams") or [{}])[0]
+            width = int(stream["width"]) if stream.get("width") else None
+            height = int(stream["height"]) if stream.get("height") else None
+            seconds = float((info.get("format") or {}).get("duration") or 0)
+            duration = max(1, round(seconds)) if seconds > 0 else None
+        except (ValueError, TypeError, KeyError, IndexError):
+            logger.warning(f"tg_video: unparsable ffprobe output for {path}")
+    # Кадр из середины: у объясняющего ролика первая секунда часто пустая.
+    at = f"{duration / 2:.2f}" if duration else "0"
+    thumb = os.path.join(thumb_dir, "thumb.jpg")
+    made = await _run(
+        "ffmpeg", "-v", "error", "-y", "-ss", at, "-i", path, "-frames:v", "1",
+        "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
+        "-q:v", "5", thumb,
+    )
+    has_thumb = made is not None and os.path.isfile(thumb) and os.path.getsize(thumb) > 0
+    return VideoMeta(duration, width, height, thumb if has_thumb else None)
+
+
+@asynccontextmanager
+async def video_meta(path: str):
+    """Метаданные видео с превью во временном каталоге, убираемом после отправки."""
+    with tempfile.TemporaryDirectory(prefix="tg-video-") as thumb_dir:
+        yield await probe_video(path, thumb_dir)
+
+
+def video_kwargs(meta: VideoMeta) -> dict:
+    from aiogram.types import FSInputFile
+
+    kwargs: dict = {"supports_streaming": True}
+    if meta.duration:
+        kwargs["duration"] = meta.duration
+    if meta.width and meta.height:
+        kwargs["width"] = meta.width
+        kwargs["height"] = meta.height
+    if meta.thumbnail_path:
+        kwargs["thumbnail"] = FSInputFile(meta.thumbnail_path, filename="thumb.jpg")
+    return kwargs
+
+
+def is_rejection(exc: BaseException) -> bool:
+    return isinstance(exc, (TelegramBadRequest, TelegramForbiddenError))
+
+
+async def send_video_or_document(
+    bot, chat_id: int, path: str, *, filename: str, caption: str | None,
+    thread_id: int | None,
+):
+    """Одно видеосообщение; при отказе Telegram — тот же файл документом."""
+    from aiogram.types import FSInputFile
+
+    async with video_meta(path) as meta:
+        try:
+            return await bot.send_video(
+                chat_id,
+                FSInputFile(path, filename=filename),
+                caption=caption,
+                message_thread_id=thread_id,
+                **video_kwargs(meta),
+            )
+        except Exception as exc:
+            if not is_rejection(exc):
+                raise
+            logger.warning(f"tg_video: send_video rejected, sending document: {exc}")
+    return await bot.send_document(
+        chat_id,
+        FSInputFile(path, filename=filename),
+        caption=caption,
+        message_thread_id=thread_id,
+    )
+
+
+async def send_group_with_video_fallback(
+    send_group: Callable, items: list[dict], build_media: Callable,
+):
+    """Альбом с видео; отказ Telegram — повтор того же альбома с видео документами.
+
+    `build_media(item, meta_or_None)` строит элемент альбома; `None` значит
+    «видео как документ». Отказ альбома атомарен — ни одно сообщение не создано.
+    """
+    with tempfile.TemporaryDirectory(prefix="tg-video-") as root:
+        metas = []
+        for index, item in enumerate(items):
+            if item["kind"] != "video":
+                metas.append(None)
+                continue
+            thumb_dir = os.path.join(root, str(index))
+            Path(thumb_dir).mkdir()
+            metas.append(await probe_video(item["snapshot_path"], thumb_dir))
+        try:
+            return await send_group([
+                build_media(item, meta) for item, meta in zip(items, metas, strict=True)
+            ])
+        except Exception as exc:
+            if not is_rejection(exc) or all(meta is None for meta in metas):
+                raise
+            logger.warning(f"tg_video: video album rejected, sending documents: {exc}")
+    return await send_group([build_media(item, None) for item in items])
diff --git a/app/upload_limits.py b/app/upload_limits.py
index 2bdc4af65..ab9941294 100644
--- a/app/upload_limits.py
+++ b/app/upload_limits.py
@@ -15,15 +15,29 @@ photo`. В альбоме этот отказ валит ВСЮ группу, п
 """
 
 from pathlib import Path
 
 MAX_UPLOAD_MB = 2000
 MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
 MAX_PHOTO_BYTES = 10 * 1024 * 1024
 PHOTO_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})
+# Клиенты Telegram проигрывают в ленте только MPEG4; прочее Bot API велит слать документом.
+VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v"})
 
 
 def send_as_photo(name: str, size_bytes: int, as_document: bool) -> bool:
     """Отправлять ли это вложение фотографией: решает и расширение, и размер."""
     if as_document or size_bytes > MAX_PHOTO_BYTES:
         return False
     return Path(name).suffix.lower() in PHOTO_EXTENSIONS
+
+
+def send_as_video(name: str, as_document: bool) -> bool:
+    """Отправлять ли вложение видео (проигрывается в ленте), а не документом.
+
+    Отдельного потолка размера здесь нет: локальный Bot API принимает видео до
+    общего `MAX_UPLOAD_BYTES`, а отказ Telegram откатывается в документ
+    (`app/tg_video.py`).
+    """
+    if as_document:
+        return False
+    return Path(name).suffix.lower() in VIDEO_EXTENSIONS
diff --git a/scripts/explainer_video/fonts/jetbrains-mono-cyrillic.woff2 b/scripts/explainer_video/fonts/jetbrains-mono-cyrillic.woff2
new file mode 100644
index 000000000..de39acbc4
Binary files /dev/null and b/scripts/explainer_video/fonts/jetbrains-mono-cyrillic.woff2 differ
diff --git a/scripts/explainer_video/fonts/jetbrains-mono-latin.woff2 b/scripts/explainer_video/fonts/jetbrains-mono-latin.woff2
new file mode 100644
index 000000000..4d09cda4a
Binary files /dev/null and b/scripts/explainer_video/fonts/jetbrains-mono-latin.woff2 differ
diff --git a/scripts/explainer_video/fonts/manrope-cyrillic.woff2 b/scripts/explainer_video/fonts/manrope-cyrillic.woff2
new file mode 100644
index 000000000..3a062296a
Binary files /dev/null and b/scripts/explainer_video/fonts/manrope-cyrillic.woff2 differ
diff --git a/scripts/explainer_video/fonts/manrope-latin.woff2 b/scripts/explainer_video/fonts/manrope-latin.woff2
new file mode 100644
index 000000000..71eb731d5
Binary files /dev/null and b/scripts/explainer_video/fonts/manrope-latin.woff2 differ
diff --git a/scripts/explainer_video/make.py b/scripts/explainer_video/make.py
new file mode 100644
index 000000000..aafb0cb77
--- /dev/null
+++ b/scripts/explainer_video/make.py
@@ -0,0 +1,376 @@
+"""Объясняющий ролик: сцена html-motion + русская озвучка Vosk TTS → MP4, синхронно по фразам.
+
+    uv run --frozen --project /home/kesha/orchestra python \
+        /home/kesha/orchestra/scripts/explainer_video/make.py scene.html --out DIR
+
+Озвучка задаёт время, а не наоборот: у каждого шага `STEPS` есть фраза `say`, она
+синтезируется первой, и длительность шага становится «вступление + фраза + пауза».
+Поэтому смена состояния в начале шага совпадает с началом фразы по построению, а не
+подгонкой. Подпись шага на экране — `sub`, если есть (транслитерация в `say` вроде «Дип Инфра»
+на экране выглядит странно), иначе сама фраза. Сцена получает длительности через `window.voice?.(STEPS)` — строку сразу
+после массива STEPS; без неё ролик не собирается (проверяется).
+
+Результат в DIR: `<имя>.mp4` (1920×1080, H.264 + AAC), `<имя>.timing.json` (когда звучит
+каждая фраза), `<имя>-contact.png` (кадры конца шагов для просмотра глазами) и, если
+есть DEEPGRAM_API_KEY, `<имя>.check.json` — распознанный текст и сдвиг каждой фразы.
+
+Ключи: --speaker 0..4 (3 и 4 мужские, 0–2 женские), --rate 1.0, --fps 30,
+--stills (только озвучка, тайминг и контакт-лист, без видео), --no-check.
+Синтез кэшируется по тексту фразы: правка одной фразы пересинтезирует только её,
+но первая загрузка модели занимает ~2 мин. Тяжёлое — запускать вне cgroup платформы.
+"""
+from __future__ import annotations
+
+import argparse
+import base64
+import difflib
+import hashlib
+import json
+import os
+import re
+import subprocess
+import sys
+import urllib.request
+import wave
+from concurrent.futures import ProcessPoolExecutor
+from multiprocessing import get_context
+from pathlib import Path
+
+from playwright.sync_api import sync_playwright
+
+HERE = Path(__file__).resolve().parent
+TTS_HOME = Path(os.environ.get("ORCHESTRA_TTS_HOME", Path.home() / ".local/share/orchestra-tts"))
+TTS_PYTHON = Path(os.environ.get("ORCHESTRA_TTS_PYTHON", TTS_HOME / "venv/bin/python"))
+TTS_MODEL = Path(os.environ.get("ORCHESTRA_TTS_MODEL", TTS_HOME / "vosk-model-tts-ru-0.9-multi"))
+SR = 48000
+VIEW = {"width": 1280, "height": 720}
+SCALE = 1.5  # 1280×720 CSS-пикселей → кадр 1920×1080
+LEAD = 0.35  # фраза вступает чуть позже смены состояния: глаз успевает за ухом
+GAP = 0.55  # пауза после фразы до следующего шага
+PRE, POST = 0.4, 1.6  # стоп-кадр до начала и после конца
+# Vosk TTS падает на латинице и цифрах (KeyError в словаре фонем) — их пишут словами.
+NOT_SPEAKABLE = re.compile(r"[A-Za-z0-9]")
+
+VOICE_JS = """
+window.__VOICE = %s;
+window.voice = steps => {
+  const v = window.__VOICE; if (!v) return;
+  steps.forEach((s, i) => { s.d = v.d[i]; s.x = s.sub ?? s.say; });
+  window.__VOICE_APPLIED = true;
+};
+"""
+
+
+def fail(message: str) -> None:
+    sys.exit(f"explainer_video: {message}")
+
+
+def run(*argv, **kwargs):
+    return subprocess.run(argv, check=True, **kwargs)
+
+
+def font_css() -> str:
+    ranges = {
+        "cyrillic": "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
+        "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
+                 "U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
+    }
+    rules = []
+    for family, stem, weight in (("Manrope", "manrope", "400 800"), ("JetBrains Mono", "jetbrains-mono", "400 500")):
+        for subset, urange in ranges.items():
+            data = base64.b64encode((HERE / "fonts" / f"{stem}-{subset}.woff2").read_bytes()).decode()
+            rules.append(
+                f"@font-face{{font-family:'{family}';font-weight:{weight};"
+                f"src:url(data:font/woff2;base64,{data}) format('woff2');unicode-range:{urange}}}"
+            )
+    return "\n".join(rules)
+
+
+def open_scene(pw, scene: Path, voice: dict | None):
+    browser = pw.chromium.launch()
+    page = browser.new_page(viewport=VIEW, device_scale_factor=SCALE)
+    errors: list[str] = []
+    page.on("pageerror", lambda e: errors.append(str(e)))
+    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
+    if voice is not None:
+        page.add_init_script(VOICE_JS % json.dumps(voice, ensure_ascii=False))
+    page.goto(scene.resolve().as_uri())
+    if errors:
+        fail(f"ошибки JS в сцене: {errors}")
+    page.add_style_tag(content=font_css() + "\n" + (HERE / "video.css").read_text())
+    page.evaluate("document.fonts.ready")
+    page.evaluate("P.seek(P.t)")  # перерисовать подписи после смены шрифта и вёрстки
+    return browser, page
+
+
+# ---------- озвучка ----------
+
+def read_steps(scene: Path) -> list[dict]:
+    with sync_playwright() as pw:
+        browser, page = open_scene(pw, scene, None)
+        steps = page.evaluate("STEPS.map(s => ({t: s.t, say: s.say || '', sub: s.sub || null, hold: s.hold ?? null}))")
+        browser.close()
+    for i, step in enumerate(steps, 1):
+        if not step["say"].strip():
+            fail(f"шаг {i} «{step['t']}» без фразы say")
+        if bad := sorted(set(NOT_SPEAKABLE.findall(step["say"]))):
+            fail(f"шаг {i}: в say есть {''.join(bad)} — латиницу и цифры пиши словами по-русски")
+    return steps
+
+
+def synthesize(steps: list[dict], cache: Path, speaker: int, rate: float) -> list[Path]:
+    """Каждая фраза → wav 48 кГц моно без тишины по краям (кэш по тексту и голосу)."""
+    cache.mkdir(parents=True, exist_ok=True)
+    trimmed, jobs = [], []
+    for step in steps:
+        key = hashlib.sha1(f"{step['say']}|{speaker}|{rate}|{TTS_MODEL.name}".encode()).hexdigest()[:16]
+        raw, cut = cache / f"{key}.raw.wav", cache / f"{key}.wav"
+        trimmed.append(cut)
+        if not cut.exists() and not raw.exists():
+            jobs.append({"text": step["say"], "speaker": speaker, "rate": rate, "out": str(raw)})
+    if jobs:
+        if not TTS_PYTHON.exists() or not (TTS_MODEL / "model.onnx").exists():
+            fail(f"нет окружения TTS: {TTS_PYTHON} и {TTS_MODEL}/model.onnx — установка в SKILL explainer-video")
+        print(f"синтез {len(jobs)} фраз (загрузка модели ~2 мин)…", flush=True)
+        run(str(TTS_PYTHON), str(HERE / "tts_worker.py"), input=json.dumps(jobs).encode(),
+            env={**os.environ, "ORCHESTRA_TTS_MODEL": str(TTS_MODEL)})
+    edge = "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.03"
+    for cut in trimmed:
+        if not cut.exists():
+            raw = cut.with_suffix(".raw.wav")
+            run("ffmpeg", "-v", "error", "-y", "-i", str(raw),
+                "-af", f"{edge},areverse,{edge},areverse", "-ar", str(SR), "-ac", "1",
+                "-c:a", "pcm_s16le", str(cut))
+    return trimmed
+
+
+def wav_seconds(path: Path) -> float:
+    with wave.open(str(path)) as w:
+        return w.getnframes() / w.getframerate()
+
+
+def plan(steps: list[dict], clips: list[Path]) -> dict:
+    rows, at = [], 0.0
+    for step, clip in zip(steps, clips, strict=True):
+        length = wav_seconds(clip)
+        d = round(LEAD + length + (step["hold"] if step["hold"] is not None else GAP), 3)
+        rows.append({"title": step["t"], "say": step["say"], "sub": step["sub"], "step_start": round(at, 3),
+                     "phrase_start": round(at + LEAD, 3), "phrase_end": round(at + LEAD + length, 3), "d": d})
+        at += d
+    return {"steps": rows, "T": round(at, 3), "pre": PRE, "post": POST}
+
+
+def voice_track(timing: dict, clips: list[Path], out: Path) -> None:
+    """Фразы раскладываются по своим местам в тишине; шаги не перекрываются, поэтому без микширования."""
+    total = round((PRE + timing["T"] + POST) * SR)
+    pcm = bytearray(total * 2)
+    for row, clip in zip(timing["steps"], clips, strict=True):
+        with wave.open(str(clip)) as w:
+            data = w.readframes(w.getnframes())
+        at = round((PRE + row["phrase_start"]) * SR) * 2
+        pcm[at:at + len(data)] = data[: len(pcm) - at]
+    with wave.open(str(out), "wb") as w:
+        w.setnchannels(1)
+        w.setsampwidth(2)
+        w.setframerate(SR)
+        w.writeframes(bytes(pcm))
+
+
+# ---------- кадры ----------
+
+def render(scene: Path, timing: dict, out: Path, name: str, fps: int, video: bool, jobs: int) -> None:
+    voice = {"d": [row["d"] for row in timing["steps"]]}
+    frames_dir = out / "frames"
+    frames_dir.mkdir(exist_ok=True)
+    with sync_playwright() as pw:
+        browser, page = open_scene(pw, scene, voice)
+        applied = page.evaluate("[window.__VOICE_APPLIED === true, P.T, STEPS.map(s => s.d)]")
+        if not applied[0] or abs(applied[1] - timing["T"]) > 1e-6:
+            fail("сцена не приняла длительности озвучки: после `const STEPS = [...]` нужна строка "
+                 "`window.voice?.(STEPS);` до кода плеера")
+        stills = []
+        for i, row in enumerate(timing["steps"]):
+            t = row["step_start"] + row["d"] - 0.05
+            page.evaluate(f"P.seek({t})")
+            path = frames_dir / f"step{i + 1:02d}.png"
+            page.screenshot(path=str(path))
+            stills.append(path)
+        tile = f"tile=3x{(len(stills) + 2) // 3}"
+        run("ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", str(frames_dir / "step*.png"),
+            "-vf", f"scale=640:-1,{tile}", "-frames:v", "1", str(out / f"{name}-contact.png"))
+        browser.close()
+    if not video:
+        return
+    # Кадр — чистая функция t, поэтому куски ролика снимаются параллельно и склеиваются без
+    # швов. Снимок 1920×1080 стоит ~0.35 с: в один поток 70-секундный ролик писался 25 мин.
+    total = round((PRE + timing["T"] + POST) * fps)
+    times = [min(max(k / fps - PRE, 0.0), timing["T"]) for k in range(total)]
+    size = -(-total // jobs)
+    parts = [(scene, voice, times[i:i + size], str(out / f".{name}.part{n:02d}.mp4"), fps)
+             for n, i in enumerate(range(0, total, size))]
+    with ProcessPoolExecutor(len(parts), mp_context=get_context("spawn")) as pool:
+        list(pool.map(render_part, parts))
+    listing = out / f".{name}.parts.txt"
+    listing.write_text("".join(f"file '{Path(part[3]).name}'\n" for part in parts))
+    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
+        "-c", "copy", str(out / f"{name}.video.mp4"))
+    for part in parts:
+        Path(part[3]).unlink()
+    listing.unlink()
+
+
+def render_part(args) -> None:
+    scene, voice, times, path, fps = args
+    ff = subprocess.Popen(
+        ["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-f", "image2pipe", "-i", "-",
+         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", path],
+        stdin=subprocess.PIPE)
+    with sync_playwright() as pw:
+        browser, page = open_scene(pw, scene, voice)
+        last_t, shot = None, b""
+        for t in times:
+            if t != last_t:
+                page.evaluate(f"P.seek({t})")
+                shot = page.screenshot(type="png", animations="allow")
+                last_t = t
+            ff.stdin.write(shot)
+        browser.close()
+    ff.stdin.close()
+    if ff.wait() != 0:
+        raise RuntimeError(f"ffmpeg не собрал кусок {path}")
+
+
+def mux(out: Path, name: str) -> Path:
+    mp4 = out / f"{name}.mp4"
+    run("ffmpeg", "-v", "error", "-y", "-i", str(out / f"{name}.video.mp4"), "-i", str(out / f"{name}.voice.wav"),
+        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
+        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-ac", "2", "-c:a", "aac", "-b:a", "160k",
+        "-shortest", "-movflags", "+faststart", str(mp4))
+    (out / f"{name}.video.mp4").unlink()
+    return mp4
+
+
+# ---------- проверка распознаванием ----------
+
+def tokens(text: str) -> list[str]:
+    """Слова для сверки с распознанным: регистр, ё/э → е, «7 680» → «7680», граница
+    кириллицы и латиницы — граница слова (Deepgram склеивает «иstreamlake»). Сравнение по
+    первым 5 знакам гасит падежи («кеша»/«кешу»)."""
+    text = text.lower().replace("ё", "е").replace("э", "е")
+    text = re.sub(r"(?<=\d) (?=\d{3}\b)", "", text)
+    text = re.sub(r"(?<=[а-я])(?=[a-z0-9])|(?<=[a-z0-9])(?=[а-я])", " ", text)
+    return [w[:5] for w in re.findall(r"[a-zа-я0-9]+", text)]
+
+
+def align(phrases: list[str], heard: list[str]) -> list[list[int | None]]:
+    """Для каждого слова каждой фразы — индекс распознанного слова или None."""
+    planned = [(i, w) for i, phrase in enumerate(phrases) for w in tokens(phrase)]
+    match: dict[int, int] = {}
+    matcher = difflib.SequenceMatcher(None, [w for _i, w in planned], heard, autojunk=False)
+    for block in matcher.get_matching_blocks():
+        for k in range(block.size):
+            match[block.a + k] = block.b + k
+    return [[match.get(k) for k, (i, _w) in enumerate(planned) if i == n] for n in range(len(phrases))]
+
+
+def voice_onsets(mp4: Path) -> list[float]:
+    """Где в итоговом MP4 (после AAC и loudnorm) кончается тишина — фактические начала фраз."""
+    log = run("ffmpeg", "-v", "info", "-i", str(mp4), "-vn", "-af", "silencedetect=noise=-40dB:d=0.25",
+              "-f", "null", "-", capture_output=True, text=True).stderr
+    return [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
+
+
+def check(out: Path, name: str, timing: dict, key: str) -> dict:
+    """Deepgram nova-2 по итоговому MP4: дословность каждой фразы и сдвиг её начала от плана."""
+    audio = run("ffmpeg", "-v", "error", "-i", str(out / f"{name}.mp4"), "-vn", "-ac", "1", "-ar", "16000",
+                "-f", "wav", "-", capture_output=True).stdout
+    request = urllib.request.Request(
+        "https://api.deepgram.com/v1/listen?model=nova-2&language=ru&punctuate=true&smart_format=false",
+        data=audio, headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"})
+    with urllib.request.urlopen(request, timeout=120) as response:
+        words = json.load(response)["results"]["channels"][0]["alternatives"][0]["words"]
+    # Deepgram пишет числа цифрами, а латинские названия — латиницей, поэтому фраза
+    # сверяется дважды: как произнесена (`say`) и как написана на экране (`sub`).
+    heard_words = []  # распознанное слово → его индекс в words (слово может дробиться)
+    for n, w in enumerate(words):
+        heard_words += [(t, n) for t in tokens(w["word"])]
+    heard = [t for t, _n in heard_words]
+    by_say = align([row["say"] for row in timing["steps"]], heard)
+    by_sub = align([row["sub"] or row["say"] for row in timing["steps"]], heard)
+    onsets = voice_onsets(out / f"{name}.mp4")
+    rows = []
+    for row, say_hits, sub_hits in zip(timing["steps"], by_say, by_sub, strict=True):
+        recall = lambda hits: sum(h is not None for h in hits) / len(hits)  # noqa: E731
+        hits = max(say_hits, sub_hits, key=recall)
+        first = next((h for h in (say_hits[0], sub_hits[0]) if h is not None), None)
+        start = words[heard_words[first][1]]["start"] if first is not None else None
+        # Первое слово записи Deepgram иногда ставит на 0.0 при тишине перед ним: это не сдвиг.
+        if start == 0.0:
+            start = None
+        rows.append({
+            "say": row["say"],
+            "heard": " ".join(dict.fromkeys(words[heard_words[h][1]]["word"] for h in hits if h is not None)),
+            "recall": round(recall(hits), 2),
+            "planned_start": round(PRE + row["phrase_start"], 2),
+            "heard_start": start,
+            "offset_s": round(start - (PRE + row["phrase_start"]), 2) if start is not None else None,
+            "onset_offset_s": min((round(o - (PRE + row["phrase_start"]), 2) for o in onsets), key=abs, default=None),
+        })
+    offsets = [abs(r["offset_s"]) for r in rows if r["offset_s"] is not None]
+    onset_offsets = [abs(r["onset_offset_s"]) for r in rows if r["onset_offset_s"] is not None]
+    report = {
+        "transcript": " ".join(w["word"] for w in words),
+        "recall_min": min(r["recall"] for r in rows),
+        "offset_max_abs_s": max(offsets) if offsets else None,
+        "onset_offset_max_abs_s": max(onset_offsets) if onset_offsets else None,
+        "phrases": rows,
+        "words": [[w["word"], w["start"], w["end"]] for w in words],
+    }
+    (out / f"{name}.check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
+    return report
+
+
+def main() -> None:
+    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
+    ap.add_argument("scene", type=Path)
+    ap.add_argument("--out", type=Path, required=True)
+    ap.add_argument("--speaker", type=int, default=3)
+    ap.add_argument("--rate", type=float, default=1.0)
+    ap.add_argument("--fps", type=int, default=30)
+    ap.add_argument("--jobs", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 2)),
+                    help="параллельных Chromium при записи")
+    ap.add_argument("--stills", action="store_true", help="без видео: тайминг и контакт-лист")
+    ap.add_argument("--no-check", action="store_true")
+    ap.add_argument("--check-only", action="store_true", help="только проверить готовый MP4")
+    args = ap.parse_args()
+    out, name = args.out, args.scene.stem
+    out.mkdir(parents=True, exist_ok=True)
+
+    steps = read_steps(args.scene)
+    clips = synthesize(steps, out / ".tts-cache", args.speaker, args.rate)
+    timing = plan(steps, clips)
+    (out / f"{name}.timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1))
+    for row in timing["steps"]:
+        print(f"  {row['phrase_start']:6.2f}–{row['phrase_end']:6.2f}  шаг {row['d']:5.2f} с  {row['say']}")
+    print(f"длина ролика {PRE + timing['T'] + POST:.1f} с")
+    if not args.check_only:
+        voice_track(timing, clips, out / f"{name}.voice.wav")
+        render(args.scene, timing, out, name, args.fps, video=not args.stills, jobs=args.jobs)
+        print(out / f"{name}-contact.png")
+        if args.stills:
+            return
+        mp4 = mux(out, name)
+        print(mp4, f"{mp4.stat().st_size / 1e6:.1f} МБ")
+    key = os.environ.get("DEEPGRAM_API_KEY")
+    if args.no_check or not key:
+        print("проверка распознаванием пропущена" + ("" if key else ": нет DEEPGRAM_API_KEY"))
+        return
+    report = check(out, name, timing, key)
+    for r in report["phrases"]:
+        print(f"  recall {r['recall']:.2f}  сдвиг слова {r['offset_s']}  звука {r['onset_offset_s']}  {r['say']}\n      слышно: {r['heard']}")
+    print(f"минимальная дословность {report['recall_min']}, наибольший сдвиг: первого слова "
+          f"{report['offset_max_abs_s']} с, начала звука {report['onset_offset_max_abs_s']} с")
+
+
+if __name__ == "__main__":
+    main()
diff --git a/scripts/explainer_video/tts_worker.py b/scripts/explainer_video/tts_worker.py
new file mode 100644
index 000000000..ab632c2e2
--- /dev/null
+++ b/scripts/explainer_video/tts_worker.py
@@ -0,0 +1,21 @@
+"""Синтез фраз Vosk TTS: JSON-список заданий на stdin → wav-файлы.
+
+Запускается интерпретатором окружения TTS (`ORCHESTRA_TTS_PYTHON`), а не рантаймом
+Orchestra: vosk-tts тянет onnxruntime и numpy, которых в рантайме нет.
+Задание: {"text", "speaker", "rate", "out"}. Модель грузится один раз (~2 мин).
+"""
+import json
+import os
+import sys
+import warnings
+
+warnings.filterwarnings("ignore")
+from vosk_tts import Model, Synth  # noqa: E402
+
+jobs = json.load(sys.stdin)
+synth = Synth(Model(model_path=os.environ["ORCHESTRA_TTS_MODEL"]))
+for job in jobs:
+    tmp = job["out"] + ".part"
+    synth.synth(job["text"], tmp, speaker_id=job["speaker"], speech_rate=job["rate"])
+    os.replace(tmp, job["out"])
+    print(f"tts: {job['out']}", file=sys.stderr, flush=True)
diff --git a/scripts/explainer_video/video.css b/scripts/explainer_video/video.css
new file mode 100644
index 000000000..9224be468
--- /dev/null
+++ b/scripts/explainer_video/video.css
@@ -0,0 +1,10 @@
+/* Кадр ролика 16:9 поверх каркаса html-motion: тёмная сцена, без кнопок, подпись = закадровый текст. */
+:root{color-scheme:dark}
+html,body{background:#0b0e14;color:#e6e6e6;font-family:Manrope,system-ui,sans-serif}
+.mv{max-width:none;margin:0;height:100vh;box-sizing:border-box;padding:28px 56px 22px;border-radius:0;box-shadow:none;background:#0b0e14;display:flex;flex-direction:column}
+.mv h1{font-size:30px;font-weight:700;color:#fff;margin:0 0 4px;letter-spacing:-.01em}
+.stg{flex:1;min-height:0;overflow:hidden}.stg>svg{min-width:0;width:100%;height:100%}
+#stage{fill:#e6e6e6;font-family:Manrope,system-ui,sans-serif}
+.cap{min-height:4.6em;margin:4px 0 0;font-size:22px;line-height:1.38;color:#d5d8df}
+.cap b{font-size:14px;font-weight:700;color:#58c4dd;text-transform:uppercase;letter-spacing:.07em;margin-bottom:2px}
+.bar,.ch{display:none!important}
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index b1b21d8c2..85d491bdc 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -61,17 +61,17 @@ class TestDefaultManifestLoads:
         assert cfg.roles["full-cycle"].kind == "worker"
 
     def test_defaults_reproduce_upstream(self):
         """Дефолты пайплайна = поведение апстрима: model opus, без skills/mcp-форса,
         base_branch_strategy main, docs_scaffold off, слои БЕЗ _pipeline.md."""
         cfg = P.load_pipeline(PIPELINE)
         d = cfg.defaults
         assert d.model == "opus"
-        assert d.skills == ["html-artifacts", "html-motion"]  # unified visuals + animation companion for every role
+        assert d.skills == ["html-artifacts", "html-motion", "explainer-video"]  # visuals, animation, narrated video for every role
         assert d.mcp_servers == []  # апстрим не прокидывает user-MCP
         assert d.base_branch_strategy == "main"  # все worktree от main
         assert d.docs_scaffold is False  # апстрим не скаффолдит doc-папки
         assert d.inherit_claude_md is True  # CLAUDE.md проекта копируется в worktree
 
     def test_prompt_layers_have_no_pipeline_layer(self):
         """У апстрима НЕТ _pipeline.md — только base + роль."""
         cfg = P.load_pipeline(PIPELINE)
@@ -212,17 +212,18 @@ class TestDefaultRolesResolve:
             assert anchor not in worker_out, f"маршрутизация протекла воркеру: {anchor[:40]}"
 
     def test_tg_emoji_for_v216_roles(self):
         assert P.get_role(PIPELINE, "sub-orchestrator").tg.emoji == "🎯"
 
     def test_orchestrator_skills_from_manifest(self):
         rr = P.get_role(PIPELINE, "orchestrator")
         assert set(rr.skills) == {
-            "html-artifacts", "html-motion", "grill-me", "orchestra-agents", "laptop-access",
+            "html-artifacts", "html-motion", "explainer-video", "grill-me", "orchestra-agents",
+            "laptop-access",
         }
 
     def test_orchestrator_can_spawn_wildcard_and_unrouted(self):
         """Апстрим не ограничивает оркестратора: can_spawn=['*'], дефолтный
         role='worker'/пустая роль допустима."""
         rr = P.get_role(PIPELINE, "orchestrator")
         assert "worker" in rr.can_spawn
         assert rr.allow_unrouted_workers is True
@@ -420,17 +421,17 @@ class TestUpstreamCharacterization:
             assert body.startswith("<role>"), f"{role}.md must start with <role>"
             # метаданные переехали в yaml — в теле их быть не должно как frontmatter
             assert not body.lstrip().startswith("---")
             assert "\nname:" not in body[:200]
 
     def test_skill_files_keep_frontmatter(self):
         """skills/*.md портированы С frontmatter (это skill-метаданные name/description,
         их читает inject_skills_to_worktree)."""
-        for skill in ("html-artifacts", "html-motion"):
+        for skill in ("html-artifacts", "html-motion", "explainer-video"):
             text = P.prompt_path(PIPELINE, f"skills/{skill}.md").read_text()
             assert text.lstrip().startswith("---"), f"{skill}.md must keep frontmatter"
             assert f"name: {skill}" in text
 
     def test_build_prompt_matches_concatenation_of_layers(self):
         """build_system_prompt(orchestrator) = base.md + role + modules."""
         base = P.prompt_path(PIPELINE, "base.md").read_text()
         role = P.prompt_path(PIPELINE, "roles/orchestrator.md").read_text()
diff --git a/tests/test_explainer_video.py b/tests/test_explainer_video.py
new file mode 100644
index 000000000..1dd649bb1
--- /dev/null
+++ b/tests/test_explainer_video.py
@@ -0,0 +1,32 @@
+"""Сверка распознанной озвучки с планом (scripts/explainer_video/make.py, V-681).
+
+Это оракул приёмки ролика: если он не узнаёт фразу, произнесённую дословно, агент
+перефразирует понятный текст или, наоборот, пропустит невнятный.
+"""
+import importlib.util
+from pathlib import Path
+
+ROOT = Path(__file__).resolve().parents[1]
+spec = importlib.util.spec_from_file_location("explainer_make", ROOT / "scripts/explainer_video/make.py")
+make = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(make)
+
+
+def test_deepgram_digits_latin_and_glued_words_match_screen_text():
+    heard = make.tokens("а deepinfra иstreamlake держат кэш 7680 токенов")
+    say, sub = "А Дип Инфра и Стрим Лейк держат кеш", "А DeepInfra и StreamLake держат кеш, 7 680 токенов"
+    assert all(h is not None for h in make.align([sub], heard)[0])
+    assert None in make.align([say], heard)[0]  # транслитерацию Deepgram пишет латиницей
+
+
+def test_missing_word_is_reported_per_phrase():
+    heard = make.tokens("один замер на ячейку")
+    hits = make.align(["Оговорка: один замер", "на ячейку"], heard)
+    assert hits[0][0] is None and hits[0][1:] == [0, 1]
+    assert hits[1] == [2, 3]
+
+
+def test_say_rejects_latin_and_digits_before_synthesis():
+    assert make.NOT_SPEAKABLE.search("кеш 20 минут")
+    assert make.NOT_SPEAKABLE.search("кеш Together")
+    assert not make.NOT_SPEAKABLE.search("Кеш живёт двадцать минут — у Тугезера.")
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index d08e65f2a..77f213bac 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -5237,8 +5237,172 @@ class TestSendMessageOwnBubble:
         async def send_expandable(chat_id, thread_id, header, body, **kw):
             shown.append((header, body))
 
         monkeypatch.setattr(tb, "_send_expandable", send_expandable)
         monkeypatch.setattr(tb, "config", {"group_id": -100})
         await tb._update_progress(state, 42, "orch", force=True)
         head, body = shown[0]
         assert head.startswith("⚙️ 1 ") and len(body.splitlines()) == 1
+
+
+# ── V-681: MP4 уходит видео (проигрывается в ленте), отказ → документ ───────
+
+
+@pytest.fixture
+def mp4_file(tmp_path):
+    import shutil
+    import subprocess
+
+    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
+        pytest.skip("ffmpeg/ffprobe not installed")
+    path = tmp_path / "explainer.mp4"
+    subprocess.run(
+        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10",
+         "-t", "3", "-pix_fmt", "yuv420p", str(path)],
+        check=True,
+    )
+    return path
+
+
+def _video_bot(send_video_error=None):
+    from aiogram.methods import SendVideo
+
+    message = SimpleNamespace(message_id=681, chat=SimpleNamespace(id=-100123456))
+    calls = []
+
+    class _Bot:
+        async def send_video(self, chat_id, video, **kwargs):
+            calls.append(("video", chat_id, video, kwargs))
+            if send_video_error == "reject":
+                raise TelegramBadRequest(
+                    method=SendVideo(chat_id=chat_id, video="x"),
+                    message="VIDEO_CONTENT_TYPE_INVALID",
+                )
+            if send_video_error == "network":
+                raise TelegramNetworkError(


## LATER FIX 5365e1ab41 (3.1 days later): V-701: #V-701: fix Telegram media routing
lines of origin it changed/deleted: 4
(code only, capped 400 lines)

V-701: #V-701: fix Telegram media routing

Squashed commits:
- #V-701: fix Telegram media routing
- #V-701: record Telegram mutation checks
- #V-701: record imported Telegram modules
- #V-701: fix gate regressions in photo classification

Orchestra-Operation: 9ee540de-0135-40f0-ac0f-6f9a1cfbf058


diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 692075f0a..c686d9bb6 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -38,17 +38,20 @@ from app.turn_markers import (
     SILENT_TURN_MARKER as TG_SILENT_TURN_MARKER,
     is_silent_turn_text,
 )
 from app.user_message_display import (
     add_user_message_time_prefix,
     user_message_display_content,
 )
 from app.transcription import transcribe_audio as _transcribe_audio
-from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, send_as_photo, send_as_video
+from app.upload_limits import (
+    MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, photo_geometry_valid, send_as_photo,
+    send_as_video,
+)
 from app.tg_video import send_group_with_video_fallback, send_video_or_document, video_kwargs
 
 logger = logging.getLogger("tg-bridge")
 logger.setLevel(logging.DEBUG)
 if not logger.handlers:
     logger.addHandler(logging.StreamHandler())
 
 CONFIG_PATH = Path(__file__).parent.parent / "data" / "tg_bridge.json"
@@ -357,16 +360,28 @@ async def _resolve_orch(msg: types.Message) -> tuple[str | None, object | None]:
             orch_name = name
             break
     if not orch_name:
         for name, mirror in config.get("mirrors", {}).items():
             if msg.chat.id == mirror.get("chat_id") and thread_id == mirror.get("topic_id"):
                 orch_name = name
                 break
     if not orch_name:
+        if msg.chat.id == config.get("group_id"):
+            logger.warning(
+                "TG incoming message not delivered: unmapped topic chat=%s thread=%s",
+                msg.chat.id,
+                thread_id,
+            )
+            await _tg_send_safe(
+                config["group_id"],
+                "❌ Сообщение не доставлено: эта тема Telegram не привязана к агенту.",
+                thread_id,
+                important=True,
+            )
         return None, None
     session = await _manager.ensure_loaded_any(orch_name)
     if not session:
         await msg.reply(f"❌ {orch_name} not found")
         return orch_name, None
     return orch_name, session
 
 
@@ -2572,16 +2587,19 @@ async def _tg_send_isolated_photo(
     return asyncio.shield(completion)
 
 
 async def _tg_send_file_safe(
     chat_id: int, path: str, caption: str | None, thread_id: int | None,
     *, is_photo: bool, important: bool, placeholder_text: str | None = None,
     isolated_preview: bool = False, is_video: bool = False,
 ):
+    if is_photo and not photo_geometry_valid(path):
+        logger.info("TG image sent as document because its dimensions are invalid: %s", path)
+        is_photo = False
     if is_photo and (not important or isolated_preview):
         return await _tg_send_isolated_photo(
             chat_id,
             path,
             caption,
             thread_id,
             placeholder_text,
             important=important,
@@ -2638,16 +2656,18 @@ async def _submit_file_snapshot_once(
     thread_id: int | None,
     *,
     is_photo: bool,
     is_video: bool = False,
 ):
     """Cross the Bot API boundary once for a durable file-delivery receipt."""
     if bot is None:
         raise RuntimeError("TG bridge not active")
+    if is_photo and not photo_geometry_valid(snapshot_path):
+        is_photo = False
     from aiogram.types import FSInputFile
 
     tg_file = FSInputFile(snapshot_path, filename=Path(snapshot_path).name)
     async with asyncio.timeout(file_submit_timeout(_snapshot_bytes([snapshot_path]))):
         if is_photo:
             return await bot.send_photo(
                 chat_id,
                 tg_file,
@@ -2676,16 +2696,31 @@ async def _submit_file_group_once(
     if bot is None:
         raise RuntimeError("TG bridge not active")
     if not 2 <= len(items) <= 10:
         raise ValueError("Telegram media group must contain 2-10 files")
     from aiogram.types import (
         FSInputFile, InputMediaDocument, InputMediaPhoto, InputMediaVideo,
     )
 
+    safe_items = [
+        {
+            **item,
+            "kind": (
+                "document"
+                if item["kind"] == "photo"
+                and not photo_geometry_valid(item["snapshot_path"])
+                else item["kind"]
+            ),
+        }
+        for item in items
+    ]
+    if any(item["kind"] == "document" for item in safe_items):
+        safe_items = [{**item, "kind": "document"} for item in safe_items]
+
     def _media(item: dict, video_meta):
         tg_file = FSInputFile(
             item["snapshot_path"], filename=item["original_name"],
         )
         common = {"media": tg_file, "caption": item.get("caption") or None, "parse_mode": None}
         if item["kind"] == "photo":
             return InputMediaPhoto(**common)
         if item["kind"] == "video" and video_meta is not None:
@@ -2695,20 +2730,20 @@ async def _submit_file_group_once(
     async def _send_group(media: list):
         return await bot.send_media_group(
             chat_id=chat_id,
             media=media,
             message_thread_id=thread_id,
         )
 
     timeout = file_submit_timeout(
-        _snapshot_bytes([item["snapshot_path"] for item in items])
+        _snapshot_bytes([item["snapshot_path"] for item in safe_items])
     )
     async with asyncio.timeout(timeout):
-        return await send_group_with_video_fallback(_send_group, items, _media)
+        return await send_group_with_video_fallback(_send_group, safe_items, _media)
 
 
 def is_provider_rejection(exc: BaseException) -> bool:
     """Отклонил ли Bot API сам запрос — то есть исход ИЗВЕСТЕН и он отрицательный.
 
     400/403 отдаются вместо результата: сообщение не создано, повтор того же
     payload вернёт тот же отказ. Такой исход нельзя записывать как UNKNOWN,
     иначе отправитель считает, что доставка, возможно, состоялась (#V-544).
@@ -2968,17 +3003,19 @@ async def send_file_to_tg(path: str, caption: str, scope: str, sender: str, as_d
     if file_size > MAX_UPLOAD_BYTES:
         return {"error": f"file too large (max {MAX_UPLOAD_MB} MB)"}
     orch_name, thread_id = _resolve_topic(scope, sender)
     logger.info(f"send_file: path={path} size={file_size} scope={scope!r} sender={sender!r} orch={orch_name!r} group_id={config['group_id']} thread_id={thread_id}")
     if not thread_id:
         return {"error": f"no TG topic for scope: {scope}"}
     label = f"📎 {sender}: {caption}" if caption else f"📎 {sender}: {fp.name}"
     label = label[:1024]
-    is_photo = send_as_photo(fp.name, file_size, as_document)
+    is_photo = send_as_photo(
+        fp.name, file_size, as_document, photo_path=str(fp),
+    )
     is_video = send_as_video(fp.name, as_document)
     msg = await _tg_send_file_safe(
         config["group_id"], path, label, thread_id,
         is_photo=is_photo, important=True, is_video=is_video,
     )
     if msg is None:
         return {"error": "TG file delivery failed; see tg-bridge logs"}
     logger.info(f"send_file: delivered msg_id={msg.message_id} chat_id={msg.chat.id} thread={getattr(msg, 'message_thread_id', None)}")
diff --git a/app/tg_file_deliveries.py b/app/tg_file_deliveries.py
index 56ac4746a..e6095b1bc 100644
--- a/app/tg_file_deliveries.py
+++ b/app/tg_file_deliveries.py
@@ -330,28 +330,35 @@ def _payload_hash(
     }
     encoded = json.dumps(
         payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
     ).encode("utf-8")
     return hashlib.sha256(encoded).hexdigest()
 
 
 def _batch_kind(path: str, size_bytes: int, as_document: bool) -> str:
-    if send_as_photo(path, size_bytes, as_document):
+    photo_path = path if Path(path).is_file() else None
+    if send_as_photo(
+        Path(path).name, size_bytes, as_document, photo_path=photo_path,
+    ):
         return "photo"
     if send_as_video(path, as_document):
         return "video"
     return "document"
 
 
 def _plan_batch(prepared: list[dict[str, Any]], as_document: bool) -> None:
     buckets: dict[str, list[dict[str, Any]]] = {}
     kind_order: list[str] = []
     for index, item in enumerate(prepared):
-        kind = _batch_kind(item["original_name"], item["size_bytes"], as_document)
+        kind = _batch_kind(
+            item.get("source_path") or item["original_name"],
+            item["size_bytes"],
+            as_document,
+        )
         item["batch_index"] = index
         item["batch_kind"] = kind
         if kind not in buckets:
             buckets[kind] = []
             kind_order.append(kind)
         buckets[kind].append(item)
     group_index = 0
     for kind in kind_order:
@@ -1500,17 +1507,17 @@ async def run_chat_deliveries(chat_id: int) -> None:
                 return
             try:
                 if len(ready) == 1:
                     candidate = ready[0]
                     kind = (
                         candidate["batch_kind"]
                         if candidate["batch_id"]
                         else _batch_kind(
-                            candidate["original_name"],
+                            candidate["snapshot_path"],
                             candidate["size_bytes"],
                             bool(candidate["as_document"]),
                         )
                     )
                     result = await _submit_file_snapshot_once(
                         candidate["chat_id"],
                         candidate["snapshot_path"],
                         candidate["outbound_caption"],
diff --git a/app/upload_limits.py b/app/upload_limits.py
index ab9941294..23760b62a 100644
--- a/app/upload_limits.py
+++ b/app/upload_limits.py
@@ -19,21 +19,46 @@ from pathlib import Path
 MAX_UPLOAD_MB = 2000
 MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
 MAX_PHOTO_BYTES = 10 * 1024 * 1024
 PHOTO_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})
 # Клиенты Telegram проигрывают в ленте только MPEG4; прочее Bot API велит слать документом.
 VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v"})
 
 
-def send_as_photo(name: str, size_bytes: int, as_document: bool) -> bool:
-    """Отправлять ли это вложение фотографией: решает и расширение, и размер."""
+def send_as_photo(
+    name: str,
+    size_bytes: int,
+    as_document: bool,
+    *,
+    photo_path: str | None = None,
+) -> bool:
+    """Выбрать photo по типу и размеру, проверяя геометрию при наличии пути."""
     if as_document or size_bytes > MAX_PHOTO_BYTES:
         return False
-    return Path(name).suffix.lower() in PHOTO_EXTENSIONS
+    return (
+        Path(name).suffix.lower() in PHOTO_EXTENSIONS
+        and (photo_path is None or photo_geometry_valid(photo_path))
+    )
+
+
+def photo_geometry_valid(path: str) -> bool:
+    from PIL import Image
+
+    try:
+        with Image.open(path) as image:
+            width, height = image.size
+    except Exception:
+        return False
+    return (
+        width > 0
+        and height > 0
+        and width + height <= 10_000
+        and max(width, height) <= 20 * min(width, height)
+    )
 
 
 def send_as_video(name: str, as_document: bool) -> bool:
     """Отправлять ли вложение видео (проигрывается в ленте), а не документом.
 
     Отдельного потолка размера здесь нет: локальный Bot API принимает видео до
     общего `MAX_UPLOAD_BYTES`, а отказ Telegram откатывается в документ
     (`app/tg_video.py`).
diff --git a/tests/test_audit0901_tg.py b/tests/test_audit0901_tg.py
index c524129a9..f62d9c7c7 100644
--- a/tests/test_audit0901_tg.py
+++ b/tests/test_audit0901_tg.py
@@ -132,16 +132,50 @@ async def test_second_resolve_of_a_live_token_delivers_nothing(tb, monkeypatch):
             f"вторым сообщением: {manager.sent!r}"
         )
     finally:
         if buf.debounce_task and not buf.debounce_task.done():
             buf.debounce_task.cancel()
             await asyncio.gather(buf.debounce_task, return_exceptions=True)
 
 
+@pytest.mark.asyncio
+async def test_late_media_resolution_cannot_overwrite_a_new_buffer_generation(
+    tb, monkeypatch,
+):
+    monkeypatch.setattr(tb, "DEBOUNCE_SEC", 0)
+    monkeypatch.setattr(tb, "MEDIA_WAIT_MAX", 0)
+    manager = _RecordingManager()
+    monkeypatch.setattr(tb, "_manager", manager)
+    session = SimpleNamespace(id="sess-generation")
+
+    old_token = await tb._register_media(_tg_message(), session)
+    buf = tb._get_buf(session.id)
+    assert await _until(lambda: buf.epoch is not old_token.epoch)
+
+    monkeypatch.setattr(tb, "DEBOUNCE_SEC", 30)
+    monkeypatch.setattr(tb, "MEDIA_WAIT_MAX", 30)
+    new_token = await tb._register_media(_tg_message(), session)
+    await tb._resolve_media(old_token, "OLD")
+
+    assert buf.entries[0][1:] == (None, new_token.reservation)
+    await tb._resolve_media(new_token, "NEW")
+    assert [(content, reservation) for _msg, content, reservation in buf.entries] == [
+        ("NEW", None),
+    ]
+    assert buf.pending_media == 0
+    if buf.debounce_task and not buf.debounce_task.done():
+        buf.debounce_task.cancel()
+        await asyncio.gather(buf.debounce_task, return_exceptions=True)
+    await tb._flush_batch(session.id, list(buf.entries))
+
+    assert len(manager.sent) == 2
+    assert all(any(value in content for value in ("OLD", "NEW")) for _sid, content in manager.sent)
+
+
 @pytest.mark.asyncio
 async def test_mirror_carries_important_flag_to_the_send(tb, monkeypatch):
     """Финальный текст агента в зеркале не должен ехать по косметической полосе."""
     tb.bot = SimpleNamespace()
     tb.config["mirrors"] = {"pilot": {"chat_id": -100999, "topic_id": 7}}
     calls = []
 
     async def fake_send(chat_id, text, thread_id=None, **kwargs):
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index 91d27c82b..a731b6275 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -17,16 +17,25 @@ from unittest.mock import AsyncMock
 
 import pytest
 from aiogram.types import LinkPreviewOptions
 from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
 from aiogram.methods import SendMessage
 from app.tg_bridge import stop_bridge as _real_stop_bridge
 
 
+def _test_png_bytes(color=(32, 64, 96)):
+    import io
+    from PIL import Image
+
+    image = io.BytesIO()
+    Image.new("RGB", (4, 4), color).save(image, format="PNG")
+    return image.getvalue()
+
+
 @pytest.mark.asyncio
 async def test_t2_artifact_text_disables_link_preview_at_the_bot_call(tb, monkeypatch):
     message = SimpleNamespace(message_id=77, chat=SimpleNamespace(id=-100123456))
     tb.bot = AsyncMock()
     tb.bot.send_message.return_value = message
     monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
 
     result = await tb._tg_send_safe(
@@ -77,16 +86,42 @@ async def test_t2_text_helper_threads_preview_disable_without_changing_document_
     monkeypatch.setattr(tb, "_tg_send_file_safe", send_file)
     file_result = await tb.send_file_to_tg(
         str(path), "fallback", "/scope", "publisher", as_document=True,
     )
     assert file_result["ok"] is True
     assert file_calls[0][1]["is_photo"] is False
 
 
+@pytest.mark.asyncio
+async def test_direct_photo_send_uses_document_for_invalid_geometry(
+    tb, tmp_path, monkeypatch,
+):
+    from PIL import Image
+
+    path = tmp_path / "panorama.png"
+    Image.new("RGB", (1_000, 40)).save(path)
+    tb.bot = object()
+    tb.config["topics"] = {"publisher": 42}