"""Telegram bridge — mirrors Orchestra orchestrators to TG group topics.

Integrated into FastAPI lifespan — no separate process needed.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.exceptions import TelegramRetryAfter
from aiogram.client.default import DefaultBotProperties
from telegramify_markdown import convert as md_convert

logger = logging.getLogger("tg-bridge")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())

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
    # Strip token before persisting — it's in .env, not on disk
    safe = {k: v for k, v in config.items() if k != "token"}
    CONFIG_PATH.write_text(json.dumps(safe, indent=2))


def load_config():
    global config
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
    if config.get("token"):
        config.pop("token", None)
        save_config()


def _load_media_cache() -> dict[str, str]:
    if MEDIA_CACHE_PATH.exists():
        try:
            data = json.loads(MEDIA_CACHE_PATH.read_text())
            # Drop entries whose files were deleted (cleanup rotation) — avoids dead references
            return {k: v for k, v in data.items() if Path(v).exists()}
        except Exception as e:
            logger.warning(f"media cache load failed: {e}")
    return {}


def _save_media_cache(cache: dict[str, str]):
    MEDIA_CACHE_PATH.write_text(json.dumps(cache))


_media_cache: dict[str, str] = _load_media_cache()


def _load_transcription_cache() -> dict[str, str]:
    if TRANSCRIPTION_CACHE_PATH.exists():
        try:
            return json.loads(TRANSCRIPTION_CACHE_PATH.read_text())
        except Exception as e:
            logger.warning(f"transcription cache load failed: {e}")
    return {}


def _save_transcription_cache(cache: dict[str, str]):
    TRANSCRIPTION_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False))


_transcription_cache: dict[str, str] = _load_transcription_cache()


def _media_name(prefix: str, ext: str, msg: types.Message) -> str:
    ts = msg.date.strftime("%Y%m%d_%H%M%S") if msg.date else str(msg.message_id)
    return f"{prefix}_{ts}_{msg.message_id}{ext}"


UPLOADS_MAX_BYTES = int(os.getenv("UPLOADS_MAX_MB", "1024")) * 1024 * 1024

# @mention for agent-to-user speech (type "text" → 💬) so TG notifications fire on the owner.
# NOT applied to inter-agent messages (📨 [from:]) — only direct user-facing responses.
# Static username from env (MVP). Dynamic "is this addressed to the user" detection is in backlog.
TG_USER_MENTION = os.getenv("TG_USER_MENTION", "").strip()


def _cleanup_uploads():
    files = [f for f in UPLOADS_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
    total = sum(f.stat().st_size for f in files)
    if total <= UPLOADS_MAX_BYTES:
        return
    files.sort(key=lambda f: f.stat().st_mtime)
    while total > UPLOADS_MAX_BYTES and files:
        old = files.pop(0)
        total -= old.stat().st_size
        old.unlink()
        logger.info(f"Uploads cleanup: deleted {old.name}")


async def _download_file(file_id: str, filename: str, unique_id: str = "") -> str | None:
    global _media_cache
    # file_unique_id is stable across bots — cache hit avoids re-downloading the same TG file
    if unique_id and unique_id in _media_cache:
        cached = _media_cache[unique_id]
        if Path(cached).exists():
            return cached
        del _media_cache[unique_id]
    _cleanup_uploads()
    t0 = time.monotonic()
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
        local_api = os.getenv("TG_LOCAL_API_URL", "")
        # Local Bot API server provides absolute paths — copy directly instead of downloading
        # over the network (~40ms vs ~2s for large files)
        if local_api and f.file_path and Path(f.file_path).is_absolute() and Path(f.file_path).exists():
            import shutil
            shutil.copy2(f.file_path, str(path))
            logger.info(f"download {filename}: local copy in {(time.monotonic()-t0)*1000:.0f}ms ({f.file_path})")
        else:
            await bot.download_file(f.file_path, str(path))
            logger.info(f"download {filename}: remote download in {(time.monotonic()-t0)*1000:.0f}ms")
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
    file_size = Path(path).stat().st_size
    with open(path, "rb") as af:
        audio_data = af.read()
    last_err = ""
    t0 = time.monotonic()
    import httpx
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120, verify=True) as client:
                resp = await client.post(
                    "https://api.deepgram.com/v1/listen?model=nova-3&language=ru&smart_format=true&profanity_filter=false",
                    headers={"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": "audio/ogg"},
                    content=audio_data,
                )
                out = resp.content
            break
        except Exception as e:
            last_err = str(e)
            logger.warning(f"Deepgram attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
    else:
        logger.error(f"Deepgram failed after 3 attempts: {last_err}")
        return "", last_err
    transcribe_ms = (time.monotonic() - t0) * 1000
    try:
        data = json.loads(out)
        if "error" in data:
            return "", data["error"]
        text = data["results"]["channels"][0]["alternatives"][0]["transcript"]
        duration = data.get("metadata", {}).get("duration", 0)
        logger.info(f"Deepgram: audio={duration:.1f}s size={file_size//1024}KB transcribe={transcribe_ms:.0f}ms")
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
    sender = msg.from_user.first_name if msg.from_user else "?"
    logger.debug(f"TG incoming: chat={msg.chat.id} thread={msg.message_thread_id} from={sender} text={str(msg.text or '')[:50]}")
    if not msg.message_thread_id or not _manager:
        return None, None
    thread_id = msg.message_thread_id
    orch_name = None
    for name, tid in config["topics"].items():
        if tid == thread_id and msg.chat.id == config.get("group_id"):
            orch_name = name
            break
    if not orch_name:
        for name, mirror in config.get("mirrors", {}).items():
            if msg.chat.id == mirror.get("chat_id") and thread_id == mirror.get("topic_id"):
                orch_name = name
                break
    if not orch_name:
        return None, None
    session = await _manager.ensure_loaded_any(orch_name)
    if not session:
        await msg.reply(f"❌ {orch_name} not found")
        return orch_name, None
    return orch_name, session


# Messages arriving within DEBOUNCE_SEC of each other are batched into one agent send.
# MEDIA_WAIT_MAX caps how long we stall for slow downloads before flushing without them.
DEBOUNCE_SEC = 5
MEDIA_WAIT_MAX = 30

from enum import Enum
from dataclasses import dataclass, field


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


# Cancel and restart the debounce timer each time a new message arrives —
# only the final fire actually flushes the batch to the agent
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
    local_tz = timezone(timedelta(hours=7))
    now = datetime.now(local_tz).strftime("%H:%M")
    combined = f"[{now}] {combined}"
    await _manager.send(sid, combined)


def _sender_tag(msg: types.Message) -> str:
    if not msg.from_user:
        return ""
    name = msg.from_user.first_name or ""
    if msg.from_user.last_name:
        name += " " + msg.from_user.last_name
    return f"[from TG: {name}] " if name else ""


async def _send_to_agent(msg: types.Message, session, content: str):
    content = f"{_sender_tag(msg)}{content}"
    sid = session.id
    buf = _get_buf(sid)
    async with buf.lock:
        buf.entries.append((msg, content))
        await _arm_debounce(sid, buf)


# Reserve a slot in the batch before the download completes —
# slot index is returned so the download goroutine can fill it in via _resolve_media
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




# TG Bot API entity offsets are in UTF-16 code units, not Python's character count or byte count
def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _md_entities(text: str, base_offset: int = 0):
    from aiogram.types import MessageEntity as AioEntity
    try:
        converted, raw_ents = md_convert(text)
        ents = [AioEntity(**{**e.to_dict(), "offset": e.offset + base_offset}) for e in raw_ents] if raw_ents else []
        return converted, ents
    except Exception:
        return text, []




# Edit an existing tool message to append the result inline —
# avoids a separate message and keeps tool+result visually grouped in TG
async def _edit_tool_with_result(msg, chat_id: int, tool_text: str, result_header: str, result_body: str):
    from aiogram.types import MessageEntity
    from aiogram.enums import MessageEntityType
    nl = tool_text.index("\n")
    tool_header = tool_text[:nl]
    tool_body = tool_text[nl + 1:].rstrip()
    result_body = result_body.rstrip()
    conv_tool, tool_ents = _md_entities(tool_body, 0)
    conv_result, result_ents = _md_entities(result_body, 0)
    parts = [tool_header, "\n", conv_tool, "\n\n", result_header, "\n", conv_result]
    text = "".join(parts)
    offsets = []
    pos = 0
    for p in parts:
        offsets.append(pos)
        pos += _utf16_len(p)
    for e in tool_ents:
        e.offset += offsets[2]
    for e in result_ents:
        e.offset += offsets[6]
    try:
        entities = [
            MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offsets[2], length=_utf16_len(conv_tool)),
            MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offsets[6], length=_utf16_len(conv_result)),
        ] + tool_ents + result_ents
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id, entities=entities)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
        except Exception as e2:
            if "message is not modified" not in str(e2).lower():
                logger.warning(f"TG edit failed: {e2}")


async def _edit_expandable(msg, chat_id: int, header: str, body: str):
    from aiogram.types import MessageEntity
    from aiogram.enums import MessageEntityType
    conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
    text = f"{header}\n{conv_body}"
    offset = _utf16_len(header) + 1
    length = _utf16_len(conv_body)
    try:
        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id, entities=entities)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
        except Exception as e2:
            if "message is not modified" not in str(e2).lower():
                logger.warning(f"TG edit failed: {e2}")


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
    try:
        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
        return await bot.send_message(chat_id, text, message_thread_id=thread_id, entities=entities)
    except Exception:
        try:
            return await bot.send_message(chat_id, text, message_thread_id=thread_id)
        except Exception as e:
            logger.warning(f"TG send failed: {e}")
            return None


TG_MSG_LIMIT = 4096


def _split_message(text: str, limit: int = TG_MSG_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind('\n', 0, limit)
        if cut < limit // 4:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip('\n')
    return chunks


_flood_until: float = 0
_last_send: float = 0
# TG allows ~1 msg/sec per chat — enforce minimum interval to avoid flood errors
_TG_MIN_INTERVAL = 1.0


# Rate-limited send with flood control: waits out flood bans before retrying important messages.
# Non-important messages are silently dropped after a flood to avoid queue buildup.
async def _tg_send_safe(chat_id: int, text: str, thread_id: int = None,
                         entities=None, important: bool = False):
    global _flood_until, _last_send
    now = asyncio.get_event_loop().time()
    if _flood_until > now:
        await asyncio.sleep(_flood_until - now + 0.1)
        now = asyncio.get_event_loop().time()
    gap = now - _last_send
    if gap < _TG_MIN_INTERVAL:
        await asyncio.sleep(_TG_MIN_INTERVAL - gap)
    try:
        result = await bot.send_message(chat_id, text, message_thread_id=thread_id,
                                         parse_mode=None, entities=entities)
        _last_send = asyncio.get_event_loop().time()
        return result
    except TelegramRetryAfter as e:
        _flood_until = asyncio.get_event_loop().time() + e.retry_after
        logger.warning(f"TG flood: pausing {e.retry_after}s")
        if important:
            await asyncio.sleep(e.retry_after + 0.5)
            try:
                result = await bot.send_message(chat_id, text, message_thread_id=thread_id,
                                                parse_mode=None, entities=entities)
                _last_send = asyncio.get_event_loop().time()
                return result
            except Exception as e2:
                logger.warning(f"TG important message LOST after flood retry: {e2}; text[:80]={text[:80]!r}")
        return None
    except Exception as e:
        logger.warning(f"TG send failed: {e}")
        return None


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


_MODEL_SHORT = {
    'claude-opus-4-8[1m]': 'opus-4.8-1M', 'claude-opus-4-7[1m]': 'opus-4.7-1M',
    'claude-opus-4-6[1m]': 'opus-4.6-1M', 'claude-opus-4-6': 'opus-4.6',
    'claude-sonnet-4-6': 'sonnet-4.6', 'claude-haiku-4-5': 'haiku-4.5',
    'claude-haiku-4-6': 'haiku-4.6', 'gpt-5.5': 'gpt-5.5',
}


def _fmt_worker_info(data: dict) -> str | None:
    """Pretty format get_worker_info result for TG."""
    name = data.get("name")
    if not name:
        return None
    model = _MODEL_SHORT.get(data.get("model", ""), data.get("model", "?"))
    status = data.get("status", "?")
    ctx = data.get("context_pct")
    ctx_s = f" | ctx:{ctx}%" if ctx else ""
    lines = [f"🤖 {name} ({model}) | {status}{ctx_s}"]
    scope = data.get("scope", "")
    if scope:
        short_scope = scope.rsplit("/", 1)[-1] if "/" in scope else scope
        lines.append(f"📁 {short_scope}")
    branch = data.get("branch", "")
    if branch:
        lines.append(f"🌿 {branch}")
    cost = data.get("cost_usd")
    cached = data.get("cost_usd_cached")
    if cost:
        cost_s = f"💰 ${cost:.2f}"
        if cached:
            cost_s += f" (${cached:.2f} cached)"
        lines.append(cost_s)
    turns = data.get("total_turns", 0)
    out_tokens = data.get("total_output_tokens", 0)
    if turns or out_tokens:
        parts = []
        if turns:
            parts.append(f"{turns} turn{'s' if turns != 1 else ''}")
        if out_tokens:
            tok = f"{out_tokens // 1000}k" if out_tokens >= 1000 else str(out_tokens)
            parts.append(f"{tok} out tokens")
        lines.append(f"📊 {', '.join(parts)}")
    task_id = data.get("task_id", "")
    if task_id:
        lines.append(f"📋 task #{task_id}")
    desc = data.get("description", "")
    if desc:
        lines.append(f"📝 {desc[:100]}")
    return "\n".join(lines)


def _short_name(name: str) -> str:
    return name.replace("-orchestrator", "")


def _pick_unique_topic_name(orch_name: str) -> str:
    """Выбрать свободное имя для TG-топика по orch_name с учётом коллизий.

    Если short(orch_name) уже занят другим оркестратором, возвращаем
    ``<short>-2``, ``<short>-3`` и т.д. Имя оркестратора, для которого
    уже выбрано имя в ``config['topic_names']``, возвращается без изменений.
    """
    topic_names = config.setdefault("topic_names", {})
    if orch_name in topic_names:
        return topic_names[orch_name]
    base = _short_name(orch_name)
    used = set(topic_names.values()) | {
        _short_name(k) for k in config["topics"] if k not in topic_names
    }
    if base not in used:
        return base
    i = 2
    while f"{base}-{i}" in used:
        i += 1
    return f"{base}-{i}"


async def remove_topics_for_orchs(orch_names: list[str]) -> dict:
    """Удалить TG-топики и записи из ``config['topics']`` для указанных оркестраторов.

    Mirrors не трогаем — их пользователь настраивает руками для отдельных групп.
    Ошибки Bot API (топик уже удалён в TG) логируются как warning, но запись
    из ``config`` всё равно убирается, чтобы не оставалось зомби.

    Возвращает структуру с разбивкой по статусу:
        {"deleted": [name, ...], "failed": [{"name": ..., "error": ...}], "skipped": [name, ...]}
    """
    if not bot or not config.get("group_id"):
        return {"deleted": [], "failed": [], "skipped": list(orch_names), "error": "bridge inactive"}

    deleted: list[str] = []
    failed: list[dict] = []
    skipped: list[str] = []
    topic_names = config.setdefault("topic_names", {})

    for name in orch_names:
        thread_id = config["topics"].get(name)
        if not thread_id:
            skipped.append(name)
            topic_names.pop(name, None)
            _topic_status.pop(name, None)
            continue
        try:
            await bot.delete_forum_topic(chat_id=config["group_id"], message_thread_id=thread_id)
            deleted.append(name)
        except Exception as e:
            logger.warning(f"Failed to delete TG topic for {name} (thread_id={thread_id}): {e}")
            failed.append({"name": name, "error": str(e)})
        # config очищаем независимо от ответа API: если топика уже нет — тем более
        config["topics"].pop(name, None)
        topic_names.pop(name, None)
        _topic_status.pop(name, None)

    save_config()
    return {"deleted": deleted, "failed": failed, "skipped": skipped}


async def rename_orch_topic(old_name: str, new_name: str) -> dict:
    """Переименовать оркестратора в TG config — обновить ключ в topics + topic_names,
    и переименовать сам топик в TG если бот доступен."""
    thread_id = config.get("topics", {}).pop(old_name, None)
    if thread_id is None:
        return {"error": f"no topic for '{old_name}'"}
    config["topics"][new_name] = thread_id
    topic_names = config.get("topic_names", {})
    old_display = topic_names.pop(old_name, None)
    new_display = _short_name(new_name)
    topic_names[new_name] = new_display
    config["topic_names"] = topic_names
    mirrors = config.get("mirrors", {})
    if old_name in mirrors:
        mirrors[new_name] = mirrors.pop(old_name)
        config["mirrors"] = mirrors
    if old_name in _topic_status:
        _topic_status[new_name] = _topic_status.pop(old_name)
    save_config()
    if bot:
        try:
            await bot.edit_forum_topic(
                chat_id=config["group_id"],
                message_thread_id=thread_id,
                name=new_display,
            )
        except Exception as e:
            logger.warning(f"Failed to rename TG topic {old_name} → {new_name}: {e}")
    return {"ok": True, "old_name": old_name, "new_name": new_name, "display": new_display, "thread_id": thread_id}


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


# Prefer the top-level orchestrator (no parent) so send_file routes to the scope owner's topic,
# not a sub-orchestrator. Falls back to any orchestrator if no top-level found.
def _find_orch_for_scope(scope: str) -> str | None:
    from app.db import get_all_sessions
    top_level = None
    any_orch = None
    for s in get_all_sessions():
        if s.get("scope", "").rstrip("/") != scope.rstrip("/"):
            continue
        role = s.get("role", "worker")
        if role in ("orchestrator", "sub-orchestrator"):
            if not s.get("parent_name"):
                top_level = s["name"]
            elif any_orch is None:
                any_orch = s["name"]
    return top_level or any_orch


def _find_thread_for_scope(scope: str) -> int | None:
    orch_name = _find_orch_for_scope(scope)
    if orch_name:
        return config["topics"].get(orch_name)
    return None


async def _mirror_send_file(orch_name: str, tg_file, caption: str, is_photo: bool):
    mirror = config.get("mirrors", {}).get(orch_name)
    if not mirror or not bot:
        return
    chat_id = mirror.get("chat_id")
    topic_id = mirror.get("topic_id")
    if not chat_id:
        return
    try:
        if is_photo:
            await bot.send_photo(chat_id, tg_file, caption=caption, message_thread_id=topic_id)
        else:
            await bot.send_document(chat_id, tg_file, caption=caption, message_thread_id=topic_id)
    except Exception as e:
        logger.warning(f"Mirror file send failed for {orch_name}: {e}")


async def send_file_to_tg(path: str, caption: str, scope: str, sender: str, as_document: bool = False) -> dict:
    if not bot or not config["group_id"]:
        return {"error": "TG bridge not active"}
    from pathlib import Path as P
    fp = P(path)
    if not fp.exists():
        return {"error": f"file not found: {path}"}
    file_size = fp.stat().st_size
    if file_size == 0:
        return {"error": f"file is empty (0 bytes): {path}"}
    if file_size > 50 * 1024 * 1024:
        return {"error": "file too large (max 50MB)"}
    topics = config.get("topics", {})
    sender_thread = topics.get(sender) if sender else None
    if sender_thread:
        orch_name = sender
        thread_id = sender_thread
    else:
        orch_name = _find_orch_for_scope(scope)
        thread_id = topics.get(orch_name) if orch_name else None
    logger.info(f"send_file: path={path} size={file_size} scope={scope!r} sender={sender!r} orch={orch_name!r} group_id={config['group_id']} thread_id={thread_id}")
    if not thread_id:
        return {"error": f"no TG topic for scope: {scope}"}
    label = f"📎 {sender}: {caption}" if caption else f"📎 {sender}: {fp.name}"
    label = label[:1024]
    try:
        from aiogram.types import FSInputFile
        tg_file = FSInputFile(path, filename=fp.name)
        is_photo = not as_document and fp.suffix.lower() in _IMAGE_EXTS
        if is_photo:
            msg = await bot.send_photo(config["group_id"], tg_file, caption=label, message_thread_id=thread_id)
        else:
            msg = await bot.send_document(config["group_id"], tg_file, caption=label, message_thread_id=thread_id)
        logger.info(f"send_file: delivered msg_id={msg.message_id} chat_id={msg.chat.id} thread={getattr(msg, 'message_thread_id', None)}")
        if orch_name:
            mirror_file = FSInputFile(path, filename=fp.name)
            await _mirror_send_file(orch_name, mirror_file, label, is_photo)
        return {"ok": True, "message_id": msg.message_id, "chat_id": msg.chat.id}
    except TelegramRetryAfter as e:
        logger.warning(f"send_file flood: retry after {e.retry_after}s")
        await asyncio.sleep(e.retry_after + 0.5)
        try:
            tg_file2 = FSInputFile(path, filename=fp.name)
            if is_photo:
                msg2 = await bot.send_photo(config["group_id"], tg_file2, caption=label, message_thread_id=thread_id)
            else:
                msg2 = await bot.send_document(config["group_id"], tg_file2, caption=label, message_thread_id=thread_id)
            logger.info(f"send_file retry: delivered msg_id={msg2.message_id} chat_id={msg2.chat.id}")
            return {"ok": True, "message_id": msg2.message_id, "chat_id": msg2.chat.id}
        except Exception as e2:
            logger.error(f"send_file retry failed: {e2}")
            return {"error": f"Send failed after flood retry: {e2}"}
    except Exception as e:
        logger.error(f"send_file exception: type={type(e).__name__} err={e}")
        return {"error": str(e)}


_topic_status = {}


def _any_running_in_scope(scope: str) -> bool:
    if not _manager or not scope:
        return False
    for s in _manager.sessions.values():
        if s.scope == scope and s.status.value == "running":
            return True
    return False


async def check_scope_idle(orch_name: str, scope: str):
    if not _any_running_in_scope(scope):
        await _update_topic_status(orch_name, False)


async def notify_scope_running(orch_name: str):
    await _update_topic_status(orch_name, True)


# ── Session hook handlers (wired into app.session by start_bridge) ──

def _find_scope_orch_name(s) -> str | None:
    if s.is_orchestrator:
        return s.name
    if not _manager:
        return None
    for x in _manager.sessions.values():
        if x.is_orchestrator and x.scope == s.scope:
            return x.name
    return None


async def _on_session_scope_idle(s) -> None:
    if not _manager:
        return
    orch_name = _find_scope_orch_name(s)
    if orch_name:
        await check_scope_idle(orch_name, s.scope)


async def _on_session_scope_running(s) -> None:
    if not _manager:
        return
    orch_name = _find_scope_orch_name(s)
    if orch_name:
        await notify_scope_running(orch_name)


async def _sync_all_topic_statuses():
    if not _manager or not bot:
        return
    for s in _manager.sessions.values():
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


# Deduplicated topic icon updates — TG rate-limits edit_forum_topic, so skip if state unchanged
async def _update_topic_status(orch_name: str, is_running: bool):
    if _topic_status.get(orch_name) == is_running:
        return
    _topic_status[orch_name] = is_running
    short = (config.get("topic_names") or {}).get(orch_name) or _short_name(orch_name)
    icon_id = _ICON_RUNNING if is_running else _ICON_IDLE
    thread_id = config["topics"].get(orch_name)
    if thread_id and bot:
        try:
            await bot.edit_forum_topic(chat_id=config["group_id"], message_thread_id=thread_id,
                                       name=short, icon_custom_emoji_id=icon_id)
        except Exception as e:
            logger.debug(f"Topic status update failed: {e}")
    mirror = config.get("mirrors", {}).get(orch_name)
    if mirror and mirror.get("chat_id") and mirror.get("topic_id") and bot:
        try:
            await bot.edit_forum_topic(chat_id=mirror["chat_id"], message_thread_id=mirror["topic_id"],
                                       name=short, icon_custom_emoji_id=icon_id)
        except Exception as e:
            logger.debug(f"Mirror topic status update failed: {e}")


async def _mirror_send(orch_name: str, text: str, entities=None):
    mirrors = config.get("mirrors", {})
    mirror = mirrors.get(orch_name)
    if not mirror or not bot:
        return
    chat_id = mirror.get("chat_id")
    topic_id = mirror.get("topic_id")
    if not chat_id:
        return
    try:
        await bot.send_message(chat_id, text, message_thread_id=topic_id, entities=entities)
    except Exception as e:
        logger.warning(f"Mirror send failed for {orch_name}: {e}")


async def ensure_topics():
    if not bot or not config["group_id"] or not _manager:
        return
    from app.db import get_all_sessions
    orchs = [s for s in get_all_sessions() if s.get("tg_topic") or s.get("role", "worker") in ("orchestrator", "sub-orchestrator")]
    if not orchs:
        return

    for o in orchs:
        name = o["name"]
        if name in config["topics"]:
            continue
        try:
            chosen = _pick_unique_topic_name(name)
            result = await bot.create_forum_topic(chat_id=config["group_id"], name=chosen, icon_custom_emoji_id=_ICON_IDLE)
            config["topics"][name] = result.message_thread_id
            config.setdefault("topic_names", {})[name] = chosen
            save_config()
            logger.info(f"Created topic for {name} as '{chosen}': {result.message_thread_id}")
            asyncio.create_task(stream_logs(name, result.message_thread_id))
        except Exception as e:
            logger.error(f"Failed to create topic for {name}: {e}")

    mirrors = config.get("mirrors", {})
    for name, mirror in mirrors.items():
        if mirror.get("topic_id") is not None:
            continue
        chat_id = mirror.get("chat_id")
        if not chat_id:
            continue
        try:
            short = _short_name(name)
            result = await bot.create_forum_topic(chat_id=chat_id, name=short, icon_custom_emoji_id=_ICON_IDLE)
            mirror["topic_id"] = result.message_thread_id
            save_config()
            logger.info(f"Created mirror topic for {name}: {result.message_thread_id}")
        except Exception as e:
            logger.warning(f"Mirror topic creation failed for {name}: {e}")


_pil_available: bool | None = None


def _check_pil() -> bool:
    global _pil_available
    if _pil_available is None:
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401
            _pil_available = True
        except Exception as e:
            _pil_available = False
            logger.warning(f"Pillow not installed — TG diff/result images disabled. Run `uv sync`. ({e})")
    return _pil_available


def _diff_images_enabled() -> bool:
    return os.getenv("TG_DIFF_IMAGES", "true").lower() not in ("0", "false", "no") and _check_pil()


def _result_images_enabled() -> bool:
    return os.getenv("TG_RESULT_IMAGES", "true").lower() in ("1", "true", "yes") and _check_pil()


async def _send_png_to_tg(png: bytes, chat_id: int, thread_id: int, label: str) -> None:
    """Send PNG bytes as a photo to TG. Temp file cleaned up after send."""
    import uuid, tempfile
    if not png or not bot:
        return
    tmp = os.path.join(tempfile.gettempdir(), f"diff-{uuid.uuid4().hex}.png")
    with open(tmp, "wb") as f:
        f.write(png)
    try:
        from aiogram.types import FSInputFile
        await bot.send_photo(chat_id, FSInputFile(tmp), message_thread_id=thread_id)
    finally:
        try:
            os.unlink(tmp)
        except Exception as e:
            logger.warning(f"tmp diff image cleanup failed ({tmp}): {e}")


async def _send_diff_image(tool_name: str, raw_content: str, chat_id: int, thread_id: int) -> bool:
    """Parse Edit/Write tool call, render diff PNG, send to TG. Returns True if image sent."""
    if not _diff_images_enabled():
        logger.debug("diff images disabled")
        return False
    import json
    try:
        colon = raw_content.index(":")
        params = json.loads(raw_content[colon + 1:].strip())
    except Exception as e:
        logger.debug(f"diff image parse failed for {tool_name}: {e}, raw[:100]={raw_content[:100]}")
        return False
    try:
        from app.diff_image import render_edit_diff, render_write_diff
        if tool_name == "Edit":
            png = render_edit_diff(params.get("file_path", ""), params.get("old_string", ""), params.get("new_string", ""))
        else:  # Write
            png = render_write_diff(params.get("file_path", ""), params.get("content", ""))
        await _send_png_to_tg(png, chat_id, thread_id, tool_name)
        return bool(png)
    except Exception as e:
        logger.warning(f"diff image send failed ({tool_name}): {e}")
        return False


async def _send_result_image(tool_name: str, tool_raw: str, result: str, chat_id: int, thread_id: int) -> bool:
    """Render Read/Grep tool_result as PNG and send to TG. Returns True if image sent."""
    if not _result_images_enabled():
        return False
    try:
        if tool_name == "Read":
            import json
            # tool_raw: "Read: {\"file_path\": ..., \"offset\": ...}"
            try:
                colon = tool_raw.index(":")
                params = json.loads(tool_raw[colon + 1:].strip())
                file_path = params.get("file_path", "")
                offset = int(params.get("offset", 0))
            except Exception:
                file_path = ""
                offset = 0
            from app.diff_image import render_read
            png = render_read(file_path, result, offset)
            await _send_png_to_tg(png, chat_id, thread_id, "Read")

        elif tool_name == "Grep":
            import json, re as _re
            # Parse pattern from tool_raw
            try:
                colon = tool_raw.index(":")
                params = json.loads(tool_raw[colon + 1:].strip())
                pattern = params.get("pattern", "")
            except Exception:
                pattern = ""

            # result format: "path/file.py:42:matching line text\n..."
            # or files_with_matches: just paths
            parsed = []
            for line in result.splitlines():
                # expect "file:lineno:text" format
                m = _re.match(r'^(.+?):(\d+):(.*)$', line)
                if not m:
                    continue  # files_with_matches or no match — skip
                fpath, lineno, text = m.group(1), int(m.group(2)), m.group(3)
                fpath = _re.sub(r'^.*/worktrees/[^/]+/[^/]+/', '', fpath)
                # Find match position in text
                ms, me = 0, len(text)
                if pattern:
                    try:
                        pm = _re.search(pattern, text)
                        if pm:
                            ms, me = pm.start(), pm.end()
                    except Exception as e:
                        logger.debug(f"grep highlight pattern failed: {e}")
                parsed.append((fpath, lineno, text, ms, me))

            if not parsed:
                return False

            from app.diff_image import render_grep
            png = render_grep(pattern, parsed)
            await _send_png_to_tg(png, chat_id, thread_id, "Grep")

        elif tool_name == "Bash":
            import json
            try:
                colon = tool_raw.index(":")
                params = json.loads(tool_raw[colon + 1:].strip())
                command = params.get("command", "")
            except Exception:
                command = ""
            from app.diff_image import render_bash
            png = render_bash(command, result)
            await _send_png_to_tg(png, chat_id, thread_id, "Bash")
        else:
            return False
        return True
    except Exception as e:
        logger.debug(f"result image send failed ({tool_name}): {e}")
        return False


async def stream_logs(orch_name: str, thread_id: int):
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

    from app.db import _conn
    # Dedicated connection per stream loop — avoids sharing state with the request threads
    _poll_conn = _conn()
    logs = get_logs(session_id, after_id=0, conn=_poll_conn)
    last_id = logs[-1]["id"] if logs else 0
    _last_tool_msg = None
    _last_tool_text = ""
    _last_tool_name = ""   # track last tool for result image rendering
    _last_tool_raw = ""    # full raw content of last tool call
    _last_diff_sent = False  # diff image was sent for Edit/Write — skip text tool_result
    _idle_ticks = 0

    try:
        while True:
            try:
                logs = get_logs(session_id, after_id=last_id, conn=_poll_conn)
                _idle_ticks = 0 if logs else _idle_ticks + 1
                for log in logs:
                    if log["id"] <= last_id:
                        continue
                    last_id = log["id"]
                    t, c = log["type"], log["content"]
                    if t in ("text", "tool"):
                        await _update_topic_status(orch_name, True)
                    if t == "user_message":
                        c = re.sub(r'^\[\d{2}:\d{2}\] ', '', c)
                        img_match = re.search(r'(/\S+\.(?:png|jpg|jpeg|gif|webp))', c, re.IGNORECASE)
                        if img_match and Path(img_match.group(1)).is_file():
                            img_path = img_match.group(1)
                            caption = c.replace(img_path, '').strip()[:1024] or None
                            try:
                                from aiogram.types import FSInputFile
                                tg_file = FSInputFile(img_path)
                                await bot.send_photo(config["group_id"], tg_file, caption=caption, message_thread_id=thread_id)
                                mirror = config.get("mirrors", {}).get(orch_name)
                                if mirror and mirror.get("chat_id"):
                                    mirror_file = FSInputFile(img_path)
                                    await bot.send_photo(mirror["chat_id"], mirror_file, caption=caption, message_thread_id=mirror.get("topic_id"))
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
                        for chunk in _split_message(raw_text):
                            try:
                                converted, ents = md_convert(chunk)
                                from aiogram.types import MessageEntity as AioEntity
                                aio_ents = [AioEntity(**e.to_dict()) for e in ents] if ents else None
                                await _tg_send_safe(config["group_id"], converted, thread_id,
                                                    entities=aio_ents, important=True)
                                await _mirror_send(orch_name, converted, entities=aio_ents)
                            except Exception as e:
                                logger.warning(f"text md_convert/send failed, fallback to plain: {e}; chunk[:80]={chunk[:80]!r}")
                                await _tg_send_safe(config["group_id"], chunk, thread_id, important=True)
                                await _mirror_send(orch_name, chunk)
                        continue
                    elif t == "tool":
                        tool_name = c.split(":")[0].strip() if ":" in c else "tool"
                        tool_body = c[len(tool_name)+1:].strip()[:1200] if ":" in c else c[:1200]
                        icon = _tg_tool_icon(tool_name)
                        short = _tg_tool_short(tool_name)
                        header = f"{icon} {short}"
                        _last_tool_text = f"{header}\n{tool_body}"
                        _last_tool_name = tool_name
                        _last_tool_raw = c
                        # Diff image for Edit/Write — if image sent, skip text expandable
                        _diff_sent = False
                        if tool_name in ("Edit", "Write"):
                            _diff_sent = await _send_diff_image(tool_name, c, config["group_id"], thread_id)
                            _last_diff_sent = _diff_sent
                        # Special formatting for send_message — render as pretty HTML
                        # send_message tool: render as readable HTML instead of raw JSON expandable —
                        # the recipient name and message body are the useful parts
                        if not _diff_sent and "send_message" in tool_name:
                            try:
                                import json as _json
                                colon_idx = c.index(":")
                                sm_params = _json.loads(c[colon_idx + 1:].strip())
                                sm_to = sm_params.get("to", "?")
                                sm_msg = sm_params.get("message", "")
                                import re as _re
                                parts_sm = _re.split(r'(```[a-z]*\n?.*?```)', sm_msg, flags=_re.DOTALL)
                                escaped_parts = []
                                for part in parts_sm:
                                    if part.startswith('```'):
                                        inner = _re.sub(r'^```[a-z]*\n?', '', part).rstrip('`').strip()
                                        escaped_parts.append(f"<pre>{inner}</pre>")
                                    else:
                                        escaped_parts.append(part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                                sm_html = "".join(escaped_parts)
                                sm_formatted = f"<b>→ {sm_to}</b>\n\n{sm_html}"
                                if bot:
                                    await bot.send_message(config["group_id"], sm_formatted, message_thread_id=thread_id, parse_mode="HTML")
                            except Exception as _e:
                                logger.debug(f"send_message pretty format failed: {_e}")
                                _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
                        elif not _diff_sent:
                            _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
                        try:
                            m_text, m_ents = md_convert(f"{header}\n{tool_body}")
                            from aiogram.types import MessageEntity as AioEntity
                            await _mirror_send(orch_name, m_text, entities=[AioEntity(**e.to_dict()) for e in m_ents] if m_ents else None)
                        except Exception:
                            await _mirror_send(orch_name, f"{header}\n{tool_body}")
                        continue
                    elif t == "tool_result":
                        if "get_worker_info" in _last_tool_name:
                            try:
                                import json as _json
                                _wi = _json.loads(c)
                                if isinstance(_wi, dict) and _wi.get("result"):
                                    _wi = _json.loads(_wi["result"]) if isinstance(_wi["result"], str) else _wi["result"]
                                pretty = _fmt_worker_info(_wi) if isinstance(_wi, dict) else None
                                if pretty:
                                    await _tg_send_safe(config["group_id"], pretty, thread_id)
                                    await _mirror_send(orch_name, pretty)
                                    _last_tool_msg = None
                                    _last_tool_text = ""
                                    _last_tool_name = ""
                                    _last_tool_raw = ""
                                    continue
                            except Exception as e:
                                logger.debug(f"worker_info pretty-print failed, falling back to raw: {e}")
                        # Edit/Write diff image already sent — skip redundant "file updated" text
                        if _last_diff_sent:
                            _last_diff_sent = False
                            _last_tool_msg = None
                            _last_tool_text = ""
                            _last_tool_name = ""
                            _last_tool_raw = ""
                            continue
                        # Read tool returned an image — send original file instead of base64 spam
                        if _last_tool_name == "Read" and ("'type': 'image'" in c or '"type": "image"' in c or "'type':'image'" in c):
                            try:
                                import json as _json
                                _colon = _last_tool_raw.index(":")
                                _read_params = _json.loads(_last_tool_raw[_colon + 1:].strip())
                                _img_path = _read_params.get("file_path", "")
                                if _img_path and Path(_img_path).is_file():
                                    from aiogram.types import FSInputFile
                                    await bot.send_photo(config["group_id"], FSInputFile(_img_path),
                                                         message_thread_id=thread_id, caption=f"📷 {Path(_img_path).name}")
                                    if _last_tool_msg:
                                        _last_tool_msg = None
                                        _last_tool_text = ""
                                    _last_tool_name = ""
                                    _last_tool_raw = ""
                                    continue
                            except Exception as _e:
                                logger.debug(f"Read image send failed, falling back: {_e}")
                        result_preview = c[:80].replace("\n", " ").strip()
                        result_body = c[:800]
                        # Result image for Read/Grep/Bash — if sent, skip text
                        _result_img_sent = False
                        if _last_tool_name in ("Read", "Grep", "Bash"):
                            _result_img_sent = await _send_result_image(_last_tool_name, _last_tool_raw, c, config["group_id"], thread_id)
                        if not _result_img_sent:
                            if _last_tool_msg:
                                await _edit_tool_with_result(
                                    _last_tool_msg, config["group_id"],
                                    _last_tool_text, f"📎 {result_preview}", result_body,
                                )
                                _last_tool_msg = None
                                _last_tool_text = ""
                            else:
                                await _send_expandable(config["group_id"], thread_id, f"📎 {result_preview}", result_body)
                        else:
                            _last_tool_msg = None
                            _last_tool_text = ""
                        try:
                            m_text, m_ents = md_convert(f"📎 {result_preview}\n{result_body}")
                            from aiogram.types import MessageEntity as AioEntity
                            await _mirror_send(orch_name, m_text, entities=[AioEntity(**e.to_dict()) for e in m_ents] if m_ents else None)
                        except Exception:
                            await _mirror_send(orch_name, f"📎 {result_preview}\n{result_body}")
                        _last_tool_name = ""
                        _last_tool_raw = ""
                        continue
                    elif t == "error":
                        text = f"❌ {c}"
                    elif t == "status":
                        if "turn ended" in c:
                            still_running = _any_running_in_scope(scope)
                            if not still_running:
                                await _update_topic_status(orch_name, False)
                        text = f"⚡ {c}"
                    else:
                        continue
                    is_important = t in ("text", "error", "user_message")
                    for chunk in _split_message(text):
                        try:
                            converted, entities = md_convert(chunk)
                            from aiogram.types import MessageEntity as AioEntity
                            aio_ents = [AioEntity(**e.to_dict()) for e in entities] if entities else None
                            await _tg_send_safe(config["group_id"], converted, thread_id,
                                                entities=aio_ents, important=is_important)
                            await _mirror_send(orch_name, converted, entities=aio_ents)
                        except Exception:
                            await _tg_send_safe(config["group_id"], chunk, thread_id,
                                                important=is_important)
                            await _mirror_send(orch_name, chunk)
            except Exception as e:
                logger.error(f"Stream error for {orch_name}: {e}")
                _idle_ticks = 0
            # Poll faster when active, slow down when idle to save CPU on long-running idle sessions
            await asyncio.sleep(2 if _idle_ticks < 3 else 5)
    finally:
        _poll_conn.close()


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text, lambda msg: msg.text and msg.text.strip() == "/restart")
async def handle_restart(msg: types.Message):
    if msg.chat.id != config.get("group_id"):
        return
    member = await msg.chat.get_member(msg.from_user.id)
    if member.status not in ("administrator", "creator"):
        await msg.reply("⛔ Only admins can restart.")
        return
    await msg.reply("🔄 Перезапуск Orchestra...")
    import subprocess
    subprocess.Popen(["sudo", "systemctl", "restart", "orchestra"])


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.voice)
async def handle_voice(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    t_total = time.monotonic()

    sid, idx = await _register_media(msg, session)
    path = await _download_file(msg.voice.file_id, _media_name("voice", ".oga", msg), msg.voice.file_unique_id)
    tag = _sender_tag(msg)
    if not path:
        await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[voice: file too large]")
        return
    text, err = await _transcribe_audio(path, msg.voice.file_unique_id)
    total_ms = (time.monotonic() - t_total) * 1000
    logger.info(f"handle_voice total={total_ms:.0f}ms duration={msg.voice.duration}s")
    if text:
        await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[voice: {path} | {text}]")
    elif err:
        await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[voice: {path} | ❌ {err}]")
    else:
        await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[voice: {path}]")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.video_note)
async def handle_video_note(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return

    sid, idx = await _register_media(msg, session)
    tag = _sender_tag(msg)
    path = await _download_file(msg.video_note.file_id, _media_name("videonote", ".mp4", msg), msg.video_note.file_unique_id)
    if not path:
        await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[video_note: file too large]")
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
            await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[video_note: {path} | {text}]")
            return
        if err:
            await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[video_note: {path} | ❌ {err}]")
            return
    await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[video_note: {path}]")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.photo)
async def handle_photo(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return

    path = await _download_file(msg.photo[-1].file_id, _media_name("photo", ".jpg", msg), msg.photo[-1].file_unique_id)
    caption = f"\n{msg.caption}" if msg.caption else ""
    tag = f"[photo: {path}]" if path else "[photo: file too large]"
    await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.document)
async def handle_document(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return

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

    path = await _download_file(msg.video.file_id, msg.video.file_name or _media_name("video", ".mp4", msg), msg.video.file_unique_id)
    caption = f"\n{msg.caption}" if msg.caption else ""
    tag = f"[video: {path}]" if path else "[video: file too large]"
    await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.audio)
async def handle_audio(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return

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
    reply_prefix = ""
    if msg.reply_to_message and msg.reply_to_message.text:
        quoted = msg.reply_to_message.text[:200]
        reply_prefix = f"> {quoted}\n\n"
    content = f"{reply_prefix}{_forward_meta(msg)}{msg.text}"
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

    # Wire callbacks regardless of bridge state: handlers no-op while _manager is
    # None, and remove_topics_for_orchs has its own bridge-inactive guard — this
    # preserves the legacy always-callable semantics without session/manager
    # importing tg_bridge.
    from app import session as _session_mod
    _session_mod.on_scope_idle = _on_session_scope_idle
    _session_mod.on_scope_running = _on_session_scope_running
    manager.tg_topics_remover = remove_topics_for_orchs

    load_config()
    token = os.getenv("TG_BRIDGE_TOKEN", "")
    group = int(os.getenv("TG_BRIDGE_GROUP", config.get("group_id", 0)))

    if not token or not group:
        logger.info("TG Bridge disabled (no TG_BRIDGE_TOKEN/TG_BRIDGE_GROUP)")
        return

    _manager = manager
    config["group_id"] = group
    save_config()

    local_api = os.getenv("TG_LOCAL_API_URL", "")
    if local_api:
        import aiohttp as _aio
        for _attempt in range(10):
            try:
                async with _aio.ClientSession() as _s:
                    async with _s.get(local_api, timeout=_aio.ClientTimeout(total=2)):
                        pass
                break
            except Exception:
                logger.info(f"Waiting for Local Bot API ({_attempt+1}/10)...")
                await asyncio.sleep(2)
        from aiogram.client.telegram import TelegramAPIServer
        server = TelegramAPIServer(base=f"{local_api}/bot{{token}}/{{method}}", file=f"{local_api}/file/bot{{token}}/{{path}}")
        from aiogram.client.session.aiohttp import AiohttpSession
        session = AiohttpSession(api=server)
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None), session=session)
        logger.info(f"TG Bot using LOCAL API: {local_api}")
    else:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None))

    _tasks.append(asyncio.create_task(_safe_polling()))
    _tasks.append(asyncio.create_task(_deferred_startup()))
    if local_api:
        _tasks.append(asyncio.create_task(_bot_api_health_loop(local_api)))
    logger.info(f"TG Bridge started (polling immediate, topics deferred) | group={group}")


async def _deferred_startup():
    try:
        await ensure_topics()
        await _sync_all_topic_statuses()
        for name, thread_id in config["topics"].items():
            _tasks.append(asyncio.create_task(stream_logs(name, thread_id)))
        _tasks.append(asyncio.create_task(topic_sync_loop()))
        logger.info(f"TG deferred startup done | topics={len(config['topics'])}")
    except Exception as e:
        logger.error(f"TG deferred startup failed: {e}")


# Health check for the local telegram-bot-api server — restarts it after 3 consecutive failures.
# The local server sometimes hangs without crashing, so polling is the only detection.
async def _bot_api_health_loop(local_api: str):
    import subprocess
    import aiohttp as _aio
    fails = 0
    while True:
        await asyncio.sleep(120)
        try:
            async with _aio.ClientSession() as s:
                async with s.get(local_api, timeout=_aio.ClientTimeout(total=5)) as r:
                    if r.status < 500:
                        fails = 0
                        continue
        except Exception as e:
            # failure detail; the counter warning below is the operational signal
            logger.debug(f"Bot API health probe error: {e}")
        fails += 1
        logger.warning(f"Bot API health check failed ({fails}/3)")
        if fails >= 3:
            logger.error("Bot API unresponsive — restarting telegram-bot-api service")
            subprocess.run(["sudo", "systemctl", "restart", "telegram-bot-api"], capture_output=True)
            fails = 0
            await asyncio.sleep(30)


# Polling loop with auto-restart — network blips or TG downtime shouldn't kill the bridge permanently
async def _safe_polling():
    while True:
        try:
            logger.info("TG polling started")
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"TG polling crashed: {e}, restarting in 10s")
            await asyncio.sleep(10)
        else:
            logger.warning("TG polling exited cleanly, restarting in 5s")
            await asyncio.sleep(5)


async def stop_bridge():
    global bot, _manager
    # unhook so a restarted bridge (or tests) never fire stale callbacks
    from app import session as _session_mod
    _session_mod.on_scope_idle = None
    _session_mod.on_scope_running = None
    if _manager:
        _manager.tg_topics_remover = None
    for t in _tasks:
        t.cancel()
    _tasks.clear()
    if bot:
        await bot.session.close()
    # drop stale refs — a handler racing past the unhook must see inactive state
    bot = None
    _manager = None


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
