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
                    text = c[:3900]
                elif t == "tool":
                    tool_name = c.split(":")[0] if ":" in c else c[:50]
                    tool_body = c[len(tool_name)+1:].strip()[:400] if ":" in c else ""
                    text = f"🔧 `{tool_name}`" + (f"\n||{tool_body}||" if tool_body else "")
                elif t == "tool_result":
                    preview = c[:100].replace("\n", " ")
                    full = c[:800] if len(c) > 100 else ""
                    text = f"📎 {preview}" + (f"\n||{full}||" if full else "")
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
