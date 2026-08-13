"""Telegram bridge — mirrors Orchestra orchestrators to TG group topics.

Integrated into FastAPI lifespan — no separate process needed.
"""

import asyncio
import json
import logging
import os
import re
import time
from collections import Counter, OrderedDict, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.client.default import DefaultBotProperties
from telegramify_markdown import convert as md_convert

from app.errtext import err_text
from app.tasks import spawn_supervised
from app.transcription import transcribe_audio as _transcribe_audio

logger = logging.getLogger("tg-bridge")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())

CONFIG_PATH = Path(__file__).parent.parent / "data" / "tg_bridge.json"
UPLOADS_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_CACHE_PATH = UPLOADS_DIR / ".media_cache.json"

config = {"group_id": 0, "topics": {}, "token": ""}
bot = None
dp = Dispatcher()
_manager = None
_tasks = []
_stream_tasks: dict[tuple[str, int], asyncio.Task] = {}
_topic_status_tasks: dict[str, asyncio.Task] = {}
_topic_status_desired: dict[str, tuple[bool, bool]] = {}
_topic_create_tasks: dict[str, asyncio.Task] = {}
_bridge_tasks: dict[str, asyncio.Task] = {}
_mirror_outboxes: dict[str, asyncio.Queue] = {}
_mirror_tasks: dict[str, asyncio.Task] = {}
_mirror_dropped: dict[str, int] = {}
_mirror_stopping: set[str] = set()


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


def _media_name(prefix: str, ext: str, msg: types.Message) -> str:
    ts = msg.date.strftime("%Y%m%d_%H%M%S") if msg.date else str(msg.message_id)
    return f"{prefix}_{ts}_{msg.message_id}{ext}"


UPLOADS_MAX_BYTES = int(os.getenv("UPLOADS_MAX_MB", "1024")) * 1024 * 1024

# @mention of the owner, delivered on the ORCHESTRATOR turn boundary (#158) so a TG push
# arrives exactly when an orchestrator stopped — but only when that turn explicitly asked
# for it (#241). Accepts "@username" or a numeric user_id; the id renders as a tg://
# text_mention and notifies even when the username does not resolve for the bot.
TG_USER_MENTION = os.getenv("TG_USER_MENTION", "").strip()

# Exact protocol token: broadening this match can silently hide real user-facing text.
TG_SILENT_TURN_MARKER = "[[ORCHESTRA:SILENT_TURN]]"

# Единственный повод дёрнуть юзера (#241). Признак СТРУКТУРНЫЙ — строка журнала должна
# БЫТЬ вызовом тула (`type == "tool"` + это имя в колонке `tool_name`), а не текстом,
# который имя упоминает: иначе тегает любой, кто объясняет устройство тега (замер #161).
TG_NOTIFY_TOOL = "mcp__orchestra__notify_user"
TG_NOTIFY_REASON_MAX = 200


def _mention_markup(mention: str, reason: str = "") -> str:
    """Markdown for the owner mention. Numeric → tg:// link (reliable), else @username.

    `reason` из `notify_user` объясняет, ЗАЧЕМ дёрнули, и обрезается: тег — это сигнал,
    а полный текст причины и так лежит в журнале строкой вызова тула.
    """
    head = (f"[⬆️ ответь](tg://user?id={mention})" if mention.lstrip("-").isdigit()
            else f"⬆️ {mention}")
    reason = " ".join(reason.split())
    if len(reason) > TG_NOTIFY_REASON_MAX:
        reason = reason[:TG_NOTIFY_REASON_MAX].rstrip() + "…"
    return f"{head} — {reason}" if reason else head


def _notify_reason_from_args(content: str) -> str:
    """`reason` из аргументов вызова `notify_user`.

    Разбор — побочная услуга: тег определяется САМИМ фактом вызова, поэтому нечитаемые
    аргументы дают тег без причины. Потеря тега здесь была бы проглоченной просьбой —
    единственное опасное направление отказа в этой задаче.
    """
    _, _, raw = content.partition(":")
    try:
        return str(json.loads(raw).get("reason") or "").strip()
    except Exception:
        return ""


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
    epoch: object = field(default_factory=object)


@dataclass(frozen=True)
class _MediaToken:
    sid: str
    epoch: object
    reservation: object


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
    buf.debounce_task = spawn_supervised(_debounce_elapsed(sid), f"дебаунс доставки {sid}")


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
        buf.epoch = object()

    await _flush_batch(sid, batch)


async def _flush_batch(sid: str, batch: list):
    if not batch:
        return
    valid = [(m, c) for m, c, _reservation in batch if c is not None]
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
    from app.main import mutating_admission_open

    if not mutating_admission_open():
        await _queue_until_restarted(sid, valid, combined)
        return
    try:
        await _manager.send(sid, combined)
    except Exception as error:
        # Недоставку обязан увидеть ЮЗЕР, а не журнал сервера: этот путь вызывается из
        # фоновой задачи дебаунса, и раньше исключение умирало в ней молча (#30, замер:
        # 0 сообщений в чат). Для человека на том конце это неотличимо от «агент прочитал
        # и не ответил».
        await _report_undelivered_to_user(sid, valid, error)


async def _queue_until_restarted(sid: str, valid: list, combined: str) -> None:
    """Restart in progress: park the message instead of pushing it into a dying session (#269).

    Pushing it through would look accepted and then die with the process — for the person on
    the other end that is indistinguishable from being ignored. Queued now, delivered by
    `restart_inbox.deliver_pending` after startup.
    """
    from app import restart_inbox

    first = next((m for m, _c in valid if m is not None), None)
    chat_id = getattr(getattr(first, "chat", None), "id", 0) or 0
    thread_id = getattr(first, "message_thread_id", None) or 0
    try:
        restart_inbox.enqueue(sid, combined, chat_id, thread_id)
    except Exception as error:
        # The queue is the only thing standing between this message and silence: if it fails,
        # deliver the old way rather than drop it, and let the existing path report failure.
        logger.warning("restart inbox unavailable for %s, delivering live: %s", sid, err_text(error))
        try:
            await _manager.send(sid, combined)
        except Exception as send_error:
            await _report_undelivered_to_user(sid, valid, send_error)
        return

    if first is None or bot is None:
        return
    try:
        await _tg_send_safe(
            first.chat.id,
            "⏳ Orchestra перезапускается — сообщение принято, но пока не доставлено. "
            "Ничего делать не нужно: отдам его агенту сам, как только вернусь.",
            thread_id=getattr(first, "message_thread_id", None),
            important=True,
        )
    except Exception as send_error:
        logger.warning("could not tell the user the message is queued for %s: %s",
                       sid, err_text(send_error))


async def _report_undelivered_to_user(sid: str, valid: list, error: Exception) -> None:
    """Один ответ на батч: коротко юзеру в чат, подробности — в журнал и в историю сессии."""
    name = sid
    try:
        session = _manager.get(sid) if _manager else None
        name = getattr(session, "name", None) or sid
    except Exception:
        pass
    detail = err_text(error)
    logger.warning("TG delivery to %s failed, user notified: %s", name, detail)

    # Факт недоставки переживает недоступность TG: строка в истории сессии видна в дашборде,
    # в отличие от строки журнала, которую никто не читает.
    try:
        from app.db import add_log

        add_log(sid, datetime.now(timezone.utc), "system",
                f"[доставка] сообщение из Telegram НЕ доставлено: {detail}")
    except Exception as log_error:
        logger.warning("could not record undelivered message for %s: %s: %s",
                       name, type(log_error).__name__, log_error)

    first = next((m for m, _c in valid if m is not None), None)
    if first is None or bot is None:
        logger.warning("no chat to answer about undelivered message for %s", name)
        return
    text = (
        f"⚠️ Сообщение агенту «{name}» не доставлено — он его не получил.\n"
        f"Повтори через минуту. Техническая причина записана в журнал."
    )
    try:
        await _tg_send_safe(first.chat.id, text,
                            thread_id=getattr(first, "message_thread_id", None),
                            important=True)
    except Exception as send_error:
        logger.warning("could not tell the user about undelivered message for %s: %s: %s",
                       name, type(send_error).__name__, send_error)


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
        buf.entries.append((msg, content, None))
        await _arm_debounce(sid, buf)


# Reserve an identity in the current buffer generation before the download completes.
async def _register_media(msg: types.Message, session) -> _MediaToken:
    sid = session.id
    buf = _get_buf(sid)
    async with buf.lock:
        reservation = object()
        token = _MediaToken(sid, buf.epoch, reservation)
        buf.entries.append((msg, None, reservation))
        buf.pending_media += 1
        await _arm_debounce(sid, buf)
    return token


async def _resolve_media(token: _MediaToken, content: str):
    buf = _buffers.get(token.sid)
    if buf is None:
        return
    flush_batch = None
    async with buf.lock:
        if buf.epoch is not token.epoch:
            return
        idx = next(
            (
                i for i, (_msg, _content, reservation)
                in enumerate(buf.entries)
                if reservation is token.reservation
            ),
            None,
        )
        if idx is None:
            return
        m, _, _reservation = buf.entries[idx]
        buf.entries[idx] = (m, content, None)
        buf.pending_media = max(0, buf.pending_media - 1)
        if buf.pending_media == 0 and buf.phase == _Phase.WAITING_MEDIA:
            batch = list(buf.entries)
            buf.entries.clear()
            buf.phase = _Phase.IDLE
            buf.epoch = object()
            if buf.debounce_task and not buf.debounce_task.done():
                buf.debounce_task.cancel()
            buf.debounce_task = None
            flush_batch = batch
    if flush_batch is not None:
        await _flush_batch(token.sid, flush_batch)




# TG Bot API entity offsets are in UTF-16 code units, not Python's character count or byte count
def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _md_entities(text: str, base_offset: int = 0):
    from aiogram.types import MessageEntity as AioEntity
    try:
        converted, raw_ents = md_convert(text)
        ents = [AioEntity(**{**e.to_dict(), "offset": e.offset + base_offset}) for e in raw_ents] if raw_ents else []
        return converted, ents
    except Exception as e:
        # Молчаливый фолбэк деградирует КАЖДОЕ форматированное TG-сообщение до
        # плоского текста — без лога это выглядит как «Telegram сам так решил».
        logger.warning(f"markdown→entities failed, sending plain: {type(e).__name__}: {e}")
        return text, []




_PROGRESS_MIN_INTERVAL = 5.0     # не чаще одной правки ⚙️ в 5 с: правки едят тот же
                                 # бюджет, что и отправки, ≈20 правок в минуту на группу
_PROGRESS_MAX_LINES = 40         # сколько последних действий видно в свёртке
_PROGRESS_MAX_CHARS = 3500
_ANCHOR_MAX_CHARS = 300
_ACTION_LINE_MAX = 70
# Ширина полосы якоря — в ЗНАКАХ ЭКРАНА телефона, а не в свободном выборе: на 20 знаках
# `━` пузырь переносил её на вторую строку (замерено юзером на живом боте 11.08.2026).
# Единственный владелец числа: правится здесь, нигде больше не дублируется.
_ANCHOR_BAR_WIDTH = 19
_ANCHOR_BAR = "━" * _ANCHOR_BAR_WIDTH
_BASH_WRAPPER = re.compile(r"""^/bin/bash\s+-lc\s+""")


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


_WORKTREE_PREFIX = re.compile(r"^.*/worktrees/[^/]+/[^/]+/")


def _tail_path(path: str, limit: int) -> str:
    """Хвост пути важнее начала: видно файл, а не общий префикс worktree.
    Сам префикс срезается целиком — он одинаков у всех путей агента и съедает строку."""
    path = _WORKTREE_PREFIX.sub("", path.strip())
    return path if len(path) <= limit else "…" + path[-(limit - 1):]


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} б"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} КБ"
    return f"{n / (1024 * 1024):.1f} МБ"


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _line_delta(old: str, new: str) -> tuple[int, int]:
    old_lines = str(old).splitlines()
    new_lines = str(new).splitlines()
    common = 0
    for a, b in zip(old_lines, new_lines):
        if a != b:
            break
        common += 1
    return len(new_lines) - common, len(old_lines) - common


def _file_change_target(params: dict) -> str:
    """Codex пишет правку файла как `FileChange` с unified-diff внутри — Claude пишет
    `Edit`/`Write`. Строка в ленте у них обязана быть одинаковой: замер показал 767
    вызовов `FileChange` против 82 `Edit`/`Write`, и все 767 уезжали сырым патчем."""
    changes = params.get("changes") or []
    if not isinstance(changes, list) or not changes:
        return ""
    first = changes[0] if isinstance(changes[0], dict) else {}
    plus = minus = 0
    for change in changes:
        if not isinstance(change, dict):
            continue
        for line in str(change.get("diff", "")).splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                plus += 1
            elif line.startswith("-") and not line.startswith("---"):
                minus += 1
    path = _tail_path(str(first.get("path", "")), _ACTION_LINE_MAX - 16)
    more = f" +{len(changes) - 1} файл." if len(changes) > 1 else ""
    return f"{path} +{plus} −{minus}{more}"


def _tool_target(tool_name: str, body: str) -> str:
    """Что именно сделал тул — то, ради чего юзер и смотрит строку."""
    try:
        params = json.loads(body.strip())
        if not isinstance(params, dict):
            params = {}
    except Exception:
        params = {}
    short = _tg_tool_short(tool_name)
    if tool_name == "Bash":
        cmd = str(params.get("command", "")).strip()
        m = _BASH_WRAPPER.match(cmd)
        if m:
            cmd = cmd[m.end():].strip()
            quote = cmd[:1]
            if quote in ("'", '"'):
                # Кавычки обёртки снимаем по краям, а не полным совпадением: у живых
                # команд внутри своя мешанина кавычек (`curl -H "..." '"'url'`), и
                # строгий разбор оставлял `/bin/bash -lc '` прямо в ленте.
                cmd = cmd[1:]
                if cmd.endswith(quote):
                    cmd = cmd[:-1]
                if quote == '"':
                    # экранирование ДЛЯ ОБОЛОЧКИ json.loads не снимает
                    cmd = cmd.replace('\\"', '"').replace("\\\\", "\\")
        # Абсолютные пути внутри команды съедают строку целиком, а рабочий каталог
        # агент и так сообщает отдельным полем — режем его префикс.
        cwd = str(params.get("cwd", "")).rstrip("/")
        if cwd:
            cmd = cmd.replace(cwd + "/", "")
        return _WORKTREE_PREFIX.sub("", cmd) or short
    if tool_name == "FileChange":
        return _file_change_target(params) or short
    if tool_name in ("Read", "Write", "Edit", "NotebookEdit"):
        path = _tail_path(str(params.get("file_path", "")), _ACTION_LINE_MAX - 14)
        if tool_name == "Edit":
            plus, minus = _line_delta(params.get("old_string", ""),
                                      params.get("new_string", ""))
            return f"{path} +{plus} −{minus}"
        if tool_name == "Write":
            return f"{path} +{len(str(params.get('content', '')).splitlines())}"
        return path or short
    if tool_name in ("Grep", "Glob"):
        return str(params.get("pattern", "")) or short
    if tool_name in ("WebSearch", "WebFetch"):
        return str(params.get("query") or params.get("url", "")) or short
    if "send_message" in tool_name:
        return f"→ {params.get('to', '?')}: «{params.get('message', '')}»"
    if "spawn_worker" in tool_name:
        model = _MODEL_SHORT.get(params.get("model", ""), params.get("model", ""))
        return f"{params.get('name', '?')} ({model})"
    named = params.get("name") or params.get("par") or params.get("query") or ""
    return f"{short} {named}".strip()


def _tool_line(tool_name: str, body: str) -> str:
    return _shorten(f"{_tg_tool_icon(tool_name)} {_tool_target(tool_name, body)}",
                    _ACTION_LINE_MAX)


def _result_mark(result: str, is_error: bool | None) -> str:
    """Хвост строки действия: чем кончилось. Размер — по сырому ответу тула."""
    if is_error:
        first = next((ln for ln in result.splitlines() if ln.strip()), "ошибка")
        return f"✗ {_shorten(first, 18)}"
    return f"{_human_size(len(result))} ✓"


def _progress_text(lines: list[str], total: int, seconds: float) -> str:
    """Тело ⚙️: заголовок со счётчиком и свёрнутый список действий."""
    head = f"⚙️ {total} {_plural(total, 'действие', 'действия', 'действий')}"
    if seconds >= 60:
        head += f" · {int(seconds // 60)} мин"
    shown = lines[-_PROGRESS_MAX_LINES:]
    if len(lines) > len(shown):
        shown = [f"…ещё {len(lines) - len(shown)} выше"] + shown
    body = "\n".join(shown)
    # Лимит Telegram считается в UTF-16, а не в символах: строка из эмодзи вдвое
    # тяжелее на вид одинаковой. Правка сообщения не режется общим кодом, поэтому
    # перебор потолка вернул бы `message is too long` вместо текста.
    while _utf16_len(body) > _PROGRESS_MAX_CHARS:
        cut = body.find("\n", 1)
        body = body[cut + 1:] if cut > 0 else body[:_PROGRESS_MAX_CHARS // 2]
    return f"{head}\n{body}"


def _turn_anchor(actions: list[str], seconds: float, status: str) -> str:
    """Якорь конца хода. КОРОТКИЙ намеренно: он идёт по надёжной полосе, и длинный
    текст `_formatted_chunks` порежет на пачку надёжных отправок — ровно то, чем
    однажды встала вся исходящая очередь."""
    n = len(actions)
    parts = [f"ход окончен · {int(seconds // 60)} мин"
             if seconds >= 60 else "ход окончен",
             f"{n} {_plural(n, 'действие', 'действия', 'действий')}"]
    tally = Counter(line.split(" ", 1)[0] for line in actions)
    if tally:
        parts.append(" · ".join(f"{icon}×{cnt}" for icon, cnt in tally.most_common(3)))
    cost = re.search(r"\$[\d.]+ turn", status)
    if cost:
        parts.append(cost.group(0).replace(" turn", ""))
    return _shorten(_ANCHOR_BAR + "\n" + " · ".join(parts),
                    _ANCHOR_MAX_CHARS).replace("━ ", "━\n", 1)


# Статусы движка. По умолчанию НИ ОДИН не уходит отдельным сообщением: за сутки их 190
# из 275, и это внутренняя телеметрия. Понадобилось сделать статус надёжным — впиши его
# строку в _STATUS_RELIABLE, больше менять нечего.
_STATUS_RELIABLE: frozenset[str] = frozenset()
_STATUS_AS_ACTION = {
    "message steered into active Codex turn": "↪ сообщение вошло в текущий ход",
    "waiting for bg jobs": "⏸ жду фоновые задачи",
}


@dataclass
class _TurnState:
    """Ход целиком. ИДЕМПОТЕНТНО ПО log.id — это не украшение: при перегрузке очереди
    `stream_logs` ловит `_TgDeliveryOverloaded`, откатывает курсор и переигрывает уже
    обработанные строки. Список, в который дописывают, дал бы дубли действий и второй
    якорь; словари по id при повторе просто перезаписываются."""
    actions: dict[int, str] = field(default_factory=dict)      # log.id вызова → строка
    raw: dict[int, str] = field(default_factory=dict)          # log.id вызова → тело
    names: dict[int, str] = field(default_factory=dict)        # log.id вызова → имя тула
    marks: dict[int, str] = field(default_factory=dict)        # log.id вызова → хвост
    result_of: dict[int, int] = field(default_factory=dict)    # log.id результата → вызова
    by_tool_id: dict[str, int] = field(default_factory=dict)   # tool_use_id → log.id
    open_ids: list[int] = field(default_factory=list)          # вызовы без результата
    block: list[int] = field(default_factory=list)             # что показывает текущее ⚙️
    started: float = 0.0
    block_seq: int = 0
    msg_id: int | None = None
    last_edit: float = 0.0
    last_text: str = ""
    anchor_sent_for: int | None = None

    def add(self, log_id: int, line: str, tool_use_id: str = "") -> None:
        if not self.actions:
            self.started = time.time()
        if log_id not in self.actions:
            self.block.append(log_id)
            self.open_ids.append(log_id)
        self.actions[log_id] = line
        if tool_use_id:
            self.by_tool_id[tool_use_id] = log_id

    def resolve(self, result_id: int, tool_use_id: str) -> int | None:
        """Какому вызову принадлежит этот результат."""
        action_id = self.result_of.get(result_id)
        if action_id is not None:
            return action_id
        if tool_use_id and tool_use_id in self.by_tool_id:
            return self.by_tool_id[tool_use_id]
        return self.open_ids[0] if self.open_ids else None

    def close(self, result_id: int, tool_use_id: str, mark: str) -> None:
        """Дописать итог к СВОЕЙ строке действия.

        Пара берётся по `tool_use_id` (пишется с #174 для обеих строк). Пусто — старая
        строка журнала: тогда к самому старому незакрытому вызову, FIFO. Это честная
        деградация, а не догадка: при параллельных тулах порядок неизвестен, и лучше
        детерминированная привязка, чем правдоподобная.
        """
        action_id = self.resolve(result_id, tool_use_id)
        if action_id is None:
            return
        if result_id not in self.result_of:
            self.result_of[result_id] = action_id
            self.by_tool_id.pop(tool_use_id, None)
            if action_id in self.open_ids:
                self.open_ids.remove(action_id)
        self.marks[action_id] = mark

    def line(self, log_id: int) -> str:
        mark = self.marks.get(log_id)
        return f"{self.actions[log_id]}  {mark}" if mark else self.actions[log_id]

    def lines(self) -> list[str]:
        return [self.line(i) for i in self.block if i in self.actions]

    def all_lines(self) -> list[str]:
        return [self.line(i) for i in sorted(self.actions)]

    def new_block(self) -> None:
        """Текст юзеру закрывает ⚙️: следующая пачка действий заводит своё сообщение,
        иначе счётчик застывает выше по ленте, вдалеке от свежего текста."""
        self.block = []
        self.block_seq += 1
        self.msg_id = None
        self.last_text = ""

    def reset(self) -> None:
        self.__init__()


async def _update_progress(
    state: _TurnState, thread_id: int, orch_name: str, *, force: bool = False,
) -> None:
    """Одно сообщение ⚙️ на пачку действий, дальше — правки на месте.

    Правки тратят тот же бюджет Bot API, что и отправки (≈20 правок в минуту на группу),
    поэтому: не чаще одной в _PROGRESS_MIN_INTERVAL, никогда с прежним текстом (иначе
    `message is not modified`) и с собственным ключом коалесцирования — очередь схлопнет
    пачку правок в одну, отдав самый свежий текст.
    """
    if not state.block:
        return
    text = _progress_text(state.lines(), len(state.actions),
                          time.time() - state.started)
    if text == state.last_text:
        return
    now = time.time()
    if not force and now - state.last_edit < _PROGRESS_MIN_INTERVAL:
        return
    head, _, body = text.partition("\n")
    if state.msg_id is None:
        sent = await _send_expandable(
            config["group_id"], thread_id, head, body,
            telemetry_key=("progress", thread_id, orch_name, state.block_seq),
        )
        # message_id разрешаем БЕЗ ожидания в потоке: ждать доставки здесь — задержать
        # весь журнал агента. Не разрешился (косметику выбросили) → правок не будет.
        if isinstance(sent, asyncio.Future):
            def _remember(f, s=state, seq=state.block_seq):
                # Пачка могла смениться, пока сообщение ехало: чужой message_id заставил
                # бы следующую пачку править предыдущее ⚙️ вместо своего.
                if f.cancelled() or f.exception() is not None or s.block_seq != seq:
                    return
                s.msg_id = getattr(f.result(), "message_id", None)
            sent.add_done_callback(_remember)
        else:
            state.msg_id = getattr(sent, "message_id", None)
    else:
        await _tg_edit_message_safe(
            config["group_id"], state.msg_id, text,
            telemetry_key=("progress-edit", thread_id, orch_name, state.block_seq),
        )
    state.last_edit = now
    state.last_text = text


# Expandable blockquote wraps the body so long tool outputs are collapsed by default in TG.
# Falls back to plain text if the Bot API version doesn't support EXPANDABLE_BLOCKQUOTE.
async def _send_expandable(
    chat_id: int,
    thread_id: int,
    header: str,
    body: str,
    *,
    important: bool = False,
    telemetry_key=None,
    batch_bucket=None,
):
    from aiogram.types import MessageEntity
    from aiogram.enums import MessageEntityType
    body = body.rstrip()
    conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
    text = f"{header}\n{conv_body}"
    offset = _utf16_len(header) + 1
    length = _utf16_len(conv_body)
    entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
    return await _tg_send_safe(
        chat_id,
        text,
        thread_id,
        entities=entities,
        important=important,
        telemetry_key=telemetry_key,
        batch_bucket=batch_bucket,
    )


TG_MSG_LIMIT = 4096


def _split_message(text: str, limit: int = TG_MSG_LIMIT) -> list[str]:
    if _utf16_len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if _utf16_len(text) <= limit:
            chunks.append(text)
            break
        # Find a newline to cut at, but measure in UTF-16 units (TG's native encoding)
        cut = -1
        for i in range(min(len(text), limit) - 1, limit // 4, -1):
            if text[i] == '\n' and _utf16_len(text[:i]) <= limit:
                cut = i
                break
        if cut < 0:
            # No good newline — binary search for the last char that fits
            lo, hi = limit // 4, min(len(text), limit + 256)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if _utf16_len(text[:mid]) <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            cut = lo
        chunks.append(text[:cut])
        text = text[cut:].lstrip('\n')
    return chunks


def _formatted_chunks(text: str) -> list[tuple[str, list | None]]:
    """Convert first, then enforce Telegram's limit on the final payload."""
    converted, entities = _md_entities(text)
    if _utf16_len(converted) <= TG_MSG_LIMIT:
        return [(converted, entities or None)]
    return [(chunk, None) for chunk in _split_message(converted)]


_TG_GROUP_INTERVAL = 1.05
_TG_PRIVATE_INTERVAL = 1.05
_TG_GROUP_WINDOW_SECONDS = 60.0
_TG_GROUP_WINDOW_MAX = 20
_TG_IMPORTANT_ATTEMPTS = 3
_TG_NETWORK_RETRY_DELAY = 1.0
_TG_RETRY_AFTER_MARGIN = 0.25
_TG_RELIABLE_QUEUE_MAX = 256
_TG_RELIABLE_ADMISSION_MAX = 64
_TG_RELIABLE_ADMISSION_TIMEOUT = 5.0
_TG_RELIABLE_CALL_TIMEOUT = 30.0
_TG_TELEMETRY_MAX_KEYS = 128
_TG_TELEMETRY_MAX_AGE = 15.0
_TG_TELEMETRY_CALL_TIMEOUT = 2.0
_TG_OPTIONAL_QUEUE_MAX = 64
_TG_IMAGE_QUEUE_MAX = 16
_TG_IMAGE_CALL_TIMEOUT = 30.0
_TG_MIRROR_OUTBOX_MAX = 64
_TG_ENTITY_REJECTED = object()


@dataclass(frozen=True)
class _TgSendEntityRejected:
    text: str
    thread_id: int | None


class _TgDeliveryOverloaded(RuntimeError):
    pass


@dataclass
class _TgCallItem:
    call_factory: object
    important: bool
    label: str
    future: asyncio.Future
    enqueued_at: float
    key: object = None
    version: int = 1
    count: int = 1
    in_flight: bool = False
    optional_kind: str | None = None
    traffic_class: str | None = None
    call_timeout: float | None = None
    count_lost: bool = True
    retry_ambiguous: bool | None = None
    reservation: object = None
    sequence: int = 0
    ordered: bool = False


@dataclass
class _TgDeliveryState:
    loop: asyncio.AbstractEventLoop
    reliable: deque = field(default_factory=deque)
    telemetry: OrderedDict = field(default_factory=OrderedDict)
    optional: deque = field(default_factory=deque)
    images: deque = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    image_wake: asyncio.Event = field(default_factory=asyncio.Event)
    space: asyncio.Event = field(default_factory=asyncio.Event)
    rate_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    rate_history: deque = field(default_factory=deque)
    dispatcher: asyncio.Task | None = None
    image_dispatcher: asyncio.Task | None = None
    in_flight: _TgCallItem | None = None
    image_in_flight: _TgCallItem | None = None
    image_reservations: set = field(default_factory=set)
    ordered_admissions: set[int] = field(default_factory=set)
    admission_waiters: int = 0
    admission_tasks: set = field(default_factory=set)
    image_admission_tasks: set = field(default_factory=set)
    telemetry_coalesced: int = 0
    telemetry_dropped: int = 0
    optional_images: int = 0
    optional_dropped: int = 0
    reliable_overflow: int = 0
    reliable_retries: int = 0
    reliable_timeouts: int = 0
    reliable_total_timeouts: int = 0
    reliable_lost: int = 0
    telemetry_timeouts: int = 0
    telemetry_lost: int = 0
    optional_timeouts: int = 0
    optional_lost: int = 0
    image_dropped: int = 0
    image_timeouts: int = 0
    image_lost: int = 0
    reliable_last_latency: float = 0.0
    reliable_max_latency: float = 0.0
    telemetry_last_latency: float = 0.0
    telemetry_max_latency: float = 0.0
    optional_last_latency: float = 0.0
    optional_max_latency: float = 0.0
    image_last_latency: float = 0.0
    image_max_latency: float = 0.0
    stopped: bool = False


_tg_delivery_states: dict[int, _TgDeliveryState] = {}
_tg_dispatch_tasks: dict[int, asyncio.Task] = {}
_tg_queue_loops: dict[int, asyncio.AbstractEventLoop] = {}
_tg_result_tasks: set[asyncio.Task] = set()
_tg_result_wrappers: dict[asyncio.Future, asyncio.Task] = {}
_tg_flood_until: dict[int, float] = {}
_tg_last_send: dict[int, float] = {}
_tg_call_sequence = 0


def _settle_tg_item(item: _TgCallItem | None, result=None) -> None:
    if item is not None and not item.future.done():
        item.future.set_result(result)


async def _clear_tg_chat(
    chat_id: int,
    expected_state: _TgDeliveryState | None = None,
) -> None:
    state = _tg_delivery_states.get(chat_id)
    if expected_state is not None and state is not expected_state:
        return
    registered_task = _tg_dispatch_tasks.get(chat_id)
    if state is None or registered_task is state.dispatcher:
        _tg_dispatch_tasks.pop(chat_id, None)
    owned_tasks = []
    if state:
        state.stopped = True
        state.wake.set()
        state.image_wake.set()
        state.space.set()
        for item in state.reliable:
            _settle_tg_item(item)
        for item in state.telemetry.values():
            _settle_tg_item(item)
        for item in state.optional:
            _settle_tg_item(item)
        for item in state.images:
            _settle_tg_item(item)
        _settle_tg_item(state.in_flight)
        _settle_tg_item(state.image_in_flight)
        state.reliable.clear()
        state.telemetry.clear()
        state.optional.clear()
        state.images.clear()
        state.image_reservations.clear()
        state.ordered_admissions.clear()
        for task in (state.dispatcher, state.image_dispatcher, registered_task):
            if task is not None and task not in owned_tasks:
                owned_tasks.append(task)
        admission_tasks = [
            waiter for waiter in state.admission_tasks
            if waiter is not asyncio.current_task()
        ]
        if admission_tasks:
            await asyncio.gather(*admission_tasks, return_exceptions=True)
        image_admission_tasks = [
            task for task in state.image_admission_tasks
            if task is not asyncio.current_task()
        ]
        if image_admission_tasks:
            await asyncio.gather(*image_admission_tasks, return_exceptions=True)
    elif registered_task is not None:
        owned_tasks.append(registered_task)
    current = asyncio.current_task()
    for task in owned_tasks:
        if task is current or task.done():
            continue
        try:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except RuntimeError:
            pass
    if _tg_delivery_states.get(chat_id) is state:
        _tg_delivery_states.pop(chat_id, None)
        _tg_queue_loops.pop(chat_id, None)
        _tg_flood_until.pop(chat_id, None)
        _tg_last_send.pop(chat_id, None)


async def _reset_tg_delivery_state() -> None:
    global _tg_call_sequence
    for chat_id in list(_tg_delivery_states):
        await _clear_tg_chat(chat_id)
    if _tg_result_tasks:
        await asyncio.gather(*list(_tg_result_tasks), return_exceptions=True)
    _tg_result_tasks.clear()
    _tg_result_wrappers.clear()
    _tg_tool_batches.clear()
    _tg_call_sequence = 0


def _tg_delivery_snapshot(chat_id: int) -> dict[str, int | float]:
    state = _tg_delivery_states.get(chat_id)
    if not state:
        return {
            "reliable_queued": 0,
            "reliable_admission_waiters": 0,
            "reliable_overflow": 0,
            "reliable_retries": 0,
            "reliable_timeouts": 0,
            "reliable_total_timeouts": 0,
            "reliable_lost": 0,
            "reliable_oldest_age": 0.0,
            "reliable_last_latency": 0.0,
            "reliable_max_latency": 0.0,
            "telemetry_pending": 0,
            "telemetry_coalesced": 0,
            "telemetry_dropped": 0,
            "telemetry_timeouts": 0,
            "telemetry_lost": 0,
            "telemetry_oldest_age": 0.0,
            "telemetry_last_latency": 0.0,
            "telemetry_max_latency": 0.0,
            "optional_queued": 0,
            "optional_images": 0,
            "optional_dropped": 0,
            "optional_timeouts": 0,
            "optional_lost": 0,
            "optional_oldest_age": 0.0,
            "optional_last_latency": 0.0,
            "optional_max_latency": 0.0,
            "image_reserved": 0,
            "image_queued": 0,
            "image_in_flight": 0,
            "image_dropped": 0,
            "image_timeouts": 0,
            "image_lost": 0,
            "image_oldest_age": 0.0,
            "image_last_latency": 0.0,
            "image_max_latency": 0.0,
        }
    now = state.loop.time()

    def oldest_age(items) -> float:
        enqueued = [item.enqueued_at for item in items]
        return max(0.0, now - min(enqueued)) if enqueued else 0.0

    return {
        "reliable_queued": len(state.reliable),
        "reliable_admission_waiters": state.admission_waiters,
        "reliable_overflow": state.reliable_overflow,
        "reliable_retries": state.reliable_retries,
        "reliable_timeouts": state.reliable_timeouts,
        "reliable_total_timeouts": state.reliable_total_timeouts,
        "reliable_lost": state.reliable_lost,
        "reliable_oldest_age": oldest_age(state.reliable),
        "reliable_last_latency": state.reliable_last_latency,
        "reliable_max_latency": state.reliable_max_latency,
        "telemetry_pending": len(state.telemetry),
        "telemetry_coalesced": state.telemetry_coalesced,
        "telemetry_dropped": state.telemetry_dropped,
        "telemetry_timeouts": state.telemetry_timeouts,
        "telemetry_lost": state.telemetry_lost,
        "telemetry_oldest_age": oldest_age(state.telemetry.values()),
        "telemetry_last_latency": state.telemetry_last_latency,
        "telemetry_max_latency": state.telemetry_max_latency,
        "optional_queued": len(state.optional),
        "optional_images": state.optional_images,
        "optional_dropped": state.optional_dropped,
        "optional_timeouts": state.optional_timeouts,
        "optional_lost": state.optional_lost,
        "optional_oldest_age": oldest_age(state.optional),
        "optional_last_latency": state.optional_last_latency,
        "optional_max_latency": state.optional_max_latency,
        "image_reserved": len(state.image_reservations),
        "image_queued": len(state.images),
        "image_in_flight": int(state.image_in_flight is not None),
        "image_dropped": state.image_dropped,
        "image_timeouts": state.image_timeouts,
        "image_lost": state.image_lost,
        "image_oldest_age": oldest_age(state.images),
        "image_last_latency": state.image_last_latency,
        "image_max_latency": state.image_max_latency,
    }


def _tg_delivery_snapshots() -> dict[str, list[dict[str, int | float]]]:
    return {
        "chats": [
            {"chat_id": chat_id, **_tg_delivery_snapshot(chat_id)}
            for chat_id in sorted(_tg_delivery_states)
        ],
    }


def _tg_interval(chat_id: int) -> float:
    return _TG_GROUP_INTERVAL if chat_id < 0 else _TG_PRIVATE_INTERVAL


async def _tg_delivery_state_for(chat_id: int) -> _TgDeliveryState:
    loop = asyncio.get_running_loop()
    while True:
        state = _tg_delivery_states.get(chat_id)
        if state is None:
            state = _TgDeliveryState(loop=loop)
            _tg_delivery_states[chat_id] = state
            _tg_queue_loops[chat_id] = loop
            return state
        if state.loop is loop and not state.stopped:
            _tg_queue_loops[chat_id] = loop
            return state
        await _clear_tg_chat(chat_id, state)


def _track_tg_result(coro) -> asyncio.Task:
    task = spawn_supervised(coro, "отправка результата в TG")
    _tg_result_tasks.add(task)
    task.add_done_callback(_tg_result_tasks.discard)
    return task


def _tg_rate_wait(
    chat_id: int,
    state: _TgDeliveryState,
    now: float,
) -> float:
    if chat_id < 0:
        while (
            state.rate_history
            and now - state.rate_history[0] >= _TG_GROUP_WINDOW_SECONDS
        ):
            state.rate_history.popleft()
    waits = [
        0,
        _tg_flood_until.get(chat_id, 0) - now,
        _tg_interval(chat_id) - (now - _tg_last_send.get(chat_id, 0)),
    ]
    if chat_id < 0 and len(state.rate_history) >= _TG_GROUP_WINDOW_MAX:
        waits.append(
            state.rate_history[0] + _TG_GROUP_WINDOW_SECONDS - now,
        )
    wait = max(waits)
    return wait if wait > 1e-9 else 0


async def _tg_reserve_rate_slot(
    chat_id: int,
    state: _TgDeliveryState,
    *,
    wait_for_slot: bool = True,
) -> bool | None:
    async with state.rate_lock:
        while not state.stopped:
            wait = _tg_rate_wait(chat_id, state, state.loop.time())
            if not wait:
                reserved_at = state.loop.time()
                _tg_last_send[chat_id] = reserved_at
                if chat_id < 0:
                    state.rate_history.append(reserved_at)
                return True
            if not wait_for_slot:
                return None
            await asyncio.sleep(wait)
        return False


def _tg_record_latency(
    state: _TgDeliveryState,
    traffic_class: str,
    item: _TgCallItem,
) -> None:
    latency = max(0.0, state.loop.time() - item.enqueued_at)
    setattr(state, f"{traffic_class}_last_latency", latency)
    maximum = getattr(state, f"{traffic_class}_max_latency")
    setattr(state, f"{traffic_class}_max_latency", max(maximum, latency))


async def _tg_run_attempts(
    chat_id: int,
    state: _TgDeliveryState,
    call,
    important: bool,
    label: str,
    traffic_class: str,
    *,
    call_timeout: float | None = None,
    count_lost: bool = True,
    retry_ambiguous: bool | None = None,
    drop_count: int = 1,
):
    loop = state.loop
    attempts = _TG_IMPORTANT_ATTEMPTS if important else 1
    retry_ambiguous = important if retry_ambiguous is None else retry_ambiguous
    for attempt in range(1, attempts + 1):
        reserved = await _tg_reserve_rate_slot(
            chat_id,
            state,
            wait_for_slot=important,
        )
        if reserved is None:
            counter = f"{traffic_class}_dropped"
            if not hasattr(state, counter):
                counter = "optional_dropped"
            setattr(state, counter, getattr(state, counter) + drop_count)
            logger.warning(f"TG {label} dropped: rate slot unavailable")
            return None
        if not reserved:
            return None
        try:
            timeout = call_timeout or (
                _TG_RELIABLE_CALL_TIMEOUT
                if important else _TG_TELEMETRY_CALL_TIMEOUT
            )
            async with asyncio.timeout(timeout):
                return await call()
        except TimeoutError:
            setattr(
                state,
                f"{traffic_class}_timeouts",
                getattr(state, f"{traffic_class}_timeouts") + 1,
            )
            if important and retry_ambiguous and attempt < attempts:
                state.reliable_retries += 1
                logger.warning(
                    f"TG {label} attempt timeout, retry {attempt + 1}/{attempts}"
                )
                if _TG_NETWORK_RETRY_DELAY:
                    await asyncio.sleep(_TG_NETWORK_RETRY_DELAY * attempt)
                continue
            if important:
                if count_lost:
                    setattr(
                        state,
                        f"{traffic_class}_lost",
                        getattr(state, f"{traffic_class}_lost") + 1,
                    )
                logger.warning(f"TG {label} LOST after {attempt} timed out attempts")
            else:
                if count_lost:
                    setattr(
                        state,
                        f"{traffic_class}_lost",
                        getattr(state, f"{traffic_class}_lost") + 1,
                    )
                logger.warning(f"TG {label} {traffic_class} timeout")
            return None
        except TelegramRetryAfter as e:
            # max(): concurrent 429s must never shorten an already longer barrier —
            # a smaller retry_after arriving second would let us knock early and re-ban
            _tg_flood_until[chat_id] = max(
                _tg_flood_until.get(chat_id, 0),
                loop.time() + e.retry_after + _TG_RETRY_AFTER_MARGIN,
            )
            logger.warning(f"TG {label} flood: retry in {e.retry_after}s")
            if not important:
                if count_lost:
                    setattr(
                        state,
                        f"{traffic_class}_lost",
                        getattr(state, f"{traffic_class}_lost") + 1,
                    )
                return None
            if attempt == attempts:
                break
            state.reliable_retries += 1
        except (TelegramNetworkError, TelegramServerError) as e:
            if important and retry_ambiguous and attempt < attempts:
                state.reliable_retries += 1
                logger.warning(
                    f"TG {label} ambiguous delivery, retry {attempt + 1}/{attempts}: "
                    f"{type(e).__name__}: {e}"
                )
                await asyncio.sleep(_TG_NETWORK_RETRY_DELAY * attempt)
                continue
            if important:
                if count_lost:
                    setattr(
                        state,
                        f"{traffic_class}_lost",
                        getattr(state, f"{traffic_class}_lost") + 1,
                    )
                logger.warning(
                    f"TG {label} LOST after {attempt} attempts: "
                    f"{type(e).__name__}: {e}"
                )
            else:
                if count_lost:
                    setattr(
                        state,
                        f"{traffic_class}_lost",
                        getattr(state, f"{traffic_class}_lost") + 1,
                    )
                logger.warning(f"TG {label} failed: {type(e).__name__}: {e}")
            return None
        except Exception as e:
            if important:
                if count_lost:
                    setattr(
                        state,
                        f"{traffic_class}_lost",
                        getattr(state, f"{traffic_class}_lost") + 1,
                    )
                logger.warning(f"TG {label} LOST: {type(e).__name__}: {e}")
            else:
                if count_lost:
                    setattr(
                        state,
                        f"{traffic_class}_lost",
                        getattr(state, f"{traffic_class}_lost") + 1,
                    )
                logger.warning(f"TG {label} failed: {type(e).__name__}: {e}")
            return None

    if important:
        if count_lost:
            setattr(
                state,
                f"{traffic_class}_lost",
                getattr(state, f"{traffic_class}_lost") + 1,
            )
        logger.warning(f"TG {label} LOST after {attempts} flood attempts")
    return None


async def _tg_run_call(
    chat_id: int,
    state: _TgDeliveryState,
    call,
    important: bool,
    label: str,
    traffic_class: str,
    *,
    call_timeout: float | None = None,
    count_lost: bool = True,
    retry_ambiguous: bool | None = None,
    drop_count: int = 1,
):
    if not important:
        return await _tg_run_attempts(
            chat_id,
            state,
            call,
            False,
            label,
            traffic_class,
            call_timeout=call_timeout,
            count_lost=count_lost,
            retry_ambiguous=retry_ambiguous,
            drop_count=drop_count,
        )
    return await _tg_run_attempts(
        chat_id,
        state,
        call,
        True,
        label,
        traffic_class,
        call_timeout=call_timeout,
        count_lost=count_lost,
        retry_ambiguous=retry_ambiguous,
        drop_count=drop_count,
    )


def _tg_ordered_sequences(state: _TgDeliveryState) -> list[int]:
    sequences = [
        item.sequence
        for item in state.reliable
        if item.ordered and not item.future.cancelled()
    ]
    if state.in_flight is not None and state.in_flight.ordered:
        sequences.append(state.in_flight.sequence)
    sequences.extend(state.ordered_admissions)
    return sequences


def _tg_first_ordered_sequence(state: _TgDeliveryState) -> int | None:
    sequences = _tg_ordered_sequences(state)
    return min(sequences) if sequences else None


def _is_background_subagent(content: str) -> bool:
    """True for background Bash tasks riding the `subagent_end` event.

    One event type, two entities: real delegated subagents (local_agent/codex)
    and background Bash. Prefer the explicit type; older rows leave it empty,
    so fall back to the id shape (`b…` = bash, `a…` = agent).
    """
    if "type=local_bash" in content:
        return True
    if "type=local_agent" in content or "type=codex" in content:
        return False
    for part in content.split("|"):
        part = part.strip()
        if part.startswith("id="):
            return part[3:].startswith("b")
    return False


_tg_tool_batches: dict = {}


def _tg_tool_batch(thread_id, orch_name) -> list:
    """Накопитель тел тул-сообщений для одного (топик, агент).

    Живёт между вызовами, потому что схлопывание в очереди происходит уже
    ПОСЛЕ возврата из _tg_send_safe: пока предыдущее сообщение не ушло,
    следующие дописываются в тот же bucket и уезжают вместе с ним.
    """
    return _tg_tool_batches.setdefault(("tool", thread_id, orch_name), [])


def _tg_oldest_telemetry(state: _TgDeliveryState, now: float):
    barrier = _tg_first_ordered_sequence(state)
    eligible = [
        item for item in state.telemetry.values()
        if not item.in_flight
        and (barrier is None or item.sequence < barrier)
    ]
    return min(eligible, key=lambda item: item.enqueued_at) if eligible else None


def _tg_drop_stale_cosmetics(state: _TgDeliveryState, now: float) -> None:
    if _TG_TELEMETRY_MAX_AGE <= 0:
        return
    expired_telemetry = [
        (key, item)
        for key, item in state.telemetry.items()
        if not item.in_flight
        and now - item.enqueued_at >= _TG_TELEMETRY_MAX_AGE
    ]
    for key, item in expired_telemetry:
        if state.telemetry.get(key) is item:
            state.telemetry.pop(key)
            state.telemetry_dropped += item.count
            _settle_tg_item(item)
    fresh_optional = deque()
    while state.optional:
        item = state.optional.popleft()
        if now - item.enqueued_at < _TG_TELEMETRY_MAX_AGE:
            fresh_optional.append(item)
            continue
        if item.optional_kind == "image":
            state.optional_images -= 1
        state.optional_dropped += 1
        _settle_tg_item(item)
    state.optional = fresh_optional


def _tg_next_telemetry_wait(state: _TgDeliveryState, now: float) -> float | None:
    if _TG_TELEMETRY_MAX_AGE <= 0:
        return None
    barrier = _tg_first_ordered_sequence(state)
    waits = [
        max(0, _TG_TELEMETRY_MAX_AGE - (now - item.enqueued_at))
        for item in state.telemetry.values()
        if not item.in_flight
        and barrier is not None
        and item.sequence >= barrier
    ]
    return min(waits) if waits else None


def _tg_pick_next(state: _TgDeliveryState):
    now = state.loop.time()
    _tg_drop_stale_cosmetics(state, now)
    telemetry = _tg_oldest_telemetry(state, now)
    marker_sequence = _tg_first_ordered_sequence(state)
    if (
        state.reliable
        and state.reliable[0].ordered
        and marker_sequence == state.reliable[0].sequence
    ):
        preceding = [
            item for item in state.telemetry.values()
            if not item.in_flight and item.sequence < marker_sequence
        ]
        telemetry = min(preceding, key=lambda item: item.sequence) if preceding else None
        if telemetry is not None:
            telemetry.in_flight = True
            return (
                "telemetry",
                telemetry,
                telemetry.version,
                telemetry.count,
                telemetry.call_factory,
                telemetry.future,
            )
    if state.reliable:
        item = state.reliable.popleft()
        state.space.set()
        return ("reliable", item)
    if telemetry:
        telemetry.in_flight = True
        return (
            "telemetry",
            telemetry,
            telemetry.version,
            telemetry.count,
            telemetry.call_factory,
            telemetry.future,
        )
    if state.optional:
        item = state.optional.popleft()
        if item.optional_kind == "image":
            state.optional_images -= 1
        return ("optional", item)
    return None


async def _tg_dispatch_chat(chat_id: int, state: _TgDeliveryState) -> None:
    try:
        while not state.stopped:
            selected = _tg_pick_next(state)
            if selected is None:
                state.wake.clear()
                timeout = _tg_next_telemetry_wait(state, state.loop.time())
                try:
                    if timeout is None:
                        await state.wake.wait()
                    else:
                        await asyncio.wait_for(state.wake.wait(), timeout=timeout)
                except TimeoutError:
                    pass
                continue
            kind, item, *snapshot = selected
            if item.future.cancelled():
                if kind == "telemetry" and state.telemetry.get(item.key) is item:
                    state.telemetry.pop(item.key, None)
                continue
            state.in_flight = item
            try:
                if kind == "reliable":
                    traffic_class = item.traffic_class or kind
                    result = await _tg_run_call(
                        chat_id,
                        state,
                        lambda: item.call_factory(1),
                        item.important,
                        item.label,
                        traffic_class,
                        call_timeout=item.call_timeout,
                        count_lost=item.count_lost,
                        retry_ambiguous=item.retry_ambiguous,
                    )
                    _tg_record_latency(state, traffic_class, item)
                    _settle_tg_item(item, result)
                elif kind == "telemetry":
                    version, count, call_factory, future = snapshot
                    result = await _tg_run_call(
                        chat_id,
                        state,
                        lambda: call_factory(count),
                        False,
                        item.label,
                        kind,
                        drop_count=count,
                    )
                    _tg_record_latency(state, kind, item)
                    if not future.done():
                        future.set_result(result)
                    current = state.telemetry.get(item.key)
                    if current is item and current.version == version:
                        state.telemetry.pop(item.key, None)
                    elif current is item:
                        current.in_flight = False
                    state.wake.set()
                else:
                    result = await _tg_run_call(
                        chat_id,
                        state,
                        lambda: item.call_factory(1),
                        False,
                        item.label,
                        kind,
                    )
                    _tg_record_latency(state, kind, item)
                    _settle_tg_item(item, result)
            except asyncio.CancelledError:
                _settle_tg_item(item)
                raise
            except Exception as e:
                logger.exception(f"TG {item.label} dispatcher failed: {e}")
                _settle_tg_item(item)
            finally:
                state.in_flight = None
    finally:
        current = asyncio.current_task()
        if _tg_dispatch_tasks.get(chat_id) is current:
            _tg_dispatch_tasks.pop(chat_id, None)
        if state.dispatcher is current:
            state.dispatcher = None


async def _tg_dispatch_images(chat_id: int, state: _TgDeliveryState) -> None:
    try:
        while not state.stopped:
            if not state.images:
                state.image_wake.clear()
                await state.image_wake.wait()
                continue
            item = state.images.popleft()
            if item.future.cancelled():
                state.image_reservations.discard(item.reservation)
                continue
            state.image_in_flight = item
            try:
                result = await _tg_run_call(
                    chat_id,
                    state,
                    lambda: item.call_factory(1),
                    item.important,
                    item.label,
                    "image",
                    call_timeout=item.call_timeout,
                    count_lost=item.count_lost,
                    retry_ambiguous=item.retry_ambiguous,
                )
                _tg_record_latency(state, "image", item)
                _settle_tg_item(item, result)
            except asyncio.CancelledError:
                _settle_tg_item(item)
                raise
            except Exception as e:
                logger.exception(f"TG {item.label} image dispatcher failed: {e}")
                _settle_tg_item(item)
            finally:
                state.image_reservations.discard(item.reservation)
                if state.image_in_flight is item:
                    state.image_in_flight = None
    finally:
        current = asyncio.current_task()
        if state.image_dispatcher is current:
            state.image_dispatcher = None


def _tg_start_dispatcher(chat_id: int, state: _TgDeliveryState) -> None:
    if state.dispatcher is None or state.dispatcher.done():
        state.dispatcher = asyncio.create_task(_tg_dispatch_chat(chat_id, state))
        _tg_dispatch_tasks[chat_id] = state.dispatcher


def _tg_start_image_dispatcher(
    chat_id: int,
    state: _TgDeliveryState,
) -> None:
    if state.image_dispatcher is None or state.image_dispatcher.done():
        state.image_dispatcher = asyncio.create_task(
            _tg_dispatch_images(chat_id, state),
        )


async def _tg_call_safe(
    chat_id: int,
    call,
    *,
    important: bool = False,
    label: str = "call",
    telemetry_key=None,
    call_factory=None,
    best_effort: bool = False,
    optional_kind: str | None = None,
    ordered: bool = False,
    traffic_class: str | None = None,
    call_timeout: float | None = None,
    count_lost: bool = True,
    retry_ambiguous: bool | None = None,
    wait_result: bool = True,
):
    """Submit a bounded ordered, optional, or coalesced call for one chat."""
    global _tg_call_sequence
    loop = asyncio.get_running_loop()
    state = await _tg_delivery_state_for(chat_id)
    if state.stopped:
        return None
    future = loop.create_future()
    _tg_call_sequence += 1
    sequence = _tg_call_sequence
    factory = call_factory or (lambda _count: call())

    if best_effort:
        image_full = (
            optional_kind == "image"
            and state.optional_images >= _TG_IMAGE_QUEUE_MAX
        )
        if len(state.optional) >= _TG_OPTIONAL_QUEUE_MAX or image_full:
            state.optional_dropped += 1
            logger.warning(f"TG {label} dropped: optional lane full")
            return None
        state.optional.append(_TgCallItem(
            call_factory=factory,
            important=False,
            label=label,
            future=future,
            enqueued_at=loop.time(),
            optional_kind=optional_kind,
        ))
        if optional_kind == "image":
            state.optional_images += 1
        state.wake.set()
        _tg_start_dispatcher(chat_id, state)
        return future

    if important or ordered:
        if ordered:
            state.ordered_admissions.add(sequence)
        try:
            if len(state.reliable) >= _TG_RELIABLE_QUEUE_MAX:
                if state.admission_waiters >= _TG_RELIABLE_ADMISSION_MAX:
                    state.reliable_overflow += 1
                    logger.error(f"TG {label} LOST: reliable admission full")
                    raise _TgDeliveryOverloaded(
                        f"TG {label} reliable admission full",
                    )
                state.admission_waiters += 1
                waiter = asyncio.current_task()
                if waiter:
                    state.admission_tasks.add(waiter)
                try:
                    async with asyncio.timeout(_TG_RELIABLE_ADMISSION_TIMEOUT):
                        while (
                            not state.stopped
                            and len(state.reliable) >= _TG_RELIABLE_QUEUE_MAX
                        ):
                            state.space.clear()
                            await state.space.wait()
                except TimeoutError:
                    state.reliable_overflow += 1
                    logger.error(f"TG {label} LOST: reliable admission timeout")
                    raise _TgDeliveryOverloaded(
                        f"TG {label} reliable admission timeout",
                    )
                finally:
                    state.admission_waiters -= 1
                    if waiter:
                        state.admission_tasks.discard(waiter)
            if state.stopped:
                future.set_result(None)
                return await future if wait_result else future
            state.reliable.append(_TgCallItem(
                call_factory=factory,
                important=important,
                label=label,
                future=future,
                enqueued_at=loop.time(),
                traffic_class=traffic_class,
                call_timeout=call_timeout,
                count_lost=count_lost,
                retry_ambiguous=retry_ambiguous,
                sequence=sequence,
                ordered=ordered,
            ))
            if ordered:
                state.ordered_admissions.discard(sequence)
            state.wake.set()
            _tg_start_dispatcher(chat_id, state)
            return await future if wait_result else future
        finally:
            if ordered:
                state.ordered_admissions.discard(sequence)
                state.wake.set()

    key = telemetry_key
    if key is None:
        key = ("unique", _tg_call_sequence)
    current = state.telemetry.get(key)
    if (
        current is not None
        and not current.in_flight
        and any(
            current.sequence < barrier < sequence
            for barrier in _tg_ordered_sequences(state)
        )
    ):
        state.telemetry.pop(key)
        current.key = ("before_ordered", key, current.sequence)
        state.telemetry[current.key] = current
        current = None
    if current is not None:
        if current.in_flight:
            current = _TgCallItem(
                call_factory=factory,
                important=False,
                label=label,
                future=future,
                enqueued_at=loop.time(),
                key=key,
                version=current.version + 1,
                sequence=sequence,
            )
            state.telemetry[key] = current
        else:
            current.call_factory = factory
            current.label = label
            current.version += 1
            current.count += 1
            future = current.future
        state.telemetry_coalesced += 1
    else:
        if len(state.telemetry) >= _TG_TELEMETRY_MAX_KEYS:
            state.telemetry_dropped += 1
            logger.warning(f"TG {label} dropped: telemetry map full")
            future.set_result(None)
            return future
        current = _TgCallItem(
            call_factory=factory,
            important=False,
            label=label,
            future=future,
            enqueued_at=loop.time(),
            key=key,
            sequence=sequence,
        )
        state.telemetry[key] = current
    state.wake.set()
    _tg_start_dispatcher(chat_id, state)
    return future


async def _tg_send_safe(chat_id: int, text: str, thread_id: int = None,
                         entities=None, important: bool = False,
                         telemetry_key=None, best_effort: bool = False,
                         batch_bucket=None):
    # Тулы копятся в bucket и уезжают ОДНИМ сообщением: TG даёт 20 сообщений
    # на 60 с в группу, поэтому «каждый тул = своё сообщение» физически
    # недостижимо — без батча пачка вызовов теряется на rate-лимите, а при
    # схлопывании по ключу выживал только последний текст.
    if batch_bucket is not None and text:
        batch_bucket.append(text)

    async def _send(coalesced_count: int = 1):
        payload = text
        taken_batch = []
        if batch_bucket is not None:
            # Склейка не должна перерасти лимит TG: сообщение целиком уйдёт
            # в отказ, и потеряется ВСЯ пачка вместо одного тула. Что не влезло —
            # остаётся в bucket и уедет следующим сообщением.
            size = 0
            while batch_bucket:
                nxt = batch_bucket[0]
                nxt_size = _utf16_len(nxt) + 2
                if taken_batch and size + nxt_size > TG_MSG_LIMIT:
                    break
                taken_batch.append(batch_bucket.pop(0))
                size += nxt_size
            if batch_bucket:
                # Хвост не влез — ставим ещё один заход, иначе он застрянет
                # в bucket навсегда: очередь этот вызов уже отработала.
                _track_tg_result(_tg_send_safe(
                    chat_id, "", thread_id,
                    telemetry_key=telemetry_key,
                    batch_bucket=batch_bucket,
                ))
            if taken_batch:
                payload = "\n\n".join(taken_batch)
        elif not important and coalesced_count > 1:
            payload = f"{text}\n\n⏱ {coalesced_count} events coalesced"
        # offsets entities посчитаны под ОДИН body — в склейке они указывают не туда
        send_entities = None if payload is not text else entities
        # Одно тело тула само по себе может быть длиннее лимита — режем,
        # иначе TG отобьёт сообщение целиком
        chunks = _split_message(payload) if _utf16_len(payload) > TG_MSG_LIMIT else [payload]
        if len(chunks) > 1:
            send_entities = None
        try:
            sent = None
            for chunk in chunks:
                sent = await bot.send_message(
                    chat_id, chunk, message_thread_id=thread_id,
                    parse_mode=None, entities=send_entities,
                )
            return sent
        except TelegramBadRequest:
            if not send_entities:
                raise
            return _TgSendEntityRejected(payload, thread_id)
        except Exception:
            # Пачка уже вынута из bucket — вернём её назад, иначе тела
            # исчезнут молча вместе с упавшей отправкой
            if taken_batch and batch_bucket is not None:
                batch_bucket[:0] = taken_batch
            raise

    result = await _tg_call_safe(
        chat_id,
        _send,
        important=important,
        label="send_message",
        telemetry_key=(
            telemetry_key
            if telemetry_key is not None
            else (("send_message", thread_id) if not important else None)
        ),
        call_factory=_send,
        best_effort=best_effort,
        optional_kind="mirror" if best_effort else None,
    )
    if isinstance(result, asyncio.Future):
        if (
            result.done()
            and not isinstance(result.result(), _TgSendEntityRejected)
        ):
            return result.result()
        wrapper = _tg_result_wrappers.get(result)
        if wrapper is not None:
            return wrapper

        async def _finish_send():
            queued_result = await result
            if not isinstance(queued_result, _TgSendEntityRejected):
                return queued_result
            logger.warning("TG formatted send rejected; trying without entities")

            async def _send_plain_queued():
                return await bot.send_message(
                    chat_id,
                    queued_result.text,
                    message_thread_id=queued_result.thread_id,
                    parse_mode=None, entities=None,
                )

            plain = await _tg_call_safe(
                chat_id,
                _send_plain_queued,
                label="send_message_plain",
                best_effort=best_effort,
                optional_kind="mirror" if best_effort else None,
                telemetry_key=(
                    ("plain", telemetry_key)
                    if telemetry_key is not None else None
                ),
            )
            return await plain if isinstance(plain, asyncio.Future) else plain

        wrapper = _track_tg_result(_finish_send())
        _tg_result_wrappers[result] = wrapper
        wrapper.add_done_callback(lambda _task: _tg_result_wrappers.pop(result, None))
        return wrapper
    if not isinstance(result, _TgSendEntityRejected):
        return result

    logger.warning("TG formatted send rejected; trying without entities")

    async def _send_plain():
        return await bot.send_message(
            chat_id,
            result.text,
            message_thread_id=result.thread_id,
            parse_mode=None, entities=None,
        )

    return await _tg_call_safe(
        chat_id,
        _send_plain,
        important=important,
        label="send_message_plain",
        best_effort=best_effort,
        optional_kind="mirror" if best_effort else None,
    )


async def _tg_edit_message_safe(chat_id: int, message, text: str, entities=None,
                                telemetry_key=None):
    """telemetry_key схлопывает пачку правок ОДНОГО сообщения в одну отправку.

    Ключ обязан отличаться от ключа исходной отправки: очередь при совпадении ключа
    подменяет `call_factory` уже стоящего элемента, и правка стала бы ждать `Future`
    подменённого вызова.
    """
    async def _message_id():
        resolved = await message if isinstance(message, asyncio.Future) else message
        if resolved is None:
            return None
        return resolved if isinstance(resolved, int) else resolved.message_id

    async def _edit():
        message_id = await _message_id()
        if message_id is None:
            return None
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

    result = await _tg_call_safe(chat_id, _edit, label="edit_message",
                                 telemetry_key=telemetry_key)
    if isinstance(result, asyncio.Future):
        async def _finish_edit():
            queued_result = await result
            if queued_result is not _TG_ENTITY_REJECTED:
                return queued_result

            async def _edit_plain_queued():
                message_id = await _message_id()
                if message_id is None:
                    return None
                try:
                    return await bot.edit_message_text(
                        text, chat_id=chat_id, message_id=message_id,
                    )
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e).lower():
                        return True
                    raise

            plain = await _tg_call_safe(
                chat_id, _edit_plain_queued, label="edit_message_plain",
            )
            return await plain

        return _track_tg_result(_finish_edit())
    if result is not _TG_ENTITY_REJECTED:
        return result

    async def _edit_plain():
        message_id = await _message_id()
        if message_id is None:
            return None
        try:
            return await bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id,
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return True
            raise

    return await _tg_call_safe(chat_id, _edit_plain, label="edit_message_plain")


async def _tg_send_isolated_photo(
    chat_id: int,
    path: str,
    caption: str | None,
    thread_id: int | None,
    placeholder_text: str | None,
    *,
    important: bool,
):
    import shutil
    import tempfile
    import uuid
    from aiogram.types import FSInputFile, InputMediaPhoto

    state = await _tg_delivery_state_for(chat_id)
    if state.stopped:
        return None
    if (
        not important
        and len(state.image_reservations) >= _TG_IMAGE_QUEUE_MAX
    ):
        state.image_dropped += 1
        logger.warning("TG send_photo dropped: image lane full")
        return None

    reservation = object()
    state.image_reservations.add(reservation)
    suffix = Path(path).suffix or ".png"
    owned_path = Path(tempfile.gettempdir()) / (
        f"tg-image-{uuid.uuid4().hex}{suffix}"
    )

    def _cleanup(_future=None):
        try:
            owned_path.unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"TG image snapshot cleanup failed ({owned_path}): {e}")

    try:
        shutil.copyfile(path, owned_path)
    except Exception as e:
        state.image_reservations.discard(reservation)
        state.image_lost += 1
        _cleanup()
        logger.warning(f"TG send_photo snapshot failed: {e}")
        return None

    async def _send_marker():
        return await bot.send_message(
            chat_id,
            placeholder_text or caption or "🖼 Image",
            message_thread_id=thread_id,
            parse_mode=None,
        )

    completion = state.loop.create_future()
    completion.add_done_callback(_cleanup)
    try:
        marker_result = await _tg_call_safe(
            chat_id,
            _send_marker,
            important=important,
            label="send_photo_marker",
            ordered=True,
            traffic_class="image",
            call_timeout=_TG_TELEMETRY_CALL_TIMEOUT,
            count_lost=False,
            retry_ambiguous=False,
            wait_result=not important,
        )
    except _TgDeliveryOverloaded as e:
        state.image_reservations.discard(reservation)
        state.image_lost += 1
        if not completion.done():
            completion.set_result(None)
        _cleanup()
        logger.error(
            f"TG send_photo marker rejected: {type(e).__name__}: {e}"
        )
        if important:
            raise
        return None
    except asyncio.CancelledError:
        state.image_reservations.discard(reservation)
        if not completion.done():
            completion.set_result(None)
        _cleanup()
        raise
    except Exception as e:
        state.image_reservations.discard(reservation)
        state.image_lost += 1
        if not completion.done():
            completion.set_result(None)
        _cleanup()
        logger.exception(
            f"TG send_photo marker failed: {type(e).__name__}: {e}"
        )
        return None

    def _queue_edit(marker) -> bool:
        message_id = getattr(marker, "message_id", None)
        active_state = (
            not state.stopped
            and _tg_delivery_states.get(chat_id) is state
        )
        if message_id is None or not active_state:
            if active_state:
                state.image_lost += 1
                logger.warning("TG send_photo marker result unavailable")
            return False

        async def _edit(_count=1):
            media = InputMediaPhoto(
                media=FSInputFile(
                    owned_path,
                    filename=Path(path).name,
                ),
                caption=caption,
                parse_mode=None,
            )
            try:
                return await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=media,
                    request_timeout=_TG_IMAGE_CALL_TIMEOUT,
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    return True
                raise

        state.images.append(_TgCallItem(
            call_factory=_edit,
            important=important,
            label="edit_message_media",
            future=completion,
            enqueued_at=state.loop.time(),
            traffic_class="image",
            call_timeout=_TG_IMAGE_CALL_TIMEOUT,
            retry_ambiguous=important,
            reservation=reservation,
        ))
        state.image_wake.set()
        _tg_start_image_dispatcher(chat_id, state)
        return True

    if not important:
        if not _queue_edit(marker_result):
            state.image_reservations.discard(reservation)
            if not completion.done():
                completion.set_result(None)
            _cleanup()
            return None
        return asyncio.shield(completion)

    if not isinstance(marker_result, asyncio.Future):
        state.image_reservations.discard(reservation)
        if not completion.done():
            completion.set_result(None)
        _cleanup()
        return None

    async def _finish_marker():
        queued = False
        try:
            queued = _queue_edit(await marker_result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not state.stopped and _tg_delivery_states.get(chat_id) is state:
                state.image_lost += 1
            logger.exception(
                f"TG send_photo marker continuation failed: "
                f"{type(e).__name__}: {e}"
            )
        finally:
            if not queued:
                state.image_reservations.discard(reservation)
                if not completion.done():
                    completion.set_result(None)
                _cleanup()

    continuation = spawn_supervised(_finish_marker(), "завершение приёма медиа")
    state.image_admission_tasks.add(continuation)
    continuation.add_done_callback(state.image_admission_tasks.discard)
    return asyncio.shield(completion)


async def _tg_send_file_safe(
    chat_id: int, path: str, caption: str | None, thread_id: int | None,
    *, is_photo: bool, important: bool, placeholder_text: str | None = None,
    isolated_preview: bool = False,
):
    if is_photo and (not important or isolated_preview):
        return await _tg_send_isolated_photo(
            chat_id,
            path,
            caption,
            thread_id,
            placeholder_text,
            important=important,
        )

    from aiogram.types import FSInputFile

    async def _send():
        tg_file = FSInputFile(path, filename=Path(path).name)
        if is_photo:
            return await bot.send_photo(
                chat_id, tg_file, caption=caption, message_thread_id=thread_id,
            )
        return await bot.send_document(
            chat_id, tg_file, caption=caption, message_thread_id=thread_id,
        )

    label = "send_photo" if is_photo else "send_document"
    return await _tg_call_safe(
        chat_id,
        _send,
        important=important,
        label=label,
        best_effort=not important,
        optional_kind=("image" if is_photo else "file") if not important else None,
    )


_TG_TOOL_ICONS = {
    'Bash': '🖥', 'Read': '📖', 'Write': '✏️', 'Edit': '✏️',
    'Glob': '🔎', 'Grep': '🔎', 'WebSearch': '🌐', 'WebFetch': '🌐',
    'Agent': '🤖', 'ToolSearch': '🔍', 'AskUserQuestion': '❓',
    # Одна правка файла — один значок, каким бы рантаймом она ни была сделана:
    # Codex пишет её как FileChange, Claude как Edit/Write (767 против 82 за трое суток).
    'FileChange': '✏️',
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
    'claude-opus-5[1m]': 'opus-5-1M',
    'claude-sonnet-5[1m]': 'sonnet-5-1M', 'claude-sonnet-4-6': 'sonnet-4.6', 'claude-haiku-4-5': 'haiku-4.5',
    'claude-haiku-4-6': 'haiku-4.6', 'gpt-5.5': 'gpt-5.5',
}


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


def _ensure_owned_task(registry: dict, key, coro_factory) -> asyncio.Task:
    current = registry.get(key)
    if current is not None and not current.done():
        return current
    task = spawn_supervised(coro_factory(), f"фоновая задача TG {key}")
    registry[key] = task
    _tasks.append(task)

    def _done(_task):
        if registry.get(key) is _task:
            registry.pop(key, None)
        try:
            _tasks.remove(_task)
        except ValueError:
            pass

    task.add_done_callback(_done)
    return task


def _ensure_stream(orch_name: str, thread_id: int) -> asyncio.Task:
    key = (orch_name, thread_id)
    return _ensure_owned_task(
        _stream_tasks,
        key,
        lambda: stream_logs(orch_name, thread_id),
    )


async def _cancel_orch_lifecycle(orch_name: str) -> None:
    tasks = [
        task
        for (name, _thread_id), task in list(_stream_tasks.items())
        if name == orch_name
    ]
    status_task = _topic_status_tasks.pop(orch_name, None)
    if status_task:
        tasks.append(status_task)
    create_task = _topic_create_tasks.pop(f"primary:{orch_name}", None)
    if create_task:
        tasks.append(create_task)
    _mirror_stopping.add(orch_name)
    mirror_task = _mirror_tasks.get(orch_name)
    if mirror_task:
        tasks.append(mirror_task)
    _topic_status_desired.pop(orch_name, None)
    for key in [
        key for key in list(_stream_tasks)
        if key[0] == orch_name
    ]:
        _stream_tasks.pop(key, None)
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    if _mirror_tasks.get(orch_name) is mirror_task:
        _mirror_tasks.pop(orch_name, None)
    _mirror_outboxes.pop(orch_name, None)
    _mirror_dropped.pop(orch_name, None)
    _mirror_stopping.discard(orch_name)


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
    uncertain = config.setdefault("topic_create_uncertain", {})

    for name in orch_names:
        await _cancel_orch_lifecycle(name)
        uncertain.pop(f"primary:{name}", None)
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
    mirror_create = _topic_create_tasks.get(f"mirror:{old_name}")
    if mirror_create is not None and not mirror_create.done():
        await asyncio.shield(mirror_create)
    await _cancel_orch_lifecycle(old_name)
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
    uncertain = config.setdefault("topic_create_uncertain", {})
    for prefix in ("primary", "mirror"):
        old_key = f"{prefix}:{old_name}"
        if old_key in uncertain:
            uncertain[f"{prefix}:{new_name}"] = uncertain.pop(old_key)
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
    _ensure_stream(new_name, thread_id)
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


async def _mirror_send_file(orch_name: str, path: str, caption: str, is_photo: bool):
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
        ),
    )


def _resolve_topic(scope: str, sender: str) -> tuple[str | None, int | None]:
    """Куда слать: собственный топик отправителя, иначе топик оркестратора скоупа.

    Вынесено из `send_file_to_tg`, чтобы у правила был один владелец: текстовые
    уведомления о квоте (#186) адресуются точно так же, а вторая копия этой логики
    разошлась бы с первой при ближайшей правке топиков.
    """
    topics = config.get("topics", {})
    sender_thread = topics.get(sender) if sender else None
    if sender_thread:
        return sender, sender_thread
    orch_name = _find_orch_for_scope(scope)
    return orch_name, (topics.get(orch_name) if orch_name else None)


async def send_text_to_tg(text: str, *, scope: str, sender: str) -> dict:
    """Отправить текст в TG. Успех — ТОЛЬКО `{"ok": True, ...}`, всё иное — отказ.

    Признак успеха обязан быть явным: сосед `send_file_to_tg` сообщает об операционных
    сбоях обычным возвратом `{"error": ...}`, а не исключением. Если вызывающий сочтёт
    успехом сам факт завершившегося `await`, то при выключенном мосте или отсутствующем
    топике предупреждение о квоте будет помечено доставленным и потеряно навсегда —
    а оно случается раз в неделю (#186).
    """
    if not bot or not config["group_id"]:
        return {"error": "TG bridge not active"}
    if not text.strip():
        return {"error": "empty text"}
    orch_name, thread_id = _resolve_topic(scope, sender)
    if not thread_id:
        return {"error": f"no TG topic for scope: {scope}"}
    msg = await _tg_send_safe(config["group_id"], text[:4096], thread_id, important=True)
    if msg is None:
        return {"error": "TG text delivery failed; see tg-bridge logs"}
    return {"ok": True, "message_id": msg.message_id, "chat_id": msg.chat.id}


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
    orch_name, thread_id = _resolve_topic(scope, sender)
    logger.info(f"send_file: path={path} size={file_size} scope={scope!r} sender={sender!r} orch={orch_name!r} group_id={config['group_id']} thread_id={thread_id}")
    if not thread_id:
        return {"error": f"no TG topic for scope: {scope}"}
    label = f"📎 {sender}: {caption}" if caption else f"📎 {sender}: {fp.name}"
    label = label[:1024]
    is_photo = not as_document and fp.suffix.lower() in _IMAGE_EXTS
    msg = await _tg_send_file_safe(
        config["group_id"], path, label, thread_id,
        is_photo=is_photo, important=True,
    )
    if msg is None:
        return {"error": "TG file delivery failed; see tg-bridge logs"}
    logger.info(f"send_file: delivered msg_id={msg.message_id} chat_id={msg.chat.id} thread={getattr(msg, 'message_thread_id', None)}")
    if orch_name:
        await _mirror_send_file(orch_name, path, label, is_photo)
    return {"ok": True, "message_id": msg.message_id, "chat_id": msg.chat.id}


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
        _schedule_topic_status(orch_name, False)


async def notify_scope_running(orch_name: str):
    _schedule_topic_status(orch_name, True)


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
    for s in list(_manager.sessions.values()):
        if not s.is_orchestrator:
            continue
        name = s.name
        if name not in config["topics"]:
            continue
        is_running = _any_running_in_scope(s.scope)
        task = _schedule_topic_status(
            name,
            is_running,
            delay_idle=False,
        )
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise


# Custom emoji IDs in the target TG group — green dot for running, grey for idle
_ICON_RUNNING = "5312016608254762256"
_ICON_IDLE = "5350392020785437399"
_TG_TOPIC_STATUS_TIMEOUT = 5
_TG_TOPIC_CREATE_TIMEOUT = 5
_TOPIC_STATUS_IDLE_FADE_DELAY_SECONDS = 5 * 60


# Topic metadata is best-effort and stays outside the user-message delivery queue.
async def _update_topic_status(orch_name: str, is_running: bool):
    if _topic_status.get(orch_name) == is_running:
        return
    short = (config.get("topic_names") or {}).get(orch_name) or _short_name(orch_name)
    icon_id = _ICON_RUNNING if is_running else _ICON_IDLE

    async def _do_edit(chat_id, thread_id):
        try:
            async with asyncio.timeout(_TG_TOPIC_STATUS_TIMEOUT):
                return await bot.edit_forum_topic(
                    chat_id=chat_id, message_thread_id=thread_id,
                    name=short, icon_custom_emoji_id=icon_id,
                    request_timeout=_TG_TOPIC_STATUS_TIMEOUT,
                )
        except TelegramBadRequest as e:
            if "TOPIC_NOT_MODIFIED" in str(e).upper():
                return True
            logger.warning(
                f"TG topic_status failed: {type(e).__name__}: {e}",
            )
        except Exception as e:
            logger.warning(
                f"TG topic_status failed: {type(e).__name__}: {e}",
            )
        return None

    thread_id = config["topics"].get(orch_name)
    primary_updated = False
    if thread_id and bot:
        primary_updated = await _do_edit(config["group_id"], thread_id) is not None
    mirror = config.get("mirrors", {}).get(orch_name)
    if mirror and mirror.get("chat_id") and mirror.get("topic_id") and bot:
        await _do_edit(mirror["chat_id"], mirror["topic_id"])
    if primary_updated:
        _topic_status[orch_name] = is_running


async def _wait_for_topic_status_idle_fade() -> None:
    await asyncio.sleep(_TOPIC_STATUS_IDLE_FADE_DELAY_SECONDS)


def _topic_status_scope(orch_name: str) -> str | None:
    if not _manager:
        return None
    for session in _manager.sessions.values():
        if session.name == orch_name and session.is_orchestrator:
            return session.scope
    return None


async def _topic_status_worker(orch_name: str) -> None:
    task = asyncio.current_task()
    while orch_name in _topic_status_desired:
        desired = _topic_status_desired[orch_name]
        is_running, delay_idle = desired
        if not is_running and delay_idle:
            if task is not None:
                task._topic_status_waiting_for_idle = True
            try:
                await _wait_for_topic_status_idle_fade()
            finally:
                if task is not None:
                    task._topic_status_waiting_for_idle = False
            if _topic_status_desired.get(orch_name) != desired:
                continue
            scope = _topic_status_scope(orch_name)
            if not scope or _any_running_in_scope(scope):
                return
        await _update_topic_status(orch_name, is_running)
        if _topic_status_desired.get(orch_name) == desired:
            return


def _schedule_topic_status(
    orch_name: str,
    is_running: bool,
    *,
    delay_idle: bool = True,
) -> asyncio.Task:
    is_running = bool(is_running)
    desired = (is_running, bool(delay_idle))
    current = _topic_status_tasks.get(orch_name)
    _topic_status_desired[orch_name] = desired
    if (
        current is not None
        and not current.done()
        and getattr(current, "_topic_status_waiting_for_idle", False)
        and (is_running or not delay_idle)
    ):
        current.cancel()
        if _topic_status_tasks.get(orch_name) is current:
            _topic_status_tasks.pop(orch_name, None)
    task = _ensure_owned_task(
        _topic_status_tasks,
        orch_name,
        lambda: _topic_status_worker(orch_name),
    )
    if task is not current:
        task._topic_status_waiting_for_idle = not is_running and delay_idle
    return task


@dataclass(frozen=True)
class _MirrorItem:
    chat_id: int
    topic_id: int | None
    text: str | None = None
    entities: object = None
    path: str | None = None
    caption: str | None = None
    is_photo: bool = False


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
                )
            else:
                completion = await _tg_send_safe(
                    item.chat_id,
                    item.text or "",
                    item.topic_id,
                    entities=item.entities,
                    best_effort=True,
                )
            if isinstance(completion, (asyncio.Future, asyncio.Task)):
                await completion
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"TG mirror delivery failed for {orch_name}: {e}")
        finally:
            outbox.task_done()


def _mirror_submit(orch_name: str, item: _MirrorItem) -> bool:
    if orch_name in _mirror_stopping:
        logger.warning(f"TG mirror dropped for {orch_name}: outbox stopping")
        return False
    outbox = _mirror_outboxes.get(orch_name)
    if outbox is None:
        outbox = asyncio.Queue(maxsize=_TG_MIRROR_OUTBOX_MAX)
        _mirror_outboxes[orch_name] = outbox
    try:
        outbox.put_nowait(item)
    except asyncio.QueueFull:
        _mirror_dropped[orch_name] = _mirror_dropped.get(orch_name, 0) + 1
        logger.warning(f"TG mirror dropped for {orch_name}: outbox full")
        return False
    _ensure_owned_task(
        _mirror_tasks,
        orch_name,
        lambda: _mirror_worker(orch_name, outbox),
    )
    return True


def _mirror_delivery_snapshot(orch_name: str) -> dict[str, int]:
    """Счётчики outbox зеркала — точка наблюдения для теста на ёмкость очереди."""
    outbox = _mirror_outboxes.get(orch_name)
    return {
        "queued": outbox.qsize() if outbox is not None else 0,
        "dropped": _mirror_dropped.get(orch_name, 0),
    }


async def _mirror_send(orch_name: str, text: str, entities=None, *, important: bool = False):
    mirrors = config.get("mirrors", {})
    mirror = mirrors.get(orch_name)
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
            text=text,
            entities=entities,
        ),
    )


def _mark_topic_create_uncertain(key: str) -> None:
    config.setdefault("topic_create_uncertain", {})[key] = (
        datetime.now(timezone.utc).isoformat()
    )
    save_config()


async def _create_primary_topic(name: str) -> None:
    key = f"primary:{name}"
    chosen = _pick_unique_topic_name(name)
    try:
        async with asyncio.timeout(_TG_TOPIC_CREATE_TIMEOUT):
            result = await bot.create_forum_topic(
                chat_id=config["group_id"],
                name=chosen,
                icon_custom_emoji_id=_ICON_IDLE,
                request_timeout=_TG_TOPIC_CREATE_TIMEOUT,
            )
    except asyncio.CancelledError:
        _mark_topic_create_uncertain(key)
        logger.error(
            f"TG topic create cancelled with uncertain result for {name}",
        )
        raise
    except (TimeoutError, TelegramNetworkError, TelegramServerError):
        _mark_topic_create_uncertain(key)
        logger.error(
            f"TG topic create uncertain for {name}; automatic retry disabled",
        )
        return
    except Exception as e:
        logger.error(f"Failed to create topic for {name}: {e}")
        return
    config["topics"][name] = result.message_thread_id
    config.setdefault("topic_names", {})[name] = chosen
    config.setdefault("topic_create_uncertain", {}).pop(key, None)
    save_config()
    logger.info(
        f"Created topic for {name} as '{chosen}': {result.message_thread_id}",
    )
    _ensure_stream(name, result.message_thread_id)


async def _ensure_primary_topic(name: str) -> None:
    if name in config["topics"]:
        _ensure_stream(name, config["topics"][name])
        return
    key = f"primary:{name}"
    if key in config.setdefault("topic_create_uncertain", {}):
        return
    task = _ensure_owned_task(
        _topic_create_tasks,
        key,
        lambda: _create_primary_topic(name),
    )
    await asyncio.shield(task)


async def _create_mirror_topic(name: str, mirror: dict) -> None:
    key = f"mirror:{name}"
    chat_id = mirror.get("chat_id")
    try:
        async with asyncio.timeout(_TG_TOPIC_CREATE_TIMEOUT):
            result = await bot.create_forum_topic(
                chat_id=chat_id,
                name=_short_name(name),
                icon_custom_emoji_id=_ICON_IDLE,
                request_timeout=_TG_TOPIC_CREATE_TIMEOUT,
            )
    except asyncio.CancelledError:
        _mark_topic_create_uncertain(key)
        logger.error(
            f"TG mirror topic create cancelled with uncertain result for {name}",
        )
        raise
    except (TimeoutError, TelegramNetworkError, TelegramServerError):
        _mark_topic_create_uncertain(key)
        logger.error(
            f"TG mirror topic create uncertain for {name}; automatic retry disabled",
        )
        return
    except Exception as e:
        logger.warning(f"Mirror topic creation failed for {name}: {e}")
        return
    mirror["topic_id"] = result.message_thread_id
    config.setdefault("topic_create_uncertain", {}).pop(key, None)
    save_config()
    logger.info(f"Created mirror topic for {name}: {result.message_thread_id}")


async def _ensure_mirror_topic(name: str, mirror: dict) -> None:
    if mirror.get("topic_id") is not None or not mirror.get("chat_id"):
        return
    key = f"mirror:{name}"
    if key in config.setdefault("topic_create_uncertain", {}):
        return
    task = _ensure_owned_task(
        _topic_create_tasks,
        key,
        lambda: _create_mirror_topic(name, mirror),
    )
    await asyncio.shield(task)


async def ensure_topics():
    if not bot or not config["group_id"] or not _manager:
        return
    from app.db import get_all_sessions
    orchs = [s for s in get_all_sessions() if s.get("tg_topic") or s.get("role", "worker") in ("orchestrator", "sub-orchestrator")]
    if not orchs:
        return

    for o in orchs:
        await _ensure_primary_topic(o["name"])

    mirrors = config.get("mirrors", {})
    for name, mirror in list(mirrors.items()):
        await _ensure_mirror_topic(name, mirror)




async def stream_logs(orch_name: str, thread_id: int):
    from app.db import get_logs, get_session_by_name, get_all_sessions

    scope = None
    is_orch = False
    for s in get_all_sessions():
        if s["name"] == orch_name:
            scope = s.get("scope", "")
            # Воркеры отчитываются оркестратору, а не юзеру — тегать его на их ходах нечем.
            is_orch = s.get("role", "worker") in ("orchestrator", "sub-orchestrator")
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
    turn = _TurnState()
    # Отметка «якорь по этой строке уже ушёл» живёт ВНЕ состояния хода: состояние
    # обнуляется на границе, а откат курсора переигрывает саму строку `turn ended`.
    _anchor_sent_for = None
    # None — `notify_user` в текущем ходе не звали, значит тега не будет. Строка (пусть
    # и пустая) — звали, и тег обязателен: молчание это дефолт, а не забывчивость.
    _notify_reason = None
    _pending_turn_end_mention = False
    _idle_ticks = 0
    current_log_previous_id = last_id

    try:
        while True:
            try:
                logs = get_logs(session_id, after_id=last_id, conn=_poll_conn)
                _idle_ticks = 0 if logs else _idle_ticks + 1
                for log in logs:
                    if log["id"] <= last_id:
                        continue
                    current_log_previous_id = last_id
                    last_id = log["id"]
                    t, c = log["type"], log["content"]
                    is_anchor = False
                    if t in ("text", "tool"):
                        _schedule_topic_status(orch_name, True)
                    if t == "user_message":
                        await _update_progress(turn, thread_id, orch_name, force=True)
                        turn.new_block()
                        c = re.sub(r'^\[\d{2}:\d{2}\] ', '', c)
                        img_match = re.search(r'(/\S+\.(?:png|jpg|jpeg|gif|webp))', c, re.IGNORECASE)
                        if img_match and Path(img_match.group(1)).is_file():
                            img_path = img_match.group(1)
                            caption = c.replace(img_path, '').strip()[:1024] or None
                            try:
                                await _tg_send_file_safe(
                                    config["group_id"], img_path, caption, thread_id,
                                    is_photo=True, important=True,
                                )
                                mirror = config.get("mirrors", {}).get(orch_name)
                                if mirror and mirror.get("chat_id"):
                                    await _mirror_send_file(
                                        orch_name, img_path, caption, True,
                                    )
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
                        if c == TG_SILENT_TURN_MARKER:
                            continue
                        from app.tool_call_guard import mark_unexecuted_tool_call

                        await _update_progress(turn, thread_id, orch_name, force=True)
                        turn.new_block()
                        raw_text = f"💬\n{mark_unexecuted_tool_call(c)}"
                        for converted, aio_ents in _formatted_chunks(raw_text):
                            await _tg_send_safe(
                                config["group_id"], converted, thread_id,
                                entities=aio_ents, important=True,
                            )
                            await _mirror_send(
                                orch_name, converted, entities=aio_ents, important=True,
                            )
                        continue
                    elif t == "tool":
                        if log.get("tool_name") == TG_NOTIFY_TOOL:
                            _notify_reason = _notify_reason_from_args(c)
                        tool_name = c.split(":")[0].strip() if ":" in c else "tool"
                        tool_body = c[len(tool_name) + 1:].strip() if ":" in c else c
                        turn.add(log["id"], _tool_line(tool_name, tool_body),
                                 log.get("tool_use_id") or "")
                        turn.raw[log["id"]] = tool_body
                        turn.names[log["id"]] = tool_name
                        await _update_progress(turn, thread_id, orch_name)
                        continue
                    elif t == "tool_result":
                        # Картинка настоящего файла, который агент СМОТРЕЛ, — это содержимое,
                        # а не машинерия: она остаётся отдельным сообщением.
                        _action_id = turn.resolve(log["id"], log.get("tool_use_id") or "")
                        if turn.names.get(_action_id) == "Read" and (
                            "'type': 'image'" in c or '"type": "image"' in c
                            or "'type':'image'" in c
                        ):
                            raw = turn.raw.get(_action_id, "")
                            try:
                                _read_params = json.loads(raw) if raw else {}
                                _img_path = _read_params.get("file_path", "")
                                if _img_path and Path(_img_path).is_file():
                                    await _tg_send_file_safe(
                                        config["group_id"], _img_path,
                                        f"📷 {Path(_img_path).name}", thread_id,
                                        is_photo=True, important=True,
                                        isolated_preview=True,
                                    )
                            except _TgDeliveryOverloaded:
                                raise
                            except Exception as _e:
                                logger.debug(f"Read image send failed: {_e}")
                        turn.close(log["id"], log.get("tool_use_id") or "",
                                   _result_mark(c, log.get("tool_is_error")))
                        await _update_progress(turn, thread_id, orch_name)
                        continue
                    elif t == "error":
                        text = f"❌ {c}"
                    elif t == "status":
                        if "turn ended" in c:
                            still_running = _any_running_in_scope(scope)
                            if not still_running:
                                _schedule_topic_status(orch_name, False)
                            # Граница хода — единственная durable-разметка «агент договорил»:
                            # на самой строке text её нет, мост стримит журнал вперёд и в
                            # момент отправки не знает, будет ли ещё текст (живой замер:
                            # 4777 из 6161 строк text — промежуточные).
                            _pending_turn_end_mention = (
                                is_orch and _notify_reason is not None
                            )
                            await _update_progress(turn, thread_id, orch_name,
                                                   force=True)
                            if _anchor_sent_for == log["id"]:
                                # Якорь по этой строке уже ушёл, а строка переигралась.
                                # Пропускаем ТОЛЬКО повтор якоря: дальше по строке живёт
                                # тег владельца, и `continue` здесь терял бы его молча.
                                text = ""
                            else:
                                elapsed = (time.time() - turn.started
                                           if turn.started else 0.0)
                                text = _turn_anchor(turn.all_lines(), elapsed, c)
                                is_anchor = True
                        elif c in _STATUS_AS_ACTION:
                            turn.add(log["id"], _STATUS_AS_ACTION[c])
                            await _update_progress(turn, thread_id, orch_name)
                            continue
                        elif c in _STATUS_RELIABLE:
                            text = f"⚡ {c}"
                        else:
                            continue    # телеметрия движка, юзеру не адресована
                    elif t == "subagent_end":
                        # Only the FINAL of a sub-agent (start/progress/stream = spam, dropped).
                        # Content: "desc | status=X | summary". Show desc + ok/fail.
                        # `subagent_end` also fires for background Bash tasks —
                        # 1608 of 1612 in one live week. They are not delegation
                        # and would flood the 20 msg/60 s group budget.
                        # task_type is sometimes empty in older rows, so fall back
                        # to the task_id shape: bash ids start with "b", agent
                        # ids with "a" (0 mismatches across 3238 live rows).
                        if _is_background_subagent(c):
                            continue
                        _parts = [p.strip() for p in c.split("|")]
                        _desc = _parts[0] if _parts else ""
                        _ok = "status=failed" not in c
                        text = f"{'✅' if _ok else '❌'} Sub-agent {'done' if _ok else 'failed'}: {_desc}"
                    else:
                        continue
                    # Якорь идёт по НАДЁЖНОЙ полосе: это единственная отметка «ход
                    # окончен», и потерять её значит вернуть исходную жалобу.
                    is_important = is_anchor or t in ("text", "error", "user_message")
                    for converted, aio_ents in (_formatted_chunks(text) if text else []):
                        await _tg_send_safe(
                            config["group_id"], converted, thread_id,
                            entities=aio_ents, important=is_important,
                        )
                        if is_anchor:
                            # Отмечаем СРАЗУ после доставки якоря, до зеркала: всё, что
                            # идёт следом по этой же строке, может упасть и откатить
                            # курсор — тогда строка переиграется с уже ушедшим якорем.
                            _anchor_sent_for = log["id"]
                            turn = _TurnState()
                        await _mirror_send(
                            orch_name, converted, entities=aio_ents,
                            important=is_important,
                        )
                    if _pending_turn_end_mention:
                        # Отдельным сообщением, а не хвостом к ⚡: status идёт по
                        # косметической полосе (important=False) и может быть дропнут,
                        # а дропнутое уведомление хуже отсутствующего.
                        if TG_USER_MENTION:
                            for converted, aio_ents in _formatted_chunks(
                                _mention_markup(TG_USER_MENTION, _notify_reason or "")
                            ):
                                await _tg_send_safe(
                                    config["group_id"], converted, thread_id,
                                    entities=aio_ents, important=True,
                                )
                        # Флаги гасим только ПОСЛЕ доставки: перегрузка откатывает
                        # курсор и переигрывает строки хода, а сброшенный раньше
                        # времени _notify_reason дал бы на повторе тихую потерю тега —
                        # строка вызова тула во второй раз уже не проиграется.
                        _pending_turn_end_mention = False
                        _notify_reason = None
            except _TgDeliveryOverloaded as e:
                last_id = current_log_previous_id
                logger.error(
                    f"Stream backpressure for {orch_name}, retaining cursor "
                    f"{last_id}: {e}"
                )
                _idle_ticks = 0
            except Exception as e:
                logger.error(f"Stream error for {orch_name}: {e}")
                _idle_ticks = 0
            # Poll faster when active, slow down when idle to save CPU on long-running idle sessions
            await asyncio.sleep(2 if _idle_ticks < 3 else 5)
    finally:
        _poll_conn.close()


async def _get_limits_usage() -> dict:
    from app.routes.system import _get_usage_data

    return await _get_usage_data()


async def _is_limits_owner(msg: types.Message) -> bool:
    group_id = config.get("group_id")
    user_id = getattr(getattr(msg, "from_user", None), "id", None)
    if not bot or not group_id or not user_id:
        return False
    try:
        member = await bot.get_chat_member(group_id, user_id)
    except Exception as e:
        logger.warning(
            f"TG /limits owner lookup failed: {type(e).__name__}: {e}"
        )
        return False
    return member.status == "creator"


def _format_limits_message(usage: dict, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_tz = timezone(timedelta(hours=7))

    def window_line(label: str, window: dict | None) -> str:
        if not isinstance(window, dict) or not isinstance(
            window.get("utilization"), (int, float)
        ):
            return f"• {label} — нет данных"

        remaining = max(0.0, min(100.0, 100 - float(window["utilization"])))
        remaining_text = f"{remaining:.1f}".rstrip("0").rstrip(".")
        reset_value = window.get("resets_at")
        if not reset_value:
            return f"• {label} — осталось {remaining_text}%; сброс не указан"
        try:
            reset = datetime.fromisoformat(
                str(reset_value).replace("Z", "+00:00")
            )
            if reset.tzinfo is None:
                reset = reset.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return f"• {label} — осталось {remaining_text}%; сброс некорректен"

        absolute = reset.astimezone(local_tz).strftime("%d.%m.%Y %H:%M UTC+7")
        seconds = (reset - now).total_seconds()
        if seconds <= 0:
            relative = "сброс уже наступил"
        else:
            minutes_total = max(1, int((seconds + 59) // 60))
            days, minutes_total = divmod(minutes_total, 24 * 60)
            hours, minutes = divmod(minutes_total, 60)
            parts = []
            if days:
                parts.append(f"{days} д")
            if hours:
                parts.append(f"{hours} ч")
            if minutes or not parts:
                parts.append(f"{minutes} мин")
            relative = f"через {' '.join(parts)}"
        return (
            f"• {label} — осталось {remaining_text}%; "
            f"сброс {absolute}, {relative}"
        )

    anthropic = usage.get("anthropic") or {}
    codex = usage.get("codex") or {}
    lines = [
        "*Лимиты*",
        window_line("Claude 5h", anthropic.get("five_hour")),
        window_line("Claude 7d", anthropic.get("seven_day")),
        window_line("Codex", codex.get("primary")),
    ]
    extra_usage = anthropic.get("extra_usage") or {}
    if extra_usage.get("spend_limit_reached") is True:
        lines.append(
            "• Claude extra usage — лимит расходов достигнут "
            "(базовые окна считаются отдельно)"
        )
    return "\n".join(lines)


@dp.message(F.chat.type == "private", F.text, lambda msg: msg.text and msg.text.strip() == "/limits")
async def handle_limits(msg: types.Message):
    if not await _is_limits_owner(msg):
        await _tg_send_safe(msg.chat.id, "⛔ Нет доступа.", important=False)
        return

    try:
        response = _format_limits_message(await _get_limits_usage())
    except Exception as e:
        detail = str(e).strip() or "(без сообщения)"
        response = f"❌ /api/usage: {type(e).__name__}: {detail}"

    for text, entities in _formatted_chunks(response):
        await _tg_send_safe(
            msg.chat.id,
            text,
            entities=entities,
            important=False,
        )


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text, lambda msg: msg.text and msg.text.strip() == "/restart")
async def handle_restart(msg: types.Message):
    if msg.chat.id != config.get("group_id"):
        return
    member = await msg.chat.get_member(msg.from_user.id)
    if member.status not in ("administrator", "creator"):
        await msg.reply("⛔ Only admins can restart.")
        return
    # Прямой `systemctl` отсюда убивал живые ходы мимо дренажа: мост живёт в ТОМ ЖЕ
    # процессе, поэтому зовём тот же серверный workflow, что и кнопка дашборда (#220 T4).
    # Второго пути рестарта не оставляем — именно из-за него дренаж и обходили бы.
    from app.routes import system

    await msg.reply(
        "🔄 Перезапуск Orchestra: дренаж запущен, ждём живые ходы. "
        "Кого всё-таки разорвало — узнает из своего журнала после старта."
    )
    await system.restart_server()


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.voice)
async def handle_voice(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return
    t_total = time.monotonic()

    token = await _register_media(msg, session)
    path = await _download_file(msg.voice.file_id, _media_name("voice", ".oga", msg), msg.voice.file_unique_id)
    tag = _sender_tag(msg)
    if not path:
        await _resolve_media(token, f"{tag}{_forward_meta(msg)}[voice: file too large]")
        return
    text, err = await _transcribe_audio(
        path,
        msg.voice.file_unique_id,
        session_name=session.name,
        scope=session.scope,
    )
    total_ms = (time.monotonic() - t_total) * 1000
    logger.info(f"handle_voice total={total_ms:.0f}ms duration={msg.voice.duration}s")
    if text:
        await _resolve_media(token, f"{tag}{_forward_meta(msg)}[voice: {path} | {text}]")
    elif err:
        await _resolve_media(token, f"{tag}{_forward_meta(msg)}[voice: {path} | ❌ {err}]")
    else:
        await _resolve_media(token, f"{tag}{_forward_meta(msg)}[voice: {path}]")


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.video_note)
async def handle_video_note(msg: types.Message):
    orch_name, session = await _resolve_orch(msg)
    if not session:
        return

    token = await _register_media(msg, session)
    tag = _sender_tag(msg)
    path = await _download_file(msg.video_note.file_id, _media_name("videonote", ".mp4", msg), msg.video_note.file_unique_id)
    if not path:
        await _resolve_media(token, f"{tag}{_forward_meta(msg)}[video_note: file too large]")
        return
    audio_path = path.replace(".mp4", ".oga")
    p = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", path, "-vn", "-acodec", "libopus", "-y", audio_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await p.communicate()
    if p.returncode == 0:
        text, err = await _transcribe_audio(
            audio_path,
            msg.video_note.file_unique_id,
            session_name=session.name,
            scope=session.scope,
        )
        if text:
            await _resolve_media(token, f"{tag}{_forward_meta(msg)}[video_note: {path} | {text}]")
            return
        if err:
            await _resolve_media(token, f"{tag}{_forward_meta(msg)}[video_note: {path} | ❌ {err}]")
            return
    await _resolve_media(token, f"{tag}{_forward_meta(msg)}[video_note: {path}]")


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
    global bot, _manager
    from dotenv import load_dotenv
    load_dotenv()
    await _reset_tg_delivery_state()

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
            except Exception as _e:
                # Без текста ошибки все 10 попыток выглядят одинаково и не говорят,
                # почему Local Bot API не поднимается (порт? proxychains? бинарник?).
                logger.info(
                    f"Waiting for Local Bot API ({_attempt+1}/10): {type(_e).__name__}: {_e}"
                )
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
        for name, thread_id in list(config["topics"].items()):
            _ensure_stream(name, thread_id)
        await asyncio.sleep(0)
        _ensure_owned_task(
            _bridge_tasks,
            "topic_sync",
            topic_sync_loop,
        )
        await _sync_all_topic_statuses()
        await ensure_topics()
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
            # Uvicorn owns process signals. Aiogram's default handlers overwrite
            # them, so SIGINT would restart only polling instead of stopping Orchestra.
            await dp.start_polling(bot, handle_signals=False)
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
    debounce_tasks = [
        buf.debounce_task
        for buf in list(_buffers.values())
        if buf.debounce_task is not None
    ]
    _mirror_stopping.update(config.get("mirrors", {}))
    owners = set(_tasks)
    owners.update(_stream_tasks.values())
    owners.update(_topic_status_tasks.values())
    owners.update(_topic_create_tasks.values())
    owners.update(_bridge_tasks.values())
    owners.update(_mirror_tasks.values())
    owners.update(debounce_tasks)
    current = asyncio.current_task()
    for task in owners:
        if task is not current and not task.done():
            task.cancel()
    await asyncio.gather(
        *(task for task in owners if task is not current),
        return_exceptions=True,
    )
    _tasks.clear()
    _stream_tasks.clear()
    _topic_status_tasks.clear()
    _topic_status_desired.clear()
    _topic_status.clear()
    _topic_create_tasks.clear()
    _bridge_tasks.clear()
    _mirror_tasks.clear()
    _mirror_outboxes.clear()
    _mirror_dropped.clear()
    _buffers.clear()
    await _reset_tg_delivery_state()
    try:
        if bot:
            await bot.session.close()
    finally:
        # A handler racing past the unhook must see inactive state even if close fails.
        bot = None
        _manager = None
        _mirror_stopping.clear()


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
