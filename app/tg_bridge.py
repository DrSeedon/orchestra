"""Telegram bridge — mirrors Orchestra orchestrators to TG group topics.

Integrated into FastAPI lifespan — no separate process needed.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
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


UPLOADS_MAX_BYTES = int(os.getenv("UPLOADS_MAX_MB", "1024")) * 1024 * 1024


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
    if unique_id and unique_id in _media_cache:
        cached = _media_cache[unique_id]
        if Path(cached).exists():
            return cached
        del _media_cache[unique_id]
    _cleanup_uploads()
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
        if local_api and f.file_path and Path(f.file_path).is_absolute() and Path(f.file_path).exists():
            import shutil
            shutil.copy2(f.file_path, str(path))
            logger.info(f"Local API: copied {f.file_path} → {path}")
        else:
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


async def _send_expandable_return(chat_id: int, thread_id: int, header: str, body: str):
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


async def _send_expandable(chat_id: int, thread_id: int, header: str, body: str):
    from aiogram.types import MessageEntity
    from aiogram.enums import MessageEntityType
    conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
    text = f"{header}\n{conv_body}"
    offset = _utf16_len(header) + 1
    length = _utf16_len(conv_body)
    try:
        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
        await bot.send_message(chat_id, text, message_thread_id=thread_id, entities=entities)
    except Exception:
        try:
            await bot.send_message(chat_id, text, message_thread_id=thread_id)
        except Exception as e:
            logger.warning(f"TG send failed: {e}")


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
    _last_tool_msg = None
    _last_tool_text = ""

    while True:
        try:
            logs = get_logs(session_id, after_id=last_id)
            for log in logs:
                if log["id"] <= last_id:
                    continue
                last_id = log["id"]
                t, c = log["type"], log["content"]
                if t == "user_message" and c.startswith("[from:"):
                    prefix = c.split("]")[0] + "]"
                    body = c[len(prefix):].strip()
                    text = f"📨 {prefix}\n{body[:3000]}"
                elif t == "user_message":
                    text = f"👤 {c[:3000]}"
                elif t == "text":
                    text = f"💬\n{c[:3900]}"
                elif t == "tool":
                    tool_name = c.split(":")[0].strip() if ":" in c else "tool"
                    tool_body = c[len(tool_name)+1:].strip()[:1200] if ":" in c else c[:1200]
                    icon = _tg_tool_icon(tool_name)
                    short = _tg_tool_short(tool_name)
                    header = f"{icon} {short}"
                    _last_tool_text = f"{header}\n{tool_body}"
                    _last_tool_msg = await _send_expandable_return(config["group_id"], thread_id, header, tool_body)
                    continue
                elif t == "tool_result":
                    result_preview = c[:80].replace("\n", " ").strip()
                    result_body = c[:800]
                    if _last_tool_msg:
                        await _edit_tool_with_result(
                            _last_tool_msg, config["group_id"],
                            _last_tool_text, f"📎 {result_preview}", result_body,
                        )
                        _last_tool_msg = None
                        _last_tool_text = ""
                    else:
                        await _send_expandable_return(config["group_id"], thread_id, f"📎 {result_preview}", result_body)
                    continue
                elif t == "error":
                    text = f"❌ {c[:1000]}"
                elif t == "status":
                    text = f"⚡ {c}"
                else:
                    continue
                try:
                    converted, entities = md_convert(text)
                    from aiogram.types import MessageEntity as AioEntity
                    aio_ents = [AioEntity(**e.to_dict()) for e in entities] if entities else None
                    await bot.send_message(
                        config["group_id"], converted,
                        message_thread_id=thread_id,
                        parse_mode=None, entities=aio_ents,
                    )
                except Exception:
                    try:
                        await bot.send_message(
                            config["group_id"], text,
                            message_thread_id=thread_id,
                        )
                    except Exception as e:
                        logger.warning(f"TG send failed: {e}")
        except Exception as e:
            logger.error(f"Stream error for {orch_name}: {e}")
        await asyncio.sleep(2)


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text, lambda msg: msg.text and msg.text.strip() == "/restart")
async def handle_restart(msg: types.Message):
    await msg.reply("🔄 Перезапуск Orchestra...")
    import subprocess
    subprocess.Popen(["sudo", "systemctl", "restart", "orchestra"])


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

    local_api = os.getenv("TG_LOCAL_API_URL", "")
    if local_api:
        from aiogram.client.telegram import TelegramAPIServer
        server = TelegramAPIServer(base=f"{local_api}/bot{{token}}/{{method}}", file=f"{local_api}/file/bot{{token}}/{{path}}")
        from aiogram.client.session.aiohttp import AiohttpSession
        session = AiohttpSession(api=server)
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None), session=session)
        logger.info(f"TG Bot using LOCAL API: {local_api}")
    else:
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
