"""Telegram bridge — mirrors Orchestra orchestrators to TG group topics.

Integrated into FastAPI lifespan — no separate process needed.
Queue-based TG delivery: all sends/edits go through asyncio.Queue consumer
at max 1 op per 3 seconds per group (respecting TG rate limits).
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from telegramify_markdown import convert as md_convert

logger = logging.getLogger("tg-bridge")

CONFIG_PATH = Path(__file__).parent.parent / "data" / "tg_bridge.json"
UPLOADS_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_CACHE_PATH = UPLOADS_DIR / ".media_cache.json"
TRANSCRIPTION_CACHE_PATH = UPLOADS_DIR / ".transcription_cache.json"

config = {"group_id": 0, "topics": {}, "token": ""}
bot = None
dp = Dispatcher()
_manager = None
_tasks = []
DEEPGRAM_API_KEY = ""


def save_config():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def load_config():
    global config
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())


def _load_media_cache() -> dict[str, str]:
    if MEDIA_CACHE_PATH.exists():
        try:
            data = json.loads(MEDIA_CACHE_PATH.read_text())
            return {k: v for k, v in data.items() if Path(v).exists()}
        except Exception:
            pass
    return {}


def _save_media_cache(cache: dict[str, str]):
    MEDIA_CACHE_PATH.write_text(json.dumps(cache))


_media_cache: dict[str, str] = _load_media_cache()


def _load_transcription_cache() -> dict[str, str]:
    if TRANSCRIPTION_CACHE_PATH.exists():
        try:
            return json.loads(TRANSCRIPTION_CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_transcription_cache(cache: dict[str, str]):
    TRANSCRIPTION_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False))


_transcription_cache: dict[str, str] = _load_transcription_cache()


def _media_name(prefix: str, ext: str, msg: types.Message) -> str:
    ts = msg.date.strftime("%Y%m%d_%H%M%S") if msg.date else str(msg.message_id)
    return f"{prefix}_{ts}_{msg.message_id}{ext}"


async def _download_file(file_id: str, filename: str, unique_id: str = "") -> str | None:
    global _media_cache
    if unique_id and unique_id in _media_cache:
        cached = _media_cache[unique_id]
        if Path(cached).exists():
            return cached
        del _media_cache[unique_id]
    try:
        f = await bot.get_file(file_id)
        name = Path(filename).name
        path = UPLOADS_DIR / name
        if path.exists():
            stem, suffix = path.stem, path.suffix
            i = 1
            while path.exists():
                path = UPLOADS_DIR / f"{stem}_{i}{suffix}"
                i += 1
        await bot.download_file(f.file_path, str(path))
        if unique_id:
            _media_cache[unique_id] = str(path)
            _save_media_cache(_media_cache)
        return str(path)
    except Exception as e:
        logger.warning(f"download_file failed for {filename}: {e}")
        return None


async def _transcribe_audio(path: str, unique_id: str = "") -> tuple[str, str | None]:
    if unique_id and unique_id in _transcription_cache:
        cached = _transcription_cache[unique_id]
        logger.info(f"Transcription cache hit: {unique_id}")
        return cached, None
    if not DEEPGRAM_API_KEY:
        return "", "no DEEPGRAM_API_KEY"
    try:
        async with aiohttp.ClientSession() as http:
            with open(path, "rb") as af:
                audio_data = af.read()
            async with http.post(
                "https://api.deepgram.com/v1/listen?model=nova-3&language=ru&smart_format=true",
                headers={"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": "audio/ogg"},
                data=audio_data,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                out = await resp.read()
    except Exception as e:
        logger.error(f"Deepgram request error: {e}")
        return "", str(e)
    try:
        data = json.loads(out)
        if "error" in data:
            return "", data["error"]
        text = data["results"]["channels"][0]["alternatives"][0]["transcript"]
        duration = data.get("metadata", {}).get("duration", 0)
        logger.info(f"Deepgram: {duration:.1f}s, {len(text)} chars")
        if unique_id and text:
            _transcription_cache[unique_id] = text
            _save_transcription_cache(_transcription_cache)
        return text, None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        raw = out.decode(errors="replace")[:200]
        logger.error(f"Deepgram parse error: {e}, raw: {raw}")
        return "", str(e)


def _forward_meta(msg: types.Message) -> str:
    if not msg.forward_date:
        return ""
    fwd = "Forwarded"
    if msg.forward_from:
        name = msg.forward_from.first_name
        if msg.forward_from.last_name:
            name += " " + msg.forward_from.last_name
        fwd += f" from {name}"
    elif msg.forward_sender_name:
        fwd += f" from {msg.forward_sender_name}"
    return f"[{fwd}] "


async def _resolve_orch(msg: types.Message) -> tuple[str | None, object | None]:
    if not msg.message_thread_id or not _manager:
        return None, None
    thread_id = msg.message_thread_id
    orch_name = None
    for name, tid in config["topics"].items():
        if tid == thread_id:
            orch_name = name
            break
    if not orch_name:
        return None, None
    session = await _manager.ensure_loaded_any(orch_name)
    if not session:
        await msg.reply(f"❌ {orch_name} not found")
        return orch_name, None
    return orch_name, session


DEBOUNCE_SEC = 5
MEDIA_WAIT_MAX = 30


class _Phase(Enum):
    IDLE = "idle"
    COLLECTING = "collecting"
    WAITING_MEDIA = "waiting_media"


@dataclass
class _BufState:
    entries: list = field(default_factory=list)
    pending_media: int = 0
    phase: _Phase = _Phase.IDLE
    debounce_task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_buffers: dict[str, _BufState] = {}


def _get_buf(sid: str) -> _BufState:
    if sid not in _buffers:
        _buffers[sid] = _BufState()
    return _buffers[sid]


async def _arm_debounce(sid: str, buf: "_BufState"):
    if buf.debounce_task and not buf.debounce_task.done():
        buf.debounce_task.cancel()
    buf.phase = _Phase.COLLECTING
    buf.debounce_task = asyncio.create_task(_debounce_elapsed(sid))


async def _debounce_elapsed(sid: str):
    try:
        await asyncio.sleep(DEBOUNCE_SEC)
    except asyncio.CancelledError:
        return

    waited = 0.0
    buf = _get_buf(sid)
    while True:
        async with buf.lock:
            if buf.pending_media <= 0:
                break
            if waited >= MEDIA_WAIT_MAX:
                logger.warning(f"[{sid}] media wait timeout {waited:.1f}s, proceeding")
                buf.pending_media = 0
                break
            buf.phase = _Phase.WAITING_MEDIA
        await asyncio.sleep(0.3)
        waited += 0.3

    async with buf.lock:
        buf.debounce_task = None
        if buf.phase not in (_Phase.COLLECTING, _Phase.WAITING_MEDIA):
            return
        batch = list(buf.entries)
        buf.entries.clear()
        buf.phase = _Phase.IDLE

    await _flush_batch(sid, batch)


async def _flush_batch(sid: str, batch: list):
    if not batch:
        return
    valid = [(m, c) for m, c in batch if c is not None]
    if not valid:
        return
    if len(valid) == 1:
        combined = valid[0][1]
    else:
        combined = "\n".join(
            f"--- message {i+1}/{len(valid)} ---\n{content}"
            for i, (_, content) in enumerate(valid)
        )
    await _manager.send(sid, combined)
    for m, _ in valid:
        try:
            await m.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception:
            pass


async def _send_to_agent(msg: types.Message, session, content: str):
    sid = session.id
    buf = _get_buf(sid)
    async with buf.lock:
        buf.entries.append((msg, content))
        await _arm_debounce(sid, buf)


async def _register_media(msg: types.Message, session) -> tuple[str, int]:
    sid = session.id
    buf = _get_buf(sid)
    async with buf.lock:
        idx = len(buf.entries)
        buf.entries.append((msg, None))
        buf.pending_media += 1
        await _arm_debounce(sid, buf)
    return sid, idx


async def _resolve_media(sid: str, idx: int, content: str):
    buf = _get_buf(sid)
    flush_batch = None
    async with buf.lock:
        if idx < len(buf.entries):
            m, _ = buf.entries[idx]
            buf.entries[idx] = (m, content)
        buf.pending_media = max(0, buf.pending_media - 1)
        if buf.pending_media == 0 and buf.phase == _Phase.WAITING_MEDIA:
            batch = list(buf.entries)
            buf.entries.clear()
            buf.phase = _Phase.IDLE
            if buf.debounce_task and not buf.debounce_task.done():
                buf.debounce_task.cancel()
            buf.debounce_task = None
            flush_batch = batch
    if flush_batch is not None:
        await _flush_batch(sid, flush_batch)


async def _react_processing(msg: types.Message):
    try:
        await msg.react([types.ReactionTypeEmoji(emoji="👂")])
    except Exception:
        pass





# ---------------------------------------------------------------------------
#  Queue-based TG delivery
# ---------------------------------------------------------------------------

MIN_TG_INTERVAL = 3.0  # seconds between TG API calls per group (20 ops/min limit)
MAX_MSG_LEN = 3800     # split threshold (TG limit 4096, buffer for entities)


class _StreamPhase(Enum):
    IDLE = "idle"
    TOOLS = "tools"
    TEXT = "text"


@dataclass
class _QueueItem:
    type: str          # "tool", "tool_result", "text", "error", "status", "user_message"
    content: str
    chat_id: int
    thread_id: int


class TgStreamQueue:
    """Single consumer drains TG operations at rate-limited speed.

    All sends/edits for one group topic go through here.
    Producer puts items instantly, consumer drains at MIN_TG_INTERVAL.
    """

    def __init__(self, bot_ref: Bot, chat_id: int, thread_id: int):
        self._bot = bot_ref
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue()
        self._phase = _StreamPhase.IDLE
        self._current_msg_id: Optional[int] = None
        self._current_text = ""
        self._last_sent_text = ""
        self._tool_lines: list[str] = []
        self._last_op_time = 0.0

    def put_nowait(self, item: _QueueItem):
        self._queue.put_nowait(item)

    async def run(self):
        while True:
            item = await self._queue.get()
            batch = [item]
            while not self._queue.empty():
                batch.append(self._queue.get_nowait())

            try:
                await self._process_batch(batch)
            except Exception as e:
                logger.error(f"TG queue error: {e}")
            finally:
                for _ in batch:
                    self._queue.task_done()

            # always wait at least MIN_TG_INTERVAL after the last TG API call
            await self._rate_wait()

    async def _rate_wait(self):
        elapsed = time.monotonic() - self._last_op_time
        if elapsed < MIN_TG_INTERVAL:
            await asyncio.sleep(MIN_TG_INTERVAL - elapsed)

    async def _process_batch(self, batch: list[_QueueItem]):
        groups = self._group_items(batch)
        for i, group in enumerate(groups):
            if i > 0:
                await self._rate_wait()
            first = group[0]
            if first.type == "tool":
                await self._handle_tool_group(group)
            elif first.type == "text":
                await self._handle_text_group(group)
            elif first.type == "tool_result":
                for item in group:
                    await self._handle_tool_result(item)
            else:
                for item in group:
                    await self._handle_passthrough(item)
                    if item != group[-1]:
                        await self._rate_wait()

    @staticmethod
    def _group_items(batch: list[_QueueItem]) -> list[list[_QueueItem]]:
        """Group consecutive items by type (tool+tool_result stay together)."""
        groups: list[list[_QueueItem]] = []
        for item in batch:
            effective = "tool" if item.type == "tool_result" else item.type
            if groups:
                prev_effective = "tool" if groups[-1][0].type in ("tool", "tool_result") else groups[-1][0].type
                if effective == prev_effective:
                    groups[-1].append(item)
                    continue
            groups.append([item])
        return groups

    async def _handle_tool_group(self, items: list[_QueueItem]):
        """Process a group of tool + tool_result items → single TG operation."""
        for item in items:
            if item.type == "tool":
                self._accumulate_tool_line(item)
            elif item.type == "tool_result":
                self._accumulate_tool_result(item)

        text = "\n".join(self._tool_lines)
        if self._phase == _StreamPhase.TOOLS and self._current_msg_id:
            if len(text) > MAX_MSG_LEN:
                overflow_start = self._find_split_point(text)
                keep_text = text[:overflow_start].rstrip()
                await self._safe_edit(keep_text)
                self._current_text = keep_text
                await self._rate_wait()
                rest_lines = text[overflow_start:].lstrip().split("\n")
                self._tool_lines = rest_lines
                text = "\n".join(rest_lines)
                msg = await self._safe_send(text)
                if msg:
                    self._current_msg_id = msg.message_id
                    self._current_text = text
            else:
                await self._safe_edit(text)
                self._current_text = text
        else:
            self._start_new_msg()
            self._phase = _StreamPhase.TOOLS
            msg = await self._safe_send(text)
            if msg:
                self._current_msg_id = msg.message_id
                self._current_text = text

    def _accumulate_tool_line(self, item: _QueueItem):
        tool_name = item.content.split(":")[0].strip() if ":" in item.content else "tool"
        tool_body = item.content[len(tool_name)+1:].strip()[:120] if ":" in item.content else ""
        icon = _tg_tool_icon(tool_name)
        short = _tg_tool_short(tool_name)
        preview = tool_body[:60] if tool_body else ""
        line = f"{icon} {short}" + (f": {preview}" if preview else "")
        if self._phase != _StreamPhase.TOOLS:
            self._tool_lines = []
        self._tool_lines.append(line)

    def _accumulate_tool_result(self, item: _QueueItem):
        if not self._tool_lines:
            return
        result_preview = item.content[:80].replace("\n", " ").strip()
        self._tool_lines[-1] = f"{self._tool_lines[-1]} → {result_preview}"

    async def _handle_tool_result(self, item: _QueueItem):
        if self._phase != _StreamPhase.TOOLS or not self._current_msg_id or not self._tool_lines:
            return
        self._accumulate_tool_result(item)
        new_text = "\n".join(self._tool_lines)
        if len(new_text) <= MAX_MSG_LEN:
            await self._safe_edit(new_text)
            self._current_text = new_text

    async def _handle_text_group(self, items: list[_QueueItem]):
        """Process a group of text items → single TG operation."""
        combined = "".join(i.content[:3800] for i in items)
        if self._phase == _StreamPhase.TEXT and self._current_msg_id:
            new_text = self._current_text + combined
            if len(new_text) > MAX_MSG_LEN:
                self._start_new_msg()
                text = f"💬\n{combined[:MAX_MSG_LEN]}"
                msg = await self._safe_send(text)
                if msg:
                    self._current_msg_id = msg.message_id
                    self._current_text = text
                    self._phase = _StreamPhase.TEXT
            else:
                await self._safe_edit(new_text)
                self._current_text = new_text
        else:
            self._start_new_msg()
            self._phase = _StreamPhase.TEXT
            text = f"💬\n{combined[:MAX_MSG_LEN]}"
            msg = await self._safe_send(text)
            if msg:
                self._current_msg_id = msg.message_id
                self._current_text = text

    @staticmethod
    def _find_split_point(text: str) -> int:
        search_start = max(0, MAX_MSG_LEN - 200)
        nl2 = text.rfind("\n\n", search_start, MAX_MSG_LEN)
        if nl2 != -1:
            return nl2 + 2
        nl = text.rfind("\n", search_start, MAX_MSG_LEN)
        if nl != -1:
            return nl + 1
        return MAX_MSG_LEN

    async def _handle_passthrough(self, item: _QueueItem):
        self._start_new_msg()
        if item.type == "error":
            text = f"❌ {item.content[:1000]}"
        elif item.type == "status":
            text = f"⚡ {item.content}"
        elif item.type == "user_message":
            c = item.content
            if c.startswith("[from:"):
                prefix = c.split("]")[0] + "]"
                body = c[len(prefix):].strip()
                text = f"📨 {prefix}\n{body[:3000]}"
            else:
                text = f"👤 {c[:3000]}"
        else:
            text = item.content[:3000]
        await self._safe_send(text)

    def _start_new_msg(self):
        self._current_msg_id = None
        self._current_text = ""
        self._last_sent_text = ""
        self._tool_lines = []
        self._phase = _StreamPhase.IDLE

    async def _safe_send(self, text: str) -> Optional[types.Message]:
        self._last_op_time = time.monotonic()
        try:
            converted, entities = md_convert(text)
            ent_dicts = [e.to_dict() for e in entities] if entities else None
            return await self._bot.send_message(
                self._chat_id, converted,
                message_thread_id=self._thread_id,
                parse_mode=None, entities=ent_dicts,
            )
        except TelegramRetryAfter as e:
            logger.warning(f"TG flood on send, waiting {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            try:
                return await self._bot.send_message(
                    self._chat_id, text,
                    message_thread_id=self._thread_id,
                )
            except Exception as e2:
                logger.warning(f"TG send retry failed: {e2}")
                return None
        except Exception:
            try:
                return await self._bot.send_message(
                    self._chat_id, text,
                    message_thread_id=self._thread_id,
                )
            except Exception as e:
                logger.warning(f"TG send failed: {e}")
                return None

    async def _safe_edit(self, text: str):
        if not self._current_msg_id:
            return
        if text == self._last_sent_text:
            return
        self._last_op_time = time.monotonic()
        try:
            converted, entities = md_convert(text)
            ent_dicts = [e.to_dict() for e in entities] if entities else None
            await self._bot.edit_message_text(
                converted, chat_id=self._chat_id,
                message_id=self._current_msg_id,
                parse_mode=None, entities=ent_dicts,
            )
            self._last_sent_text = text
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            try:
                await self._bot.edit_message_text(
                    text, chat_id=self._chat_id,
                    message_id=self._current_msg_id,
                )
                self._last_sent_text = text
            except TelegramBadRequest as e2:
                if "message is not modified" not in str(e2).lower():
                    logger.warning(f"TG edit failed: {e2}")
        except TelegramRetryAfter as e:
            logger.warning(f"TG flood on edit, waiting {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            logger.warning(f"TG edit failed: {e}")


_stream_queues: dict[str, TgStreamQueue] = {}


def _get_stream_queue(orch_name: str, chat_id: int, thread_id: int) -> TgStreamQueue:
    if orch_name not in _stream_queues:
        q = TgStreamQueue(bot, chat_id, thread_id)
        _stream_queues[orch_name] = q
        _tasks.append(asyncio.create_task(q.run()))
    return _stream_queues[orch_name]


# ---------------------------------------------------------------------------
#  Tool icons
# ---------------------------------------------------------------------------

_TG_TOOL_ICONS = {
    'Bash': '🖥', 'Read': '📖', 'Write': '✏️', 'Edit': '✏️',
    'Glob': '🔎', 'Grep': '🔎', 'WebSearch': '🌐', 'WebFetch': '🌐',
    'Agent': '🤖', 'ToolSearch': '🔍', 'AskUserQuestion': '❓',
}
_TG_MCP_ICONS = {
    'orchestra': '🎼', 'websearch': '🌐', 'kesha': '🦜',
    'yougile': '📋', 'serena': '🧠', 'mailru': '📧',
}


def _tg_tool_icon(name: str) -> str:
    if name.startswith('mcp__'):
        parts = name.split('__')
        return _TG_MCP_ICONS.get(parts[1], '🔌') if len(parts) >= 2 else '🔌'
    for key, icon in _TG_TOOL_ICONS.items():
        if name == key or name.startswith(key):
            return icon
    return '🔧'


def _tg_tool_short(name: str) -> str:
    if name.startswith('mcp__'):
        parts = name.split('__', 2)
        return parts[2] if len(parts) >= 3 else name
    return name


def _short_name(name: str) -> str:
    return name.replace("-orchestrator", "")


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _find_thread_for_scope(scope: str) -> int | None:
    from app.db import get_all_sessions
    for s in get_all_sessions():
        if s.get("is_orchestrator") and s.get("scope", "").rstrip("/") == scope.rstrip("/"):
            tid = config["topics"].get(s["name"])
            if tid:
                return tid
    return None


async def send_file_to_tg(path: str, caption: str, scope: str, sender: str) -> dict:
    if not bot or not config["group_id"]:
        return {"error": "TG bridge not active"}
    from pathlib import Path as P
    fp = P(path)
    if not fp.exists():
        return {"error": f"file not found: {path}"}
    if fp.stat().st_size > 50 * 1024 * 1024:
        return {"error": "file too large (max 50MB)"}
    thread_id = _find_thread_for_scope(scope)
    if not thread_id:
        return {"error": f"no TG topic for scope: {scope}"}
    label = f"📎 {sender}: {caption}" if caption else f"📎 {sender}: {fp.name}"
    label = label[:1024]
    try:
        from aiogram.types import FSInputFile
        tg_file = FSInputFile(path, filename=fp.name)
        if fp.suffix.lower() in _IMAGE_EXTS:
            await bot.send_photo(config["group_id"], tg_file, caption=label, message_thread_id=thread_id)
        else:
            await bot.send_document(config["group_id"], tg_file, caption=label, message_thread_id=thread_id)
        return {"ok": True}
    except TelegramRetryAfter as e:
        return {"error": f"TG flood: retry after {e.retry_after}s"}
    except Exception as e:
        return {"error": str(e)}


async def ensure_topics():
    if not bot or not config["group_id"] or not _manager:
        return
    from app.db import get_all_sessions
    orchs = [s for s in get_all_sessions() if s.get("is_orchestrator")]
    if not orchs:
        return

    for o in orchs:
        name = o["name"]
        if name in config["topics"]:
            continue
        try:
            short = _short_name(name)
            result = await bot.create_forum_topic(chat_id=config["group_id"], name=f"🎯 {short}")
            config["topics"][name] = result.message_thread_id
            save_config()
            logger.info(f"Created topic for {name}: {result.message_thread_id}")
            asyncio.create_task(stream_logs(name, result.message_thread_id))
        except Exception as e:
            logger.error(f"Failed to create topic for {name}: {e}")


async def stream_logs(orch_name: str, thread_id: int):
    """Poll DB logs and feed them into TgStreamQueue for rate-limited delivery."""
    from app.db import get_logs, get_session_by_name, get_all_sessions

    scope = None
    for s in get_all_sessions():
        if s["name"] == orch_name:
            scope = s.get("scope", "")
            break
    if not scope:
        return

    session_id = None
    row = get_session_by_name(orch_name, scope)
    if row:
        session_id = row["id"]
    if not session_id:
        return

    logs = get_logs(session_id, after_id=0)
    last_id = logs[-1]["id"] if logs else 0

    queue = _get_stream_queue(orch_name, config["group_id"], thread_id)

    while True:
        try:
            logs = get_logs(session_id, after_id=last_id)
            for log in logs:
                if log["id"] <= last_id:
                    continue
                last_id = log["id"]
                t, c = log["type"], log["content"]
                if t in ("tool", "tool_result", "text", "error", "status", "user_message"):
                    queue.put_nowait(_QueueItem(
                        type=t, content=c,
                        chat_id=config["group_id"], thread_id=thread_id,
                    ))
        except Exception as e:
            logger.error(f"Stream error for {orch_name}: {e}")
        await asyncio.sleep(2)


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.voice)
async def handle_voice(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    await _react_processing(msg)
    sid, idx = await _register_media(msg, session)
    path = await _download_file(msg.voice.file_id, _media_name("voice", ".oga", msg), msg.voice.file_unique_id)
    if not path:
        await _resolve_media(sid, idx, f"{_forward_meta(msg)}[voice: file too large]")
        return
    text, err = await _transcribe_audio(path, msg.voice.file_unique_id)
    if text:
        await _resolve_media(sid, idx, f"{_forward_meta(msg)}[voice: {path} | {text}]")
    else:
        await _resolve_media(sid, idx, f"{_forward_meta(msg)}[voice: {path}]")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.video_note)
async def handle_video_note(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    await _react_processing(msg)
    sid, idx = await _register_media(msg, session)
    path = await _download_file(msg.video_note.file_id, _media_name("videonote", ".mp4", msg), msg.video_note.file_unique_id)
    if not path:
        await _resolve_media(sid, idx, f"{_forward_meta(msg)}[video_note: file too large]")
        return
    audio_path = path.replace(".mp4", ".oga")
    p = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", path, "-vn", "-acodec", "libopus", "-y", audio_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await p.communicate()
    if p.returncode == 0:
        text, err = await _transcribe_audio(audio_path, msg.video_note.file_unique_id)
        if text:
            await _resolve_media(sid, idx, f"{_forward_meta(msg)}[video_note: {path} | {text}]")
            return
    await _resolve_media(sid, idx, f"{_forward_meta(msg)}[video_note: {path}]")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.photo)
async def handle_photo(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    await _react_processing(msg)
    path = await _download_file(msg.photo[-1].file_id, _media_name("photo", ".jpg", msg), msg.photo[-1].file_unique_id)
    caption = f"\n{msg.caption}" if msg.caption else ""
    tag = f"[photo: {path}]" if path else "[photo: file too large]"
    await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.document)
async def handle_document(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    await _react_processing(msg)
    doc = msg.document
    ext = os.path.splitext(doc.file_name or "file")[1] or ".bin"
    path = await _download_file(doc.file_id, doc.file_name or _media_name("doc", ext, msg), doc.file_unique_id)
    caption = f"\n{msg.caption}" if msg.caption else ""
    tag = f"[file: {path} | {doc.file_name}]" if path else f"[file: too large | {doc.file_name}]"
    await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.video)
async def handle_video(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    await _react_processing(msg)
    path = await _download_file(msg.video.file_id, msg.video.file_name or _media_name("video", ".mp4", msg), msg.video.file_unique_id)
    caption = f"\n{msg.caption}" if msg.caption else ""
    tag = f"[video: {path}]" if path else "[video: file too large]"
    await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.audio)
async def handle_audio(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    await _react_processing(msg)
    name = msg.audio.file_name or _media_name("audio", ".mp3", msg)
    path = await _download_file(msg.audio.file_id, name, msg.audio.file_unique_id)
    caption = f"\n{msg.caption}" if msg.caption else ""
    tag = f"[audio: {path} | {name}]" if path else f"[audio: too large | {name}]"
    await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.sticker)
async def handle_sticker(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    emoji = msg.sticker.emoji or "?"
    await _send_to_agent(msg, session, f"[sticker: {emoji}]")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def handle_group_message(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    content = f"{_forward_meta(msg)}{msg.text}"
    await _send_to_agent(msg, session, content)


async def topic_sync_loop():
    while True:
        await asyncio.sleep(30)
        try:
            await ensure_topics()
        except Exception as e:
            logger.error(f"Topic sync error: {e}")


async def start_bridge(manager):
    global bot, _manager, DEEPGRAM_API_KEY
    from dotenv import load_dotenv
    load_dotenv()

    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

    load_config()
    token = os.getenv("TG_BRIDGE_TOKEN", config.get("token", ""))
    group = int(os.getenv("TG_BRIDGE_GROUP", config.get("group_id", 0)))

    if not token or not group:
        logger.info("TG Bridge disabled (no TG_BRIDGE_TOKEN/TG_BRIDGE_GROUP)")
        return

    _manager = manager
    config["token"] = token
    config["group_id"] = group
    save_config()

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None))

    await ensure_topics()

    for name, thread_id in config["topics"].items():
        _tasks.append(asyncio.create_task(stream_logs(name, thread_id)))

    _tasks.append(asyncio.create_task(topic_sync_loop()))
    _tasks.append(asyncio.create_task(dp.start_polling(bot)))
    logger.info(f"TG Bridge started | group={group} | topics={len(config['topics'])}")


async def stop_bridge():
    for t in _tasks:
        t.cancel()
    _tasks.clear()
    _stream_queues.clear()
    if bot:
        await bot.session.close()


if __name__ == "__main__":
    import sys
    async def _main():
        from app.manager import SessionManager
        m = SessionManager()
        from app.db import init_db
        init_db()
        if len(sys.argv) > 1:
            os.environ["TG_BRIDGE_TOKEN"] = sys.argv[1]
        if len(sys.argv) > 2:
            os.environ["TG_BRIDGE_GROUP"] = sys.argv[2]
        await start_bridge(m)
        await asyncio.Event().wait()
    asyncio.run(_main())
