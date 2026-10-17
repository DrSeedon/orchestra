# Candidate cand-24

## ORIGIN commit d7532ac82a (2026-07-18): #tg-message-delivery: make Telegram topic delivery resilient
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 221ee14e0..c2c8fb3f1 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -9,17 +9,22 @@ import logging
 import os
 import re
 import time
 from datetime import datetime, timezone, timedelta
 from pathlib import Path
 
 import aiohttp
 from aiogram import Bot, Dispatcher, types, F
-from aiogram.exceptions import TelegramRetryAfter
+from aiogram.exceptions import (
+    TelegramBadRequest,
+    TelegramNetworkError,
+    TelegramRetryAfter,
+    TelegramServerError,
+)
 from aiogram.client.default import DefaultBotProperties
 from telegramify_markdown import convert as md_convert
 
 logger = logging.getLogger("tg-bridge")
 logger.setLevel(logging.DEBUG)
 if not logger.handlers:
     logger.addHandler(logging.StreamHandler())
 
@@ -419,71 +424,46 @@ async def _edit_tool_with_result(msg, chat_id: int, tool_text: str, result_heade
     pos = 0
     for p in parts:
         offsets.append(pos)
         pos += _utf16_len(p)
     for e in tool_ents:
         e.offset += offsets[2]
     for e in result_ents:
         e.offset += offsets[6]
-    try:
-        entities = [
-            MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offsets[2], length=_utf16_len(conv_tool)),
-            MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offsets[6], length=_utf16_len(conv_result)),
-        ] + tool_ents + result_ents
-        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id, entities=entities)
-    except Exception as e:
-        if "message is not modified" in str(e).lower():
-            return
-        try:
-            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
-        except Exception as e2:
-            if "message is not modified" not in str(e2).lower():
-                logger.warning(f"TG edit failed: {e2}")
+    entities = [
+        MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offsets[2], length=_utf16_len(conv_tool)),
+        MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offsets[6], length=_utf16_len(conv_result)),
+    ] + tool_ents + result_ents
+    await _tg_edit_message_safe(chat_id, msg.message_id, text, entities)
 
 
 async def _edit_expandable(msg, chat_id: int, header: str, body: str):
     from aiogram.types import MessageEntity
     from aiogram.enums import MessageEntityType
     conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
     text = f"{header}\n{conv_body}"
     offset = _utf16_len(header) + 1
     length = _utf16_len(conv_body)
-    try:
-        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
-        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id, entities=entities)
-    except Exception as e:
-        if "message is not modified" in str(e).lower():
-            return
-        try:
-            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
-        except Exception as e2:
-            if "message is not modified" not in str(e2).lower():
-                logger.warning(f"TG edit failed: {e2}")
+    entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
+    await _tg_edit_message_safe(chat_id, msg.message_id, text, entities)
 
 
 # Expandable blockquote wraps the body so long tool outputs are collapsed by default in TG.
 # Falls back to plain text if the Bot API version doesn't support EXPANDABLE_BLOCKQUOTE.
 async def _send_expandable(chat_id: int, thread_id: int, header: str, body: str):
     from aiogram.types import MessageEntity
     from aiogram.enums import MessageEntityType
     body = body.rstrip()
     conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
     text = f"{header}\n{conv_body}"
     offset = _utf16_len(header) + 1
     length = _utf16_len(conv_body)
-    try:
-        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
-        return await bot.send_message(chat_id, text, message_thread_id=thread_id, entities=entities)
-    except Exception:
-        try:
-            return await bot.send_message(chat_id, text, message_thread_id=thread_id)
-        except Exception as e:
-            logger.warning(f"TG send failed: {e}")
-            return None
+    entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
+    return await _tg_send_safe(chat_id, text, thread_id, entities=entities)
 
 
 TG_MSG_LIMIT = 4096
 
 
 def _split_message(text: str, limit: int = TG_MSG_LIMIT) -> list[str]:
     if _utf16_len(text) <= limit:
         return [text]
@@ -508,57 +488,188 @@ def _split_message(text: str, limit: int = TG_MSG_LIMIT) -> list[str]:
                 else:
                     hi = mid - 1
             cut = lo
         chunks.append(text[:cut])
         text = text[cut:].lstrip('\n')
     return chunks
 
 
-_flood_until: float = 0
-_last_send: float = 0
-# TG allows ~1 msg/sec per chat — enforce minimum interval to avoid flood errors
-_TG_MIN_INTERVAL = 1.0
+def _formatted_chunks(text: str) -> list[tuple[str, list | None]]:
+    """Convert first, then enforce Telegram's limit on the final payload."""
+    converted, entities = _md_entities(text)
+    if _utf16_len(converted) <= TG_MSG_LIMIT:
+        return [(converted, entities or None)]
+    return [(chunk, None) for chunk in _split_message(converted)]
 
 
-# Rate-limited send with flood control: waits out flood bans before retrying important messages.
-# Non-important messages are silently dropped after a flood to avoid queue buildup.
-async def _tg_send_safe(chat_id: int, text: str, thread_id: int = None,
-                         entities=None, important: bool = False):
-    global _flood_until, _last_send
-    now = asyncio.get_event_loop().time()
-    if _flood_until > now:
-        await asyncio.sleep(_flood_until - now + 0.1)
-        now = asyncio.get_event_loop().time()
-    gap = now - _last_send
-    if gap < _TG_MIN_INTERVAL:
-        await asyncio.sleep(_TG_MIN_INTERVAL - gap)
-    try:
-        result = await bot.send_message(chat_id, text, message_thread_id=thread_id,
-                                         parse_mode=None, entities=entities)
-        _last_send = asyncio.get_event_loop().time()
-        return result
-    except TelegramRetryAfter as e:
-        _flood_until = asyncio.get_event_loop().time() + e.retry_after
-        logger.warning(f"TG flood: pausing {e.retry_after}s")
-        if important:
-            await asyncio.sleep(e.retry_after + 0.5)
+_TG_GROUP_INTERVAL = 3.05
+_TG_PRIVATE_INTERVAL = 1.05
+_TG_IMPORTANT_ATTEMPTS = 3
+_TG_NETWORK_RETRY_DELAY = 1.0
+_TG_RETRY_AFTER_MARGIN = 0.25
+_TG_ENTITY_REJECTED = object()
+_tg_chat_locks: dict[int, asyncio.Lock] = {}
+_tg_flood_until: dict[int, float] = {}
+_tg_last_send: dict[int, float] = {}
+
+
+def _reset_tg_delivery_state() -> None:
+    _tg_chat_locks.clear()
+    _tg_flood_until.clear()
+    _tg_last_send.clear()
+
+
+def _tg_interval(chat_id: int) -> float:
+    return _TG_GROUP_INTERVAL if chat_id < 0 else _TG_PRIVATE_INTERVAL
+
+
+async def _tg_call_safe(chat_id: int, call, *, important: bool = False, label: str = "call"):
+    """Serialize one chat, retry important transient failures, shed low-value bursts."""
+    loop = asyncio.get_running_loop()
+    lock = _tg_chat_locks.setdefault(chat_id, asyncio.Lock())
+    interval = _tg_interval(chat_id)
+    now = loop.time()
+    if not important and (
+        lock.locked()
+        or _tg_flood_until.get(chat_id, 0) > now
+        or now - _tg_last_send.get(chat_id, 0) < interval
+    ):
+        logger.debug(f"TG {label} dropped before queue: chat={chat_id}")
+        return None
+
+    attempts = _TG_IMPORTANT_ATTEMPTS if important else 1
+    async with lock:
+        for attempt in range(1, attempts + 1):
+            now = loop.time()
+            flood_wait = _tg_flood_until.get(chat_id, 0) - now
+            interval_wait = interval - (now - _tg_last_send.get(chat_id, 0))
+            wait = max(0, flood_wait, interval_wait)
+            if wait:
+                await asyncio.sleep(wait)
+            # A timeout is ambiguous: Telegram may have accepted the request. Count
+            # every attempt, not only confirmed responses, before any retry.
+            _tg_last_send[chat_id] = loop.time()
             try:
-                result = await bot.send_message(chat_id, text, message_thread_id=thread_id,
-                                                parse_mode=None, entities=entities)
-                _last_send = asyncio.get_event_loop().time()
+                result = await call()
                 return result
-            except Exception as e2:
-                logger.warning(f"TG important message LOST after flood retry: {e2}; text[:80]={text[:80]!r}")
-        return None
-    except Exception as e:
-        logger.warning(f"TG send failed: {e}")
+            except TelegramRetryAfter as e:
+                _tg_flood_until[chat_id] = loop.time() + e.retry_after + _TG_RETRY_AFTER_MARGIN
+                logger.warning(f"TG {label} flood: retry in {e.retry_after}s")
+                if not important or attempt == attempts:
+                    break
+            except (TelegramNetworkError, TelegramServerError) as e:
+                if important and attempt < attempts:
+                    logger.warning(
+                        f"TG {label} ambiguous delivery, retry {attempt + 1}/{attempts}: {e}"
+                    )
+                    await asyncio.sleep(_TG_NETWORK_RETRY_DELAY * attempt)
+                    continue
+                if important:
+                    logger.warning(f"TG {label} LOST after {attempt} attempts: {e}")
+                else:
+                    logger.warning(f"TG {label} failed: {e}")
+                return None
+            except Exception as e:
+                if important:
+                    logger.warning(f"TG {label} LOST: {e}")
+                else:
+                    logger.warning(f"TG {label} failed: {e}")
+                return None
+
+        if important:
+            logger.warning(f"TG {label} LOST after {attempts} flood attempts")
         return None
 
 
+async def _tg_send_safe(chat_id: int, text: str, thread_id: int = None,
+                         entities=None, important: bool = False):
+    async def _send():
+        try:
+            return await bot.send_message(
+                chat_id, text, message_thread_id=thread_id,
+                parse_mode=None, entities=entities,
+            )
+        except TelegramBadRequest:
+            if not entities:
+                raise
+            return _TG_ENTITY_REJECTED
+
+    result = await _tg_call_safe(
+        chat_id, _send, important=important, label="send_message",
+    )
+    if result is not _TG_ENTITY_REJECTED:
+        return result
+
+    logger.warning("TG formatted send rejected; trying without entities")
+
+    async def _send_plain():
+        return await bot.send_message(
+            chat_id, text, message_thread_id=thread_id,
+            parse_mode=None, entities=None,
+        )
+
+    return await _tg_call_safe(
+        chat_id, _send_plain, important=important, label="send_message_plain",
+    )
+
+
+async def _tg_edit_message_safe(chat_id: int, message_id: int, text: str, entities=None):
+    async def _edit():
+        try:
+            return await bot.edit_message_text(
+                text, chat_id=chat_id, message_id=message_id,
+                entities=entities,
+            )
+        except TelegramBadRequest as e:
+            if "message is not modified" in str(e).lower():
+                return True
+            if not entities:
+                raise
+            return _TG_ENTITY_REJECTED
+
+    result = await _tg_call_safe(chat_id, _edit, label="edit_message")
+    if result is not _TG_ENTITY_REJECTED:
+        return result
+
+    async def _edit_plain():
+        try:
+            return await bot.edit_message_text(
+                text, chat_id=chat_id, message_id=message_id,
+            )
+        except TelegramBadRequest as e:
+            if "message is not modified" in str(e).lower():
+                return True
+            raise
+
+    return await _tg_call_safe(chat_id, _edit_plain, label="edit_message_plain")
+
+
+async def _tg_send_file_safe(
+    chat_id: int, path: str, caption: str | None, thread_id: int | None,
+    *, is_photo: bool, important: bool,
+):
+    from aiogram.types import FSInputFile
+
+    async def _send():
+        tg_file = FSInputFile(path, filename=Path(path).name)
+        if is_photo:
+            return await bot.send_photo(
+                chat_id, tg_file, caption=caption, message_thread_id=thread_id,
+            )
+        return await bot.send_document(
+            chat_id, tg_file, caption=caption, message_thread_id=thread_id,
+        )
+
+    label = "send_photo" if is_photo else "send_document"
+    return await _tg_call_safe(
+        chat_id, _send, important=important, label=label,
+    )
+
+
 _TG_TOOL_ICONS = {
     'Bash': '🖥', 'Read': '📖', 'Write': '✏️', 'Edit': '✏️',
     'Glob': '🔎', 'Grep': '🔎', 'WebSearch': '🌐', 'WebFetch': '🌐',
     'Agent': '🤖', 'ToolSearch': '🔍', 'AskUserQuestion': '❓',
 }
 _TG_MCP_ICONS = {
     'orchestra': '🎼', 'websearch': '🌐', 'kesha': '🦜',
     'yougile': '📋', 'serena': '🧠', 'mailru': '📧',
@@ -753,31 +864,27 @@ def _find_orch_for_scope(scope: str) -> str | None:
 
 def _find_thread_for_scope(scope: str) -> int | None:
     orch_name = _find_orch_for_scope(scope)
     if orch_name:
         return config["topics"].get(orch_name)
     return None
 
 
-async def _mirror_send_file(orch_name: str, tg_file, caption: str, is_photo: bool):
+async def _mirror_send_file(orch_name: str, path: str, caption: str, is_photo: bool):
     mirror = config.get("mirrors", {}).get(orch_name)
     if not mirror or not bot:
         return
     chat_id = mirror.get("chat_id")
     topic_id = mirror.get("topic_id")
     if not chat_id:
         return
-    try:
-        if is_photo:
-            await bot.send_photo(chat_id, tg_file, caption=caption, message_thread_id=topic_id)
-        else:
-            await bot.send_document(chat_id, tg_file, caption=caption, message_thread_id=topic_id)
-    except Exception as e:
-        logger.warning(f"Mirror file send failed for {orch_name}: {e}")
+    await _tg_send_file_safe(
+        chat_id, path, caption, topic_id, is_photo=is_photo, important=True,
+    )
 
 
 async def send_file_to_tg(path: str, caption: str, scope: str, sender: str, as_document: bool = False) -> dict:
     if not bot or not config["group_id"]:
         return {"error": "TG bridge not active"}
     from pathlib import Path as P
     fp = P(path)
     if not fp.exists():
@@ -795,46 +902,27 @@ async def send_file_to_tg(path: str, caption: str, scope: str, sender: str, as_d
     else:
         orch_name = _find_orch_for_scope(scope)
         thread_id = topics.get(orch_name) if orch_name else None
     logger.info(f"send_file: path={path} size={file_size} scope={scope!r} sender={sender!r} orch={orch_name!r} group_id={config['group_id']} thread_id={thread_id}")
     if not thread_id:
         return {"error": f"no TG topic for scope: {scope}"}
     label = f"📎 {sender}: {caption}" if caption else f"📎 {sender}: {fp.name}"
     label = label[:1024]
-    try:
-        from aiogram.types import FSInputFile
-        tg_file = FSInputFile(path, filename=fp.name)
-        is_photo = not as_document and fp.suffix.lower() in _IMAGE_EXTS
-        if is_photo:
-            msg = await bot.send_photo(config["group_id"], tg_file, caption=label, message_thread_id=thread_id)
-        else:
-            msg = await bot.send_document(config["group_id"], tg_file, caption=label, message_thread_id=thread_id)
-        logger.info(f"send_file: delivered msg_id={msg.message_id} chat_id={msg.chat.id} thread={getattr(msg, 'message_thread_id', None)}")
-        if orch_name:
-            mirror_file = FSInputFile(path, filename=fp.name)
-            await _mirror_send_file(orch_name, mirror_file, label, is_photo)
-        return {"ok": True, "message_id": msg.message_id, "chat_id": msg.chat.id}
-    except TelegramRetryAfter as e:
-        logger.warning(f"send_file flood: retry after {e.retry_after}s")
-        await asyncio.sleep(e.retry_after + 0.5)
-        try:
-            tg_file2 = FSInputFile(path, filename=fp.name)
-            if is_photo:
-                msg2 = await bot.send_photo(config["group_id"], tg_file2, caption=label, message_thread_id=thread_id)
-            else:
-                msg2 = await bot.send_document(config["group_id"], tg_file2, caption=label, message_thread_id=thread_id)
-            logger.info(f"send_file retry: delivered msg_id={msg2.message_id} chat_id={msg2.chat.id}")
-            return {"ok": True, "message_id": msg2.message_id, "chat_id": msg2.chat.id}
-        except Exception as e2:
-            logger.error(f"send_file retry failed: {e2}")
-            return {"error": f"Send failed after flood retry: {e2}"}
-    except Exception as e:
-        logger.error(f"send_file exception: type={type(e).__name__} err={e}")
-        return {"error": str(e)}
+    is_photo = not as_document and fp.suffix.lower() in _IMAGE_EXTS
+    msg = await _tg_send_file_safe(
+        config["group_id"], path, label, thread_id,
+        is_photo=is_photo, important=True,
+    )
+    if msg is None:
+        return {"error": "TG file delivery failed; see tg-bridge logs"}
+    logger.info(f"send_file: delivered msg_id={msg.message_id} chat_id={msg.chat.id} thread={getattr(msg, 'message_thread_id', None)}")
+    if orch_name:
+        await _mirror_send_file(orch_name, path, label, is_photo)
+    return {"ok": True, "message_id": msg.message_id, "chat_id": msg.chat.id}
 
 
 _topic_status = {}
 
 
 def _any_running_in_scope(scope: str) -> bool:
     if not _manager or not scope:
         return False
@@ -900,55 +988,58 @@ async def _sync_all_topic_statuses():
 _ICON_RUNNING = "5312016608254762256"
 _ICON_IDLE = "5350392020785437399"
 
 
 # Deduplicated topic icon updates with flood-control retry (like _tg_send_safe)
 async def _update_topic_status(orch_name: str, is_running: bool):
     if _topic_status.get(orch_name) == is_running:
         return
-    _topic_status[orch_name] = is_running
     short = (config.get("topic_names") or {}).get(orch_name) or _short_name(orch_name)
     icon_id = _ICON_RUNNING if is_running else _ICON_IDLE
 
     async def _do_edit(chat_id, thread_id):
-        for attempt in range(3):
+        async def _edit():
             try:
-                await bot.edit_forum_topic(chat_id=chat_id, message_thread_id=thread_id,
-                                           name=short, icon_custom_emoji_id=icon_id)
-                return
-            except TelegramRetryAfter as e:
-                await asyncio.sleep(e.retry_after + 0.5)
-            except Exception as e:
-                if "TOPIC_NOT_MODIFIED" in str(e):
-                    return
-                logger.debug(f"Topic icon update failed: {e}")
-                return
+                return await bot.edit_forum_topic(
+                    chat_id=chat_id, message_thread_id=thread_id,
+                    name=short, icon_custom_emoji_id=icon_id,
+                )
+            except TelegramBadRequest as e:
+                if "TOPIC_NOT_MODIFIED" in str(e).upper():
+                    return True
+                raise
+
+        return await _tg_call_safe(
+            chat_id, _edit, label="topic_status",
+        )
 
     thread_id = config["topics"].get(orch_name)
+    primary_updated = False
     if thread_id and bot:
-        await _do_edit(config["group_id"], thread_id)
+        primary_updated = await _do_edit(config["group_id"], thread_id) is not None
     mirror = config.get("mirrors", {}).get(orch_name)
     if mirror and mirror.get("chat_id") and mirror.get("topic_id") and bot:
         await _do_edit(mirror["chat_id"], mirror["topic_id"])
+    if primary_updated:
+        _topic_status[orch_name] = is_running
 
 
-async def _mirror_send(orch_name: str, text: str, entities=None):
+async def _mirror_send(orch_name: str, text: str, entities=None, *, important: bool = False):
     mirrors = config.get("mirrors", {})
     mirror = mirrors.get(orch_name)
     if not mirror or not bot:
         return
     chat_id = mirror.get("chat_id")
     topic_id = mirror.get("topic_id")
     if not chat_id:
         return
-    try:
-        await bot.send_message(chat_id, text, message_thread_id=topic_id, entities=entities)
-    except Exception as e:
-        logger.warning(f"Mirror send failed for {orch_name}: {e}")
+    return await _tg_send_safe(
+        chat_id, text, topic_id, entities=entities, important=important,
+    )
 
 
 async def ensure_topics():
     if not bot or not config["group_id"] or not _manager:
         return
     from app.db import get_all_sessions
     orchs = [s for s in get_all_sessions() if s.get("tg_topic") or s.get("role", "worker") in ("orchestrator", "sub-orchestrator")]
     if not orchs:
@@ -1013,18 +1104,19 @@ async def _send_png_to_tg(png: bytes, chat_id: int, thread_id: int, label: str)
     """Send PNG bytes as a photo to TG. Temp file cleaned up after send."""
     import uuid, tempfile
     if not png or not bot:
         return
     tmp = os.path.join(tempfile.gettempdir(), f"diff-{uuid.uuid4().hex}.png")
     with open(tmp, "wb") as f:
         f.write(png)
     try:
-        from aiogram.types import FSInputFile
-        await bot.send_photo(chat_id, FSInputFile(tmp), message_thread_id=thread_id)
+        await _tg_send_file_safe(
+            chat_id, tmp, None, thread_id, is_photo=True, important=False,
+        )
     finally:
         try:
             os.unlink(tmp)
         except Exception as e:
             logger.warning(f"tmp diff image cleanup failed ({tmp}): {e}")
 
 
 async def _send_diff_image(tool_name: str, raw_content: str, chat_id: int, thread_id: int) -> bool:
@@ -1187,49 +1279,49 @@ async def stream_logs(orch_name: str, thread_id: int):
                         await _update_topic_status(orch_name, True)
                     if t == "user_message":
                         c = re.sub(r'^\[\d{2}:\d{2}\] ', '', c)
                         img_match = re.search(r'(/\S+\.(?:png|jpg|jpeg|gif|webp))', c, re.IGNORECASE)
                         if img_match and Path(img_match.group(1)).is_file():
                             img_path = img_match.group(1)
                             caption = c.replace(img_path, '').strip()[:1024] or None
                             try:
-                                from aiogram.types import FSInputFile
-                                tg_file = FSInputFile(img_path)
-                                await bot.send_photo(config["group_id"], tg_file, caption=caption, message_thread_id=thread_id)
+                                await _tg_send_file_safe(
+                                    config["group_id"], img_path, caption, thread_id,
+                                    is_photo=True, important=True,
+                                )
                                 mirror = config.get("mirrors", {}).get(orch_name)
                                 if mirror and mirror.get("chat_id"):
-                                    mirror_file = FSInputFile(img_path)
-                                    await bot.send_photo(mirror["chat_id"], mirror_file, caption=caption, message_thread_id=mirror.get("topic_id"))
+                                    await _tg_send_file_safe(
+                                        mirror["chat_id"], img_path, caption,
+                                        mirror.get("topic_id"), is_photo=True,
+                                        important=True,
+                                    )
                             except Exception as e:
                                 logger.warning(f"TG send photo failed: {e}")
                             continue
                         if c.startswith("[from:"):
                             prefix = c.split("]")[0] + "]"
                             body = c[len(prefix):].strip()
                             text = f"📨 {prefix}\n{body}"
                         else:
                             text = f"👤\n{c}" if c.startswith("> ") else f"👤 {c}"
                     elif t == "text":
                         # @mention пользователя — только в речи агента (text), чтобы уведы
                         # приходили на обращения к тебе, а не на внутрянку (📨 [from:]).
                         head = f"💬 {TG_USER_MENTION}" if TG_USER_MENTION else "💬"
                         raw_text = f"{head}\n{c}"
-                        for chunk in _split_message(raw_text):
-                            try:
-                                converted, ents = md_convert(chunk)
-                                from aiogram.types import MessageEntity as AioEntity
-                                aio_ents = [AioEntity(**e.to_dict()) for e in ents] if ents else None
-                                await _tg_send_safe(config["group_id"], converted, thread_id,
-                                                    entities=aio_ents, important=True)
-                                await _mirror_send(orch_name, converted, entities=aio_ents)
-                            except Exception as e:
-                                logger.warning(f"text md_convert/send failed, fallback to plain: {e}; chunk[:80]={chunk[:80]!r}")
-                                await _tg_send_safe(config["group_id"], chunk, thread_id, important=True)
-                                await _mirror_send(orch_name, chunk)
+                        for converted, aio_ents in _formatted_chunks(raw_text):
+                            await _tg_send_safe(
+                                config["group_id"], converted, thread_id,
+                                entities=aio_ents, important=True,
+                            )
+                            await _mirror_send(
+                                orch_name, converted, entities=aio_ents, important=True,
+                            )
                         continue
                     elif t == "tool":
                         tool_name = c.split(":")[0].strip() if ":" in c else "tool"
                         tool_body = c[len(tool_name)+1:].strip()[:1200] if ":" in c else c[:1200]
                         icon = _tg_tool_icon(tool_name)
                         short = _tg_tool_short(tool_name)
                         # spawn_worker: show name + model + role in header
                         if "spawn_worker" in tool_name:
@@ -1259,22 +1351,21 @@ async def stream_logs(orch_name: str, thread_id: int):
                         if not _diff_sent and "send_message" in tool_name:
                             try:
                                 import json as _json
                                 colon_idx = c.index(":")
                                 sm_params = _json.loads(c[colon_idx + 1:].strip())
                                 sm_to = sm_params.get("to", "?")
                                 sm_msg = sm_params.get("message", "")
                                 sm_md = f"✉️ **→ {sm_to}**\n\n{sm_msg}"
-                                converted, entities = md_convert(sm_md)
-                                from aiogram.types import MessageEntity as AioEntity
-                                aio_ents = [AioEntity(**e.to_dict()) for e in entities] if entities else None
-                                for chunk in _split_message(converted):
-                                    await _tg_send_safe(config["group_id"], chunk, thread_id, entities=aio_ents, important=True)
-                                    aio_ents = None
+                                for chunk, aio_ents in _formatted_chunks(sm_md):
+                                    await _tg_send_safe(
+                                        config["group_id"], chunk, thread_id,
+                                        entities=aio_ents, important=True,
+                                    )
                                 _last_diff_sent = True
                             except Exception as _e:
                                 logger.debug(f"send_message pretty format failed: {_e}")
                                 _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
                         elif not _diff_sent:
                             _skip_expandable = (tool_name in ("Read", "Grep", "Bash", "Glob") and _result_images_enabled())
                             if not _skip_expandable:
                                 _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
@@ -1314,19 +1405,21 @@ async def stream_logs(orch_name: str, thread_id: int):
                         # Read tool returned an image — send original file instead of base64 spam
                         if _last_tool_name == "Read" and ("'type': 'image'" in c or '"type": "image"' in c or "'type':'image'" in c):
                             try:
                                 import json as _json
                                 _colon = _last_tool_raw.index(":")
                                 _read_params = _json.loads(_last_tool_raw[_colon + 1:].strip())
                                 _img_path = _read_params.get("file_path", "")
                                 if _img_path and Path(_img_path).is_file():
-                                    from aiogram.types import FSInputFile
-                                    await bot.send_photo(config["group_id"], FSInputFile(_img_path),
-                                                         message_thread_id=thread_id, caption=f"📷 {Path(_img_path).name}")
+                                    await _tg_send_file_safe(
+                                        config["group_id"], _img_path,
+                                        f"📷 {Path(_img_path).name}", thread_id,
+                                        is_photo=True, important=False,
+                                    )
                                     if _last_tool_msg:
                                         _last_tool_msg = None
                                         _last_tool_text = ""
                                     _last_tool_name = ""
                                     _last_tool_raw = ""
                                     continue
                             except Exception as _e:
                                 logger.debug(f"Read image send failed, falling back: {_e}")
@@ -1371,28 +1464,25 @@ async def stream_logs(orch_name: str, thread_id: int):
                         # Content: "desc | status=X | summary". Show desc + ok/fail.
                         _parts = [p.strip() for p in c.split("|")]
                         _desc = _parts[0] if _parts else ""
                         _ok = "status=failed" not in c
                         text = f"{'✅' if _ok else '❌'} Sub-agent {'done' if _ok else 'failed'}: {_desc}"
                     else:
                         continue
                     is_important = t in ("text", "error", "user_message")
-                    for chunk in _split_message(text):
-                        try:
-                            converted, entities = md_convert(chunk)
-                            from aiogram.types import MessageEntity as AioEntity
-                            aio_ents = [AioEntity(**e.to_dict()) for e in entities] if entities else None
-                            await _tg_send_safe(config["group_id"], converted, thread_id,
-                                                entities=aio_ents, important=is_important)
-                            await _mirror_send(orch_name, converted, entities=aio_ents)
-                        except Exception:
-                            await _tg_send_safe(config["group_id"], chunk, thread_id,
-                                                important=is_important)
-                            await _mirror_send(orch_name, chunk)
+                    for converted, aio_ents in _formatted_chunks(text):
+                        await _tg_send_safe(
+                            config["group_id"], converted, thread_id,
+                            entities=aio_ents, important=is_important,
+                        )
+                        await _mirror_send(
+                            orch_name, converted, entities=aio_ents,
+                            important=is_important,
+                        )
             except Exception as e:
                 logger.error(f"Stream error for {orch_name}: {e}")
                 _idle_ticks = 0
             # Poll faster when active, slow down when idle to save CPU on long-running idle sessions
             await asyncio.sleep(2 if _idle_ticks < 3 else 5)
     finally:
         _poll_conn.close()
 
@@ -1544,16 +1634,17 @@ async def topic_sync_loop():
         except Exception as e:
             logger.error(f"Topic sync error: {e}")
 
 
 async def start_bridge(manager):
     global bot, _manager, DEEPGRAM_API_KEY
     from dotenv import load_dotenv
     load_dotenv()
+    _reset_tg_delivery_state()
 
     DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
 
     # Wire callbacks regardless of bridge state: handlers no-op while _manager is
     # None, and remove_topics_for_orchs has its own bridge-inactive guard — this
     # preserves the legacy always-callable semantics without session/manager
     # importing tg_bridge.
     from app import session as _session_mod
@@ -1666,16 +1757,17 @@ async def stop_bridge():
     for t in _tasks:
         t.cancel()
     _tasks.clear()
     if bot:
         await bot.session.close()
     # drop stale refs — a handler racing past the unhook must see inactive state
     bot = None
     _manager = None
+    _reset_tg_delivery_state()
 
 
 if __name__ == "__main__":
     import sys
     async def _main():
         from app.manager import SessionManager
         m = SessionManager()
         from app.db import init_db
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index 57347cfb9..15b9814cf 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -3,33 +3,39 @@
 Покрытие:
 - ``_short_name`` — нормализация имени оркестратора в имя топика.
 - ``_pick_unique_topic_name`` — выбор свободного имени с инкрементом ``-2``, ``-3`` при коллизиях.
 - ``remove_topics_for_orchs`` — удаление топиков из TG и записей из ``config["topics"]`` /
   ``config["topic_names"]``. Mirrors не трогаем. Ошибки Bot API не должны валить процесс.
 """
 
 import asyncio
+import time
 from unittest.mock import AsyncMock
 
 import pytest
+from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
+from aiogram.methods import SendMessage
 
 
 @pytest.fixture
 def tb(tmp_path, monkeypatch):
     """Изолированный модуль tg_bridge: путь к конфигу — во временной папке,
     состояние модуля сбрасываем перед каждым тестом."""
     cfg_path = tmp_path / "tg_bridge.json"
     monkeypatch.setattr("app.tg_bridge.CONFIG_PATH", cfg_path)
     from app import tg_bridge
 
     tg_bridge.config = {"group_id": -100123456, "topics": {}, "token": "test"}
     tg_bridge._topic_status = {}
     tg_bridge.bot = None
     tg_bridge._pil_available = None
+    monkeypatch.setattr(tg_bridge, "_tg_chat_locks", {}, raising=False)
+    monkeypatch.setattr(tg_bridge, "_tg_flood_until", {}, raising=False)
+    monkeypatch.setattr(tg_bridge, "_tg_last_send", {}, raising=False)
     return tg_bridge
 
 
 @pytest.mark.asyncio
 async def test_polling_does_not_override_uvicorn_signal_handlers(tb):
     dispatcher = AsyncMock()
     dispatcher.start_polling.side_effect = asyncio.CancelledError
     bot = object()
@@ -477,8 +483,266 @@ class TestSendFileRouting:
         """Ни у sender, ни у скоупа нет топика → error."""
         tb.bot = AsyncMock()
         tb.config["topics"] = {}
         monkeypatch.setattr(tb, "_find_orch_for_scope", lambda s: None)
 
         result = await tb.send_file_to_tg(file_tmp, "cap", "/s", "ghost")
 
         assert "error" in result
+
+
+# ── reliable outbound delivery ─────────────────────────────────────────────
+
+
+class TestFormattedChunks:
+    def test_splits_after_markdown_expands_table(self, tb):
+        raw = (
+            f"| {'A' * 100} | B |\n"
+            "| --- | --- |\n"
+            + "\n".join("| x | y |" for _ in range(40))
+        )
+
+        converted, _ = tb.md_convert(raw)
+        chunks = tb._formatted_chunks(raw)
+
+        assert tb._utf16_len(raw) < tb.TG_MSG_LIMIT
+        assert tb._utf16_len(converted) > tb.TG_MSG_LIMIT
+        assert len(chunks) > 1
+        assert all(tb._utf16_len(text) <= tb.TG_MSG_LIMIT for text, _ in chunks)
+        assert all(entities is None for _, entities in chunks)
+
+    def test_keeps_entities_for_single_chunk(self, tb):
+        chunks = tb._formatted_chunks("hello **world**")
+
+        assert len(chunks) == 1
+        text, entities = chunks[0]
+        assert text == "hello world"
+        assert entities
+
+
+class TestTgSendSafe:
+    @pytest.mark.asyncio
+    async def test_serializes_concurrent_group_sends(self, tb, monkeypatch):
+        sent_at = []
+
+        async def send_message(*args, **kwargs):
+            sent_at.append(time.monotonic())
+            return object()
+
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = send_message
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.02)
+
+        await asyncio.gather(*(
+            tb._tg_send_safe(-100, f"m{i}", 42, important=True)
+            for i in range(3)
+        ))
+
+        assert len(sent_at) == 3
+        assert sent_at[1] - sent_at[0] >= 0.018
+        assert sent_at[2] - sent_at[1] >= 0.018
+
+    @pytest.mark.asyncio
+    async def test_different_chats_do_not_share_lock(self, tb, monkeypatch):
+        both_started = asyncio.Event()
+        started = []
+
+        async def send_message(chat_id, *args, **kwargs):
+            started.append(chat_id)
+            if len(started) == 2:
+                both_started.set()
+            await asyncio.wait_for(both_started.wait(), timeout=0.1)
+            return object()
+
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = send_message
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
+
+        await asyncio.gather(
+            tb._tg_send_safe(-100, "a", 1, important=True),
+            tb._tg_send_safe(-200, "b", 2, important=True),
+        )
+
+        assert set(started) == {-100, -200}
+
+    @pytest.mark.asyncio
+    async def test_retries_rate_limit_with_same_thread(self, tb, monkeypatch):
+        method = SendMessage(chat_id=-100, text="hello")
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = [
+            TelegramRetryAfter(method=method, message="flood", retry_after=0),
+            object(),
+        ]
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
+        monkeypatch.setattr(tb, "_TG_RETRY_AFTER_MARGIN", 0)
+
+        result = await tb._tg_send_safe(-100, "hello", 77, important=True)
+
+        assert result is not None
+        assert tb.bot.send_message.await_count == 2
+        assert [c.kwargs["message_thread_id"] for c in tb.bot.send_message.await_args_list] == [77, 77]
+
+    @pytest.mark.asyncio
+    async def test_retries_ambiguous_network_error(self, tb, monkeypatch, caplog):
+        method = SendMessage(chat_id=-100, text="hello")
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = [
+            TelegramNetworkError(method=method, message="timeout"),
+            object(),
+        ]
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
+        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)
+
+        result = await tb._tg_send_safe(-100, "hello", 77, important=True)
+
+        assert result is not None
+        assert tb.bot.send_message.await_count == 2
+        assert "ambiguous delivery" in caplog.text
+
+    @pytest.mark.asyncio
+    async def test_network_retry_counts_failed_request_against_interval(self, tb, monkeypatch):
+        method = SendMessage(chat_id=-100, text="hello")
+        started = []
+
+        async def send_message(*args, **kwargs):
+            started.append(asyncio.get_running_loop().time())
+            if len(started) == 1:
+                raise TelegramNetworkError(method=method, message="timeout")
+            return object()
+
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = send_message
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.03)
+        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)
+
+        result = await tb._tg_send_safe(-100, "hello", 77, important=True)
+
+        assert result is not None
+        assert started[1] - started[0] >= 0.025
+
+    @pytest.mark.asyncio
+    async def test_retries_bad_entities_as_plain_text(self, tb, monkeypatch):
+        method = SendMessage(chat_id=-100, text="local path")
+
+        async def send_message(*args, **kwargs):
+            if kwargs.get("entities"):
+                raise TelegramBadRequest(method=method, message="entity URL is invalid")
+            return object()
+
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = send_message
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
+
+        result = await tb._tg_send_safe(-100, "local path", 77, entities=[object()], important=True)
+
+        assert result is not None
+        assert tb.bot.send_message.await_count == 2
+        assert tb.bot.send_message.await_args_list[1].kwargs["entities"] is None
+
+    @pytest.mark.asyncio
+    async def test_plain_entity_fallback_uses_a_new_rate_slot(self, tb, monkeypatch):
+        method = SendMessage(chat_id=-100, text="local path")
+        started = []
+
+        async def send_message(*args, **kwargs):
+            started.append(asyncio.get_running_loop().time())
+            if kwargs.get("entities"):
+                raise TelegramBadRequest(method=method, message="entity URL is invalid")
+            return object()
+
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = send_message
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.03)
+
+        result = await tb._tg_send_safe(
+            -100, "local path", 77, entities=[object()], important=True,
+        )
+
+        assert result is not None
+        assert started[1] - started[0] >= 0.025
+
+    @pytest.mark.asyncio
+    async def test_logs_lost_after_final_network_failure(self, tb, monkeypatch, caplog):
+        method = SendMessage(chat_id=-100, text="hello")
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = TelegramNetworkError(method=method, message="timeout")
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
+        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)
+
+        result = await tb._tg_send_safe(-100, "hello", 77, important=True)
+
+        assert result is None
+        assert tb.bot.send_message.await_count == tb._TG_IMPORTANT_ATTEMPTS
+        assert "LOST" in caplog.text
+
+    @pytest.mark.asyncio
+    async def test_drops_nonimportant_call_while_chat_busy(self, tb):
+        tb.bot = AsyncMock()
+        lock = asyncio.Lock()
+        await lock.acquire()
+        tb._tg_chat_locks[-100] = lock
+        try:
+            result = await tb._tg_send_safe(-100, "tool", 77, important=False)
+        finally:
+            lock.release()
+
+        assert result is None
+        tb.bot.send_message.assert_not_awaited()
+
+    @pytest.mark.asyncio
+    async def test_drops_nonimportant_call_inside_interval(self, tb, monkeypatch):
+        tb.bot = AsyncMock()
+        tb.bot.send_message.return_value = object()
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 10)
+
+        first = await tb._tg_send_safe(-100, "tool-1", 77)
+        second = await tb._tg_send_safe(-100, "tool-2", 77)
+
+        assert first is not None
+        assert second is None
+        tb.bot.send_message.assert_awaited_once()
+
+    @pytest.mark.asyncio
+    async def test_drops_edit_before_lock_wait(self, tb):
+        tb.bot = AsyncMock()
+        lock = asyncio.Lock()
+        await lock.acquire()
+        tb._tg_chat_locks[-100] = lock
+        try:
+            result = await tb._tg_edit_message_safe(-100, 5, "updated", [object()])
+        finally:
+            lock.release()
+
+        assert result is None
+        tb.bot.edit_message_text.assert_not_awaited()
+
+
+class TestSendFileRetry:
+    @pytest.mark.asyncio
+    async def test_recreates_files_for_primary_and_mirror_retry(self, tb, tmp_path, monkeypatch):
+        path = tmp_path / "report.txt"
+        path.write_text("hello")
+        method = SendMessage(chat_id=-100, text="file placeholder")
+        primary = type("M", (), {
+            "message_id": 5,
+            "chat": type("C", (), {"id": -100123456})(),
+            "message_thread_id": 555,
+        })()
+        tb.bot = AsyncMock()
+        tb.bot.send_document.side_effect = [
+            TelegramNetworkError(method=method, message="timeout"),
+            primary,
+            TelegramNetworkError(method=method, message="timeout"),
+            object(),
+        ]
+        tb.config["topics"] = {"worker-a": 555}
+        tb.config["mirrors"] = {"worker-a": {"chat_id": -200, "topic_id": 666}}
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
+        monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)
+
+        result = await tb.send_file_to_tg(str(path), "cap", "/s", "worker-a", as_document=True)
+
+        assert result["ok"] is True
+        assert tb.bot.send_document.await_count == 4
+        files = [call.args[1] for call in tb.bot.send_document.await_args_list]
+        assert len({id(file) for file in files}) == 4
+        assert [call.kwargs["message_thread_id"] for call in tb.bot.send_document.await_args_list] == [555, 555, 666, 666]


## LATER FIX 74639962d1 (5.1 days later): fix: queue Telegram outbound bursts
lines of origin it changed/deleted: 53
(code only, capped 400 lines)

fix: queue Telegram outbound bursts


diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 28a97f97e..2d3320710 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -437,28 +437,28 @@ async def _edit_tool_with_result(msg, chat_id: int, tool_text: str, result_heade
     for e in tool_ents:
         e.offset += offsets[2]
     for e in result_ents:
         e.offset += offsets[6]
     entities = [
         MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offsets[2], length=_utf16_len(conv_tool)),
         MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offsets[6], length=_utf16_len(conv_result)),
     ] + tool_ents + result_ents
-    await _tg_edit_message_safe(chat_id, msg.message_id, text, entities)
+    await _tg_edit_message_safe(chat_id, msg, text, entities)
 
 
 async def _edit_expandable(msg, chat_id: int, header: str, body: str):
     from aiogram.types import MessageEntity
     from aiogram.enums import MessageEntityType
     conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
     text = f"{header}\n{conv_body}"
     offset = _utf16_len(header) + 1
     length = _utf16_len(conv_body)
     entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
-    await _tg_edit_message_safe(chat_id, msg.message_id, text, entities)
+    await _tg_edit_message_safe(chat_id, msg, text, entities)
 
 
 # Expandable blockquote wraps the body so long tool outputs are collapsed by default in TG.
 # Falls back to plain text if the Bot API version doesn't support EXPANDABLE_BLOCKQUOTE.
 async def _send_expandable(chat_id: int, thread_id: int, header: str, body: str, *, important: bool = False):
     from aiogram.types import MessageEntity
     from aiogram.enums import MessageEntityType
     body = body.rstrip()
@@ -511,87 +511,167 @@ def _formatted_chunks(text: str) -> list[tuple[str, list | None]]:
 
 
 _TG_GROUP_INTERVAL = 3.05
 _TG_PRIVATE_INTERVAL = 1.05
 _TG_IMPORTANT_ATTEMPTS = 3
 _TG_NETWORK_RETRY_DELAY = 1.0
 _TG_RETRY_AFTER_MARGIN = 0.25
 _TG_ENTITY_REJECTED = object()
-_tg_chat_locks: dict[int, asyncio.Lock] = {}
+_tg_call_queues: dict[int, asyncio.PriorityQueue] = {}
+_tg_dispatch_tasks: dict[int, asyncio.Task] = {}
+_tg_queue_loops: dict[int, asyncio.AbstractEventLoop] = {}
+_tg_result_tasks: set[asyncio.Task] = set()
 _tg_flood_until: dict[int, float] = {}
 _tg_last_send: dict[int, float] = {}
+_tg_call_sequence = 0
+
+
+def _clear_tg_chat(chat_id: int) -> None:
+    task = _tg_dispatch_tasks.pop(chat_id, None)
+    if task and not task.done():
+        try:
+            task.cancel()
+        except RuntimeError:
+            pass
+    queue = _tg_call_queues.pop(chat_id, None)
+    if queue:
+        while not queue.empty():
+            try:
+                _, _, _, _, _, future = queue.get_nowait()
+            except asyncio.QueueEmpty:
+                break
+            if not future.done():
+                future.cancel()
+            queue.task_done()
+    _tg_queue_loops.pop(chat_id, None)
+    _tg_flood_until.pop(chat_id, None)
+    _tg_last_send.pop(chat_id, None)
 
 
 def _reset_tg_delivery_state() -> None:
-    _tg_chat_locks.clear()
-    _tg_flood_until.clear()
-    _tg_last_send.clear()
+    global _tg_call_sequence
+    for task in list(_tg_result_tasks):
+        task.cancel()
+    _tg_result_tasks.clear()
+    for chat_id in list(_tg_call_queues):
+        _clear_tg_chat(chat_id)
+    _tg_call_sequence = 0
 
 
 def _tg_interval(chat_id: int) -> float:
     return _TG_GROUP_INTERVAL if chat_id < 0 else _TG_PRIVATE_INTERVAL
 
 
-async def _tg_call_safe(chat_id: int, call, *, important: bool = False, label: str = "call"):
-    """Serialize one chat, retry important transient failures, shed low-value bursts."""
-    loop = asyncio.get_running_loop()
-    lock = _tg_chat_locks.setdefault(chat_id, asyncio.Lock())
-    interval = _tg_interval(chat_id)
-    now = loop.time()
-    if not important and (
-        lock.locked()
-        or _tg_flood_until.get(chat_id, 0) > now
-        or now - _tg_last_send.get(chat_id, 0) < interval
-    ):
-        logger.debug(f"TG {label} dropped before queue: chat={chat_id}")
-        return None
+def _track_tg_result(coro) -> asyncio.Task:
+    task = asyncio.create_task(coro)
+    _tg_result_tasks.add(task)
+    task.add_done_callback(_tg_result_tasks.discard)
+    return task
+
+
+def _tg_rate_wait(chat_id: int, now: float) -> float:
+    return max(
+        0,
+        _tg_flood_until.get(chat_id, 0) - now,
+        _tg_interval(chat_id) - (now - _tg_last_send.get(chat_id, 0)),
+    )
+
 
+async def _tg_run_call(chat_id: int, call, important: bool, label: str):
+    loop = asyncio.get_running_loop()
     attempts = _TG_IMPORTANT_ATTEMPTS if important else 1
-    async with lock:
-        for attempt in range(1, attempts + 1):
-            now = loop.time()
-            flood_wait = _tg_flood_until.get(chat_id, 0) - now
-            interval_wait = interval - (now - _tg_last_send.get(chat_id, 0))
-            wait = max(0, flood_wait, interval_wait)
+    for attempt in range(1, attempts + 1):
+        wait = _tg_rate_wait(chat_id, loop.time())
+        if wait:
+            await asyncio.sleep(wait)
+        _tg_last_send[chat_id] = loop.time()
+        try:
+            return await call()
+        except TelegramRetryAfter as e:
+            _tg_flood_until[chat_id] = loop.time() + e.retry_after + _TG_RETRY_AFTER_MARGIN
+            logger.warning(f"TG {label} flood: retry in {e.retry_after}s")
+            if not important or attempt == attempts:
+                break
+        except (TelegramNetworkError, TelegramServerError) as e:
+            if important and attempt < attempts:
+                logger.warning(
+                    f"TG {label} ambiguous delivery, retry {attempt + 1}/{attempts}: {e}"
+                )
+                await asyncio.sleep(_TG_NETWORK_RETRY_DELAY * attempt)
+                continue
+            if important:
+                logger.warning(f"TG {label} LOST after {attempt} attempts: {e}")
+            else:
+                logger.warning(f"TG {label} failed: {e}")
+            return None
+        except Exception as e:
+            if important:
+                logger.warning(f"TG {label} LOST: {e}")
+            else:
+                logger.warning(f"TG {label} failed: {e}")
+            return None
+
+    if important:
+        logger.warning(f"TG {label} LOST after {attempts} flood attempts")
+    return None
+
+
+async def _tg_dispatch_chat(chat_id: int) -> None:
+    queue = _tg_call_queues[chat_id]
+    try:
+        while True:
+            item = await queue.get()
+            _, _, call, important, label, future = item
+            if future.cancelled():
+                queue.task_done()
+                continue
+            wait = _tg_rate_wait(chat_id, asyncio.get_running_loop().time())
             if wait:
+                queue.put_nowait(item)
+                queue.task_done()
                 await asyncio.sleep(wait)
-            # A timeout is ambiguous: Telegram may have accepted the request. Count
-            # every attempt, not only confirmed responses, before any retry.
-            _tg_last_send[chat_id] = loop.time()
+                continue
             try:
-                result = await call()
-                return result
-            except TelegramRetryAfter as e:
-                _tg_flood_until[chat_id] = loop.time() + e.retry_after + _TG_RETRY_AFTER_MARGIN
-                logger.warning(f"TG {label} flood: retry in {e.retry_after}s")
-                if not important or attempt == attempts:
-                    break
-            except (TelegramNetworkError, TelegramServerError) as e:
-                if important and attempt < attempts:
-                    logger.warning(
-                        f"TG {label} ambiguous delivery, retry {attempt + 1}/{attempts}: {e}"
-                    )
-                    await asyncio.sleep(_TG_NETWORK_RETRY_DELAY * attempt)
-                    continue
-                if important:
-                    logger.warning(f"TG {label} LOST after {attempt} attempts: {e}")
-                else:
-                    logger.warning(f"TG {label} failed: {e}")
-                return None
+                result = await _tg_run_call(chat_id, call, important, label)
+                if not future.done():
+                    future.set_result(result)
+            except asyncio.CancelledError:
+                if not future.done():
+                    future.cancel()
+                raise
             except Exception as e:
-                if important:
-                    logger.warning(f"TG {label} LOST: {e}")
-                else:
-                    logger.warning(f"TG {label} failed: {e}")
-                return None
+                logger.exception(f"TG {label} dispatcher failed: {e}")
+                if not future.done():
+                    future.set_result(None)
+            finally:
+                queue.task_done()
+    finally:
+        current = asyncio.current_task()
+        if _tg_dispatch_tasks.get(chat_id) is current:
+            _tg_dispatch_tasks.pop(chat_id, None)
 
-        if important:
-            logger.warning(f"TG {label} LOST after {attempts} flood attempts")
-        return None
+
+async def _tg_call_safe(chat_id: int, call, *, important: bool = False, label: str = "call"):
+    """Queue one chat, prioritize important calls, and rate-limit delivery."""
+    global _tg_call_sequence
+    loop = asyncio.get_running_loop()
+    if _tg_queue_loops.get(chat_id) not in (None, loop):
+        _clear_tg_chat(chat_id)
+    queue = _tg_call_queues.setdefault(chat_id, asyncio.PriorityQueue())
+    _tg_queue_loops[chat_id] = loop
+    future = loop.create_future()
+    _tg_call_sequence += 1
+    queue.put_nowait((0 if important else 1, _tg_call_sequence, call, important, label, future))
+    task = _tg_dispatch_tasks.get(chat_id)
+    if task is None or task.done():
+        _tg_dispatch_tasks[chat_id] = asyncio.create_task(_tg_dispatch_chat(chat_id))
+    if important:
+        return await future
+    return future
 
 
 async def _tg_send_safe(chat_id: int, text: str, thread_id: int = None,
                          entities=None, important: bool = False):
     async def _send():
         try:
             return await bot.send_message(
                 chat_id, text, message_thread_id=thread_id,
@@ -600,51 +680,107 @@ async def _tg_send_safe(chat_id: int, text: str, thread_id: int = None,
         except TelegramBadRequest:
             if not entities:
                 raise
             return _TG_ENTITY_REJECTED
 
     result = await _tg_call_safe(
         chat_id, _send, important=important, label="send_message",
     )
+    if isinstance(result, asyncio.Future):
+        async def _finish_send():
+            queued_result = await result
+            if queued_result is not _TG_ENTITY_REJECTED:
+                return queued_result
+            logger.warning("TG formatted send rejected; trying without entities")
+
+            async def _send_plain_queued():
+                return await bot.send_message(
+                    chat_id, text, message_thread_id=thread_id,
+                    parse_mode=None, entities=None,
+                )
+
+            plain = await _tg_call_safe(
+                chat_id, _send_plain_queued, label="send_message_plain",
+            )
+            return await plain
+
+        return _track_tg_result(_finish_send())
     if result is not _TG_ENTITY_REJECTED:
         return result
 
     logger.warning("TG formatted send rejected; trying without entities")
 
     async def _send_plain():
         return await bot.send_message(
             chat_id, text, message_thread_id=thread_id,
             parse_mode=None, entities=None,
         )
 
     return await _tg_call_safe(
         chat_id, _send_plain, important=important, label="send_message_plain",
     )
 
 
-async def _tg_edit_message_safe(chat_id: int, message_id: int, text: str, entities=None):
+async def _tg_edit_message_safe(chat_id: int, message, text: str, entities=None):
+    async def _message_id():
+        resolved = await message if isinstance(message, asyncio.Future) else message
+        if resolved is None:
+            return None
+        return resolved if isinstance(resolved, int) else resolved.message_id
+
     async def _edit():
+        message_id = await _message_id()
+        if message_id is None:
+            return None
         try:
             return await bot.edit_message_text(
                 text, chat_id=chat_id, message_id=message_id,
                 entities=entities,
             )
         except TelegramBadRequest as e:
             if "message is not modified" in str(e).lower():
                 return True
             if not entities:
                 raise
             return _TG_ENTITY_REJECTED
 
     result = await _tg_call_safe(chat_id, _edit, label="edit_message")
+    if isinstance(result, asyncio.Future):
+        async def _finish_edit():
+            queued_result = await result
+            if queued_result is not _TG_ENTITY_REJECTED:
+                return queued_result
+
+            async def _edit_plain_queued():
+                message_id = await _message_id()
+                if message_id is None:
+                    return None
+                try:
+                    return await bot.edit_message_text(
+                        text, chat_id=chat_id, message_id=message_id,
+                    )
+                except TelegramBadRequest as e:
+                    if "message is not modified" in str(e).lower():
+                        return True
+                    raise
+
+            plain = await _tg_call_safe(
+                chat_id, _edit_plain_queued, label="edit_message_plain",
+            )
+            return await plain
+
+        return _track_tg_result(_finish_edit())
     if result is not _TG_ENTITY_REJECTED:
         return result
 
     async def _edit_plain():
+        message_id = await _message_id()
+        if message_id is None:
+            return None
         try:
             return await bot.edit_message_text(
                 text, chat_id=chat_id, message_id=message_id,
             )
         except TelegramBadRequest as e:
             if "message is not modified" in str(e).lower():
                 return True
             raise
@@ -1112,25 +1248,34 @@ def _result_images_enabled() -> bool:
 async def _send_png_to_tg(png: bytes, chat_id: int, thread_id: int, label: str) -> None:
     """Send PNG bytes as a photo to TG. Temp file cleaned up after send."""
     import uuid, tempfile
     if not png or not bot:
         return
     tmp = os.path.join(tempfile.gettempdir(), f"diff-{uuid.uuid4().hex}.png")
     with open(tmp, "wb") as f:
         f.write(png)
+    delivery = None
     try:
-        await _tg_send_file_safe(
+        delivery = await _tg_send_file_safe(
             chat_id, tmp, None, thread_id, is_photo=True, important=False,
         )
     finally:
-        try:
-            os.unlink(tmp)
-        except Exception as e:
-            logger.warning(f"tmp diff image cleanup failed ({tmp}): {e}")
+        def _cleanup(_=None):
+            try:
+                os.unlink(tmp)
+            except FileNotFoundError:
+                pass
+            except Exception as e:
+                logger.warning(f"tmp diff image cleanup failed ({tmp}): {e}")
+
+        if isinstance(delivery, asyncio.Future):
+            delivery.add_done_callback(_cleanup)
+        else:
+            _cleanup()


## LATER FIX aca605412c (6.8 days later): fix: isolate TG topic status updates
lines of origin it changed/deleted: 36
(code only, capped 400 lines)

fix: isolate TG topic status updates


diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index 2d3320710..ef67ab17b 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -1113,54 +1113,55 @@ async def _on_session_scope_running(s) -> None:
     orch_name = _find_scope_orch_name(s)
     if orch_name:
         await notify_scope_running(orch_name)
 
 
 async def _sync_all_topic_statuses():
     if not _manager or not bot:
         return
-    for s in _manager.sessions.values():
+    for s in list(_manager.sessions.values()):
         if s.role not in ("orchestrator", "sub-orchestrator"):
             continue
         name = s.name
         if name not in config["topics"]:
             continue
         is_running = _any_running_in_scope(s.scope)
         _topic_status.pop(name, None)
         await _update_topic_status(name, is_running)
 
 
 # Custom emoji IDs in the target TG group — green dot for running, grey for idle
 _ICON_RUNNING = "5312016608254762256"
 _ICON_IDLE = "5350392020785437399"
+_TG_TOPIC_STATUS_TIMEOUT = 5
 
 
-# Deduplicated topic icon updates with flood-control retry (like _tg_send_safe)
+# Topic metadata is best-effort and stays outside the user-message delivery queue.
 async def _update_topic_status(orch_name: str, is_running: bool):
     if _topic_status.get(orch_name) == is_running:
         return
     short = (config.get("topic_names") or {}).get(orch_name) or _short_name(orch_name)
     icon_id = _ICON_RUNNING if is_running else _ICON_IDLE
 
     async def _do_edit(chat_id, thread_id):
-        async def _edit():
-            try:
+        try:
+            async with asyncio.timeout(_TG_TOPIC_STATUS_TIMEOUT):
                 return await bot.edit_forum_topic(
                     chat_id=chat_id, message_thread_id=thread_id,
                     name=short, icon_custom_emoji_id=icon_id,
+                    request_timeout=_TG_TOPIC_STATUS_TIMEOUT,
                 )
-            except TelegramBadRequest as e:
-                if "TOPIC_NOT_MODIFIED" in str(e).upper():
-                    return True
-                raise
-
-        return await _tg_call_safe(
-            chat_id, _edit, label="topic_status", important=True,
-        )
+        except TelegramBadRequest as e:
+            if "TOPIC_NOT_MODIFIED" in str(e).upper():
+                return True
+            logger.debug(f"TG topic_status failed: {e}")
+        except Exception as e:
+            logger.debug(f"TG topic_status failed: {e}")
+        return None
 
     thread_id = config["topics"].get(orch_name)
     primary_updated = False
     if thread_id and bot:
         primary_updated = await _do_edit(config["group_id"], thread_id) is not None
     mirror = config.get("mirrors", {}).get(orch_name)
     if mirror and mirror.get("chat_id") and mirror.get("topic_id") and bot:
         await _do_edit(mirror["chat_id"], mirror["topic_id"])
@@ -1855,17 +1856,17 @@ async def start_bridge(manager):
         _tasks.append(asyncio.create_task(_bot_api_health_loop(local_api)))
     logger.info(f"TG Bridge started (polling immediate, topics deferred) | group={group}")
 
 
 async def _deferred_startup():
     try:
         await ensure_topics()
         await _sync_all_topic_statuses()
-        for name, thread_id in config["topics"].items():
+        for name, thread_id in list(config["topics"].items()):
             _tasks.append(asyncio.create_task(stream_logs(name, thread_id)))
         _tasks.append(asyncio.create_task(topic_sync_loop()))
         logger.info(f"TG deferred startup done | topics={len(config['topics'])}")
     except Exception as e:
         logger.error(f"TG deferred startup failed: {e}")
 
 
 # Health check for the local telegram-bot-api server — restarts it after 3 consecutive failures.
diff --git a/tests/test_tg_bridge.py b/tests/test_tg_bridge.py
index 5fc0d12be..55c76a72c 100644
--- a/tests/test_tg_bridge.py
+++ b/tests/test_tg_bridge.py
@@ -24,19 +24,23 @@ def tb(tmp_path, monkeypatch):
     cfg_path = tmp_path / "tg_bridge.json"
     monkeypatch.setattr("app.tg_bridge.CONFIG_PATH", cfg_path)
     from app import tg_bridge
 
     tg_bridge.config = {"group_id": -100123456, "topics": {}, "token": "test"}
     tg_bridge._topic_status = {}
     tg_bridge.bot = None
     tg_bridge._pil_available = None
-    monkeypatch.setattr(tg_bridge, "_tg_chat_locks", {}, raising=False)
-    monkeypatch.setattr(tg_bridge, "_tg_flood_until", {}, raising=False)
-    monkeypatch.setattr(tg_bridge, "_tg_last_send", {}, raising=False)
+    monkeypatch.setattr(tg_bridge, "_tg_call_queues", {})
+    monkeypatch.setattr(tg_bridge, "_tg_dispatch_tasks", {})
+    monkeypatch.setattr(tg_bridge, "_tg_queue_loops", {})
+    monkeypatch.setattr(tg_bridge, "_tg_result_tasks", set())
+    monkeypatch.setattr(tg_bridge, "_tg_flood_until", {})
+    monkeypatch.setattr(tg_bridge, "_tg_last_send", {})
+    monkeypatch.setattr(tg_bridge, "_tg_call_sequence", 0)
     return tg_bridge
 
 
 @pytest.mark.asyncio
 async def test_polling_does_not_override_uvicorn_signal_handlers(tb):
     dispatcher = AsyncMock()
     dispatcher.start_polling.side_effect = asyncio.CancelledError
     bot = object()
@@ -720,56 +724,185 @@ class TestTgSendSafe:
         monkeypatch.setattr(tb, "_TG_NETWORK_RETRY_DELAY", 0)
 
         result = await tb._tg_send_safe(-100, "hello", 77, important=True)
 
         assert result is None
         assert tb.bot.send_message.await_count == tb._TG_IMPORTANT_ATTEMPTS
         assert "LOST" in caplog.text
 
+
+class TestTopicStatusDelivery:
     @pytest.mark.asyncio
-    async def test_drops_nonimportant_call_while_chat_busy(self, tb):
+    async def test_slow_topic_status_does_not_block_message_queue(self, tb, monkeypatch):
+        edit_started = asyncio.Event()
+        never_finishes = asyncio.Event()
+
+        async def edit_forum_topic(*args, **kwargs):
+            edit_started.set()
+            await never_finishes.wait()
+
         tb.bot = AsyncMock()
-        lock = asyncio.Lock()
-        await lock.acquire()
-        tb._tg_chat_locks[-100] = lock
-        try:
-            result = await tb._tg_send_safe(-100, "tool", 77, important=False)
-        finally:
-            lock.release()
+        tb.bot.edit_forum_topic.side_effect = edit_forum_topic
+        tb.bot.send_message.return_value = object()
+        tb.config["topics"] = {"orch": 42}
+        monkeypatch.setattr(tb, "_TG_TOPIC_STATUS_TIMEOUT", 0.01)
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
 
-        assert result is None
-        tb.bot.send_message.assert_not_awaited()
+        status_task = asyncio.create_task(tb._update_topic_status("orch", True))
+        await asyncio.wait_for(edit_started.wait(), timeout=0.1)
+
+        message = await asyncio.wait_for(
+            tb._tg_send_safe(tb.config["group_id"], "reply", 42, important=True),
+            timeout=0.1,
+        )
+        await status_task
+
+        assert message is not None
+        tb.bot.send_message.assert_awaited_once()
+        tb.bot.edit_forum_topic.assert_awaited_once()
+        assert tb._topic_status == {}
+
+    @pytest.mark.asyncio
+    async def test_sync_statuses_iterates_session_snapshot(self, tb, monkeypatch):
+        def session(name):
+            return type("Session", (), {
+                "name": name,
+                "role": "orchestrator",
+                "scope": f"/{name}",
+            })()
+
+        manager = type("Manager", (), {
+            "sessions": {"orch-1": session("orch-1"), "orch-2": session("orch-2")},
+        })()
+        tb.bot = object()
+        tb.config["topics"] = {"orch-1": 1, "orch-2": 2, "orch-3": 3}
+        monkeypatch.setattr(tb, "_manager", manager)
+        monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
+        updated = []
+
+        async def update(name, is_running):
+            updated.append((name, is_running))
+            if name == "orch-1":
+                manager.sessions["orch-3"] = session("orch-3")
+
+        monkeypatch.setattr(tb, "_update_topic_status", update)
+
+        await tb._sync_all_topic_statuses()
+
+        assert updated == [("orch-1", False), ("orch-2", False)]
+
+    @pytest.mark.asyncio
+    async def test_deferred_startup_iterates_topic_snapshot(self, tb, monkeypatch):
+        streamed = []
+
+        async def stream_logs(name, thread_id):
+            streamed.append((name, thread_id))
+
+        async def no_op():
+            pass
+
+        class MutatingTasks(list):
+            def append(self, task):
+                super().append(task)
+                if len(self) == 1:
+                    tb.config["topics"]["orch-3"] = 3
+
+        tasks = MutatingTasks()
+        tb.config["topics"] = {"orch-1": 1, "orch-2": 2}
+        monkeypatch.setattr(tb, "_tasks", tasks)
+        monkeypatch.setattr(tb, "ensure_topics", no_op)
+        monkeypatch.setattr(tb, "_sync_all_topic_statuses", no_op)
+        monkeypatch.setattr(tb, "stream_logs", stream_logs)
+        monkeypatch.setattr(tb, "topic_sync_loop", no_op)
+
+        await tb._deferred_startup()
+        await asyncio.gather(*tasks)
+
+        assert streamed == [("orch-1", 1), ("orch-2", 2)]
+
+
+class TestTgCallQueue:
+    @pytest.mark.asyncio
+    async def test_important_call_overtakes_waiting_nonimportant_call(self, tb, monkeypatch):
+        blocker_started = asyncio.Event()
+        release_blocker = asyncio.Event()
+        calls = []
+
+        async def send_message(chat_id, text, **kwargs):
+            calls.append(text)
+            if text == "blocker":
+                blocker_started.set()
+                await release_blocker.wait()
+            return object()
+
+        tb.bot = AsyncMock()
+        tb.bot.send_message.side_effect = send_message
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
+
+        blocker = asyncio.create_task(
+            tb._tg_send_safe(-100, "blocker", 77, important=True),
+        )
+        await asyncio.wait_for(blocker_started.wait(), timeout=0.1)
+        nonimportant = await tb._tg_send_safe(-100, "tool", 77)
+        important = asyncio.create_task(
+            tb._tg_send_safe(-100, "reply", 77, important=True),
+        )
+        await asyncio.sleep(0)
+        release_blocker.set()
+
+        await asyncio.gather(blocker, important, nonimportant)
+
+        assert calls == ["blocker", "reply", "tool"]
 
     @pytest.mark.asyncio
-    async def test_drops_nonimportant_call_inside_interval(self, tb, monkeypatch):
+    async def test_queued_nonimportant_calls_keep_rate_interval(self, tb, monkeypatch):
+        sent_at = []
+
+        async def send_message(*args, **kwargs):
+            sent_at.append(asyncio.get_running_loop().time())
+            return object()
+
         tb.bot = AsyncMock()
-        tb.bot.send_message.return_value = object()
-        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 10)
+        tb.bot.send_message.side_effect = send_message
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0.02)
 
         first = await tb._tg_send_safe(-100, "tool-1", 77)
         second = await tb._tg_send_safe(-100, "tool-2", 77)
+        await asyncio.gather(first, second)
 
-        assert first is not None
-        assert second is None
-        tb.bot.send_message.assert_awaited_once()
+        assert len(sent_at) == 2
+        assert sent_at[1] - sent_at[0] >= 0.018
 
     @pytest.mark.asyncio
-    async def test_drops_edit_before_lock_wait(self, tb):
+    async def test_queued_edit_does_not_block_caller(self, tb, monkeypatch):
+        blocker_started = asyncio.Event()
+        release_blocker = asyncio.Event()
+
+        async def send_message(*args, **kwargs):
+            blocker_started.set()
+            await release_blocker.wait()
+            return object()
+
         tb.bot = AsyncMock()
-        lock = asyncio.Lock()
-        await lock.acquire()
-        tb._tg_chat_locks[-100] = lock
-        try:
-            result = await tb._tg_edit_message_safe(-100, 5, "updated", [object()])
-        finally:
-            lock.release()
+        tb.bot.send_message.side_effect = send_message
+        tb.bot.edit_message_text.return_value = object()
+        monkeypatch.setattr(tb, "_TG_GROUP_INTERVAL", 0)
 
-        assert result is None
+        blocker = asyncio.create_task(
+            tb._tg_send_safe(-100, "blocker", 77, important=True),
+        )
+        await asyncio.wait_for(blocker_started.wait(), timeout=0.1)
+        edit = await tb._tg_edit_message_safe(-100, 5, "updated")
+
+        assert isinstance(edit, asyncio.Task)
         tb.bot.edit_message_text.assert_not_awaited()
+        release_blocker.set()
+        await asyncio.gather(blocker, edit)
+        tb.bot.edit_message_text.assert_awaited_once()
 
 
 class TestSendFileRetry:
     @pytest.mark.asyncio
     async def test_recreates_files_for_primary_and_mirror_retry(self, tb, tmp_path, monkeypatch):
         path = tmp_path / "report.txt"
         path.write_text("hello")
         method = SendMessage(chat_id=-100, text="file placeholder")