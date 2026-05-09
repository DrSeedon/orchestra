"""Telegram bridge — mirrors Orchestra orchestrators to TG group topics."""

import asyncio
import json
import logging
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tg-bridge")

ORCHESTRA_URL = "http://127.0.0.1:8888"
CONFIG_PATH = Path(__file__).parent.parent / "data" / "tg_bridge.json"

bot: Bot = None
dp = Dispatcher()
config = {"group_id": 0, "topics": {}, "token": ""}


def save_config():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def load_config():
    global config
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())


async def orchestra_api(method: str, path: str, **kwargs):
    async with httpx.AsyncClient(base_url=ORCHESTRA_URL, timeout=10) as client:
        if method == "GET":
            r = await client.get(path, params=kwargs.get("params"))
        elif method == "POST":
            r = await client.post(path, json=kwargs.get("json"))
        else:
            return None
        return r.json() if r.status_code < 400 else None


async def ensure_topics():
    orchs = await orchestra_api("GET", "/api/orchestrators")
    if not orchs:
        return
    group_id = config["group_id"]
    if not group_id:
        return

    for o in orchs:
        name = o["name"]
        if name in config["topics"]:
            continue
        try:
            result = await bot.create_forum_topic(chat_id=group_id, name=f"🎯 {name}")
            config["topics"][name] = result.message_thread_id
            save_config()
            logger.info(f"Created topic for {name}: {result.message_thread_id}")
        except Exception as e:
            logger.error(f"Failed to create topic for {name}: {e}")


async def stream_logs(orch_name: str, thread_id: int):
    scope = None
    orchs = await orchestra_api("GET", "/api/orchestrators")
    if orchs:
        for o in orchs:
            if o["name"] == orch_name:
                scope = o.get("scope", "")
                break
    if not scope:
        return

    # Skip old logs — only stream new ones
    logs = await orchestra_api("GET", f"/api/sessions/{orch_name}/logs",
                               params={"scope": scope, "after_id": 0})
    last_id = logs[-1]["id"] if logs else 0

    while True:
        try:
            logs = await orchestra_api("GET", f"/api/sessions/{orch_name}/logs",
                                       params={"scope": scope, "after_id": last_id})
            if logs:
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
                        text = f"🔧 {c[:500]}"
                    elif t == "tool_result":
                        text = f"📎 {c[:1000]}"
                    elif t == "error":
                        text = f"❌ {c[:1000]}"
                    elif t == "status":
                        text = f"⚡ {c}"
                    else:
                        continue
                    try:
                        try:
                            await bot.send_message(
                                config["group_id"], text,
                                message_thread_id=thread_id,
                                parse_mode="Markdown",
                            )
                        except Exception:
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
    if not msg.text or not msg.message_thread_id:
        return
    thread_id = msg.message_thread_id
    orch_name = None
    for name, tid in config["topics"].items():
        if tid == thread_id:
            orch_name = name
            break
    if not orch_name:
        return

    orchs = await orchestra_api("GET", "/api/orchestrators")
    scope = ""
    if orchs:
        for o in orchs:
            if o["name"] == orch_name:
                scope = o.get("scope", "")
                break

    result = await orchestra_api("POST", f"/api/sessions/{orch_name}/send",
                                  json={"message": msg.text, "scope": scope})
    if result and result.get("ok"):
        await msg.react([types.ReactionTypeEmoji(emoji="👍")])
    else:
        await msg.reply(f"❌ {result}")


async def main():
    global bot
    import os, sys
    from dotenv import load_dotenv
    load_dotenv()

    load_config()
    token = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TG_BRIDGE_TOKEN", config.get("token", ""))
    group = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.getenv("TG_BRIDGE_GROUP", config.get("group_id", 0)))
    if not token:
        print("Set TG_BRIDGE_TOKEN in .env or pass as arg")
        sys.exit(1)
    config["token"] = token
    config["group_id"] = group
    save_config()

    bot = Bot(token=config["token"], default=DefaultBotProperties(parse_mode=None))

    await ensure_topics()

    for name, thread_id in config["topics"].items():
        asyncio.create_task(stream_logs(name, thread_id))
        logger.info(f"Streaming {name} → thread {thread_id}")

    asyncio.create_task(topic_sync_loop())
    logger.info(f"TG Bridge started | group={config['group_id']} | topics={len(config['topics'])}")
    await dp.start_polling(bot)


async def topic_sync_loop():
    while True:
        await asyncio.sleep(30)
        old_topics = set(config["topics"].keys())
        await ensure_topics()
        new_topics = set(config["topics"].keys()) - old_topics
        for name in new_topics:
            thread_id = config["topics"][name]
            asyncio.create_task(stream_logs(name, thread_id))
            logger.info(f"New orchestrator {name} → thread {thread_id}")


if __name__ == "__main__":
    asyncio.run(main())
