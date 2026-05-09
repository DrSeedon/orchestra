"""Telegram bridge — mirrors Orchestra orchestrators to TG group topics.

Integrated into FastAPI lifespan — no separate process needed.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from telegramify_markdown import convert as md_convert

logger = logging.getLogger("tg-bridge")

CONFIG_PATH = Path(__file__).parent.parent / "data" / "tg_bridge.json"

config = {"group_id": 0, "topics": {}, "token": ""}
bot = None
dp = Dispatcher()
_manager = None
_tasks = []


def save_config():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def load_config():
    global config
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


async def _send_expandable_return(chat_id: int, thread_id: int, header: str, body: str):
    from aiogram.types import MessageEntity, Message
    from aiogram.enums import MessageEntityType
    text = f"{header}\n{body}"
    offset = _utf16_len(header) + 1
    length = _utf16_len(body)
    try:
        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)]
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
    tool_header_end = tool_text.index("\n")
    tool_header = tool_text[:tool_header_end]
    tool_body = tool_text[tool_header_end + 1:]
    text = f"{tool_header}\n{tool_body}\n\n{result_header}\n{result_body}"
    e1_offset = _utf16_len(tool_header) + 1
    e1_length = _utf16_len(tool_body)
    e2_offset = e1_offset + e1_length + 1 + _utf16_len(result_header) + 1
    e2_length = _utf16_len(result_body)
    try:
        entities = [
            MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=e1_offset, length=e1_length),
            MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=e2_offset, length=e2_length),
        ]
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id, entities=entities)
    except Exception:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
        except Exception as e:
            logger.warning(f"TG edit failed: {e}")


async def _edit_expandable(msg, chat_id: int, header: str, body: str):
    from aiogram.types import MessageEntity
    from aiogram.enums import MessageEntityType
    text = f"{header}\n{body}"
    offset = _utf16_len(header) + 1
    length = _utf16_len(body)
    try:
        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)]
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id, entities=entities)
    except Exception:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
        except Exception as e:
            logger.warning(f"TG edit failed: {e}")


async def _send_expandable(chat_id: int, thread_id: int, header: str, body: str):
    from aiogram.types import MessageEntity
    from aiogram.enums import MessageEntityType
    text = f"{header}\n{body}"
    offset = _utf16_len(header) + 1
    length = _utf16_len(body)
    try:
        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)]
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
                    ent_dicts = [e.to_dict() for e in entities] if entities else None
                    await bot.send_message(
                        config["group_id"], converted,
                        message_thread_id=thread_id,
                        parse_mode=None, entities=ent_dicts,
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


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(msg: types.Message):
    if not msg.text or not msg.message_thread_id or not _manager:
        return
    thread_id = msg.message_thread_id
    orch_name = None
    for name, tid in config["topics"].items():
        if tid == thread_id:
            orch_name = name
            break
    if not orch_name:
        return

    session = await _manager.ensure_loaded_any(orch_name)
    if not session:
        await msg.reply(f"❌ {orch_name} not found")
        return

    await _manager.send(session.id, msg.text)
    try:
        await msg.react([types.ReactionTypeEmoji(emoji="👍")])
    except Exception:
        pass


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
