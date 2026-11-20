"""ACP-only Telegram log cursor/outbox. Unknown sends block, never auto-replay."""
import asyncio
import hashlib
import json
import time
import uuid
from aiogram.exceptions import TelegramRetryAfter
from app import db


class Busy(Exception):pass
class UnknownSend(Exception):pass


def schema():
    with db._conn() as c:c.executescript("""CREATE TABLE IF NOT EXISTS acp_tg_cursor (
      destination TEXT PRIMARY KEY,session_id TEXT,last_id INTEGER,lease TEXT,until REAL);
    CREATE TABLE IF NOT EXISTS acp_tg_outbox (
      destination TEXT,log_id INTEGER,chunk INTEGER,digest TEXT,state TEXT,message_id INTEGER,
      PRIMARY KEY(destination,log_id,chunk));""")
    with db._conn() as c:
        columns = {r[1] for r in c.execute("PRAGMA table_info(acp_tg_outbox)")}
        if "next_attempt_at" not in columns:
            c.execute("ALTER TABLE acp_tg_outbox ADD COLUMN next_attempt_at REAL NOT NULL DEFAULT 0")


def destination(session_id,chat_id,topic):return f"{session_id}:{chat_id}:{topic}"


def start(session_id,chat_id,topic):
    schema();dest=destination(session_id,chat_id,topic);lease=uuid.uuid4().hex;now=time.time()
    with db._conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT * FROM acp_tg_cursor WHERE destination=?",(dest,)).fetchone()
        if row and row["lease"] and row["until"]>now:raise Busy("ACP Telegram destination already owned")
        if row is None:
            # First attachment starts at latest, never re-sends prior chat history.
            last=c.execute("SELECT COALESCE(MAX(id),0) FROM logs WHERE session_id=?",(session_id,)).fetchone()[0]
            c.execute("INSERT INTO acp_tg_cursor VALUES (?,?,?,?,?)",(dest,session_id,last,lease,now+30))
        else:
            c.execute("UPDATE acp_tg_cursor SET lease=?,until=? WHERE destination=?",(lease,now+30,dest))
            c.execute("UPDATE acp_tg_outbox SET state='unknown' WHERE destination=? AND state='sending'",(dest,))
    return dest,lease


def release(dest,lease):
    with db._conn() as c:c.execute("UPDATE acp_tg_cursor SET lease='',until=0 WHERE destination=? AND lease=?",(dest,lease))


def parts(log):
    content=str(log.get("content") or "");name=log.get("tool_name")
    if name:
        prefix,sep,body=content.partition(":")
        return str(name),body.strip() if sep and prefix.strip().replace("_","").replace("-","").replace(".","").isalnum() else content
    prefix,sep,body=content.partition(":")
    return (prefix.strip(),body.strip()) if sep else ("tool",content)


def native_markup(request):
    from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
    buttons=[[InlineKeyboardButton(text=option["name"][:64],callback_data="acpn:"+request["id"]+":"+str(i))]
             for i,option in enumerate(request["options"])]
    buttons.append([InlineKeyboardButton(text="Отмена",callback_data="acpn:"+request["id"]+":cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_log(log,bridge):
    kind=log["type"];content=log["content"];markup=None
    if kind=="native_request":
        request=json.loads(content);content=("Вопрос агента" if request["kind"]=="question" else "Подтверждение действия")+"\n"+request["title"]
        if request.get("details"):content+="\n"+json.dumps(request["details"],ensure_ascii=False)
        markup=native_markup(request)
    elif kind=="tool":
        name,body=parts(log);content=bridge._tool_line(name,body)+"\n"+body
    elif kind in {"tool_update","tool_result","thinking"}:
        return []
    elif kind in {"text","error"}:pass
    elif kind=="user_message":content=bridge._format_user_message_log(log,"")
    else:return []
    # Existing production Markdown formatter, no third-party renderer or fake content.
    return [(text,entities,markup if i==0 else None) for i,(text,entities) in enumerate(bridge._formatted_chunks(content))]


async def pump(session_id,chat_id,topic,dest,lease,bridge):
    now=time.time()
    with db._conn() as c:
        row=c.execute("SELECT * FROM acp_tg_cursor WHERE destination=? AND lease=?",(dest,lease)).fetchone()
        if row is None:raise Busy("Stale ACP Telegram stream lease")
        c.execute("UPDATE acp_tg_cursor SET until=? WHERE destination=? AND lease=?",(now+30,dest,lease))
        cursor=row["last_id"]
    logs=db.get_logs_forward(session_id,after_id=cursor,limit=100)
    for log in logs:
        chunks=format_log(log,bridge)
        for i,(text,entities,markup) in enumerate(chunks):
            digest=hashlib.sha256((text+(markup.model_dump_json() if markup else "")).encode()).hexdigest()
            with db._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                item=c.execute("SELECT * FROM acp_tg_outbox WHERE destination=? AND log_id=? AND chunk=?",(dest,log["id"],i)).fetchone()
                if item:
                    if item["digest"]!=digest:raise UnknownSend("ACP Telegram payload binding changed")
                    if item["state"]=="sent":continue
                    if item["state"] != "pending":
                        raise UnknownSend("ACP Telegram send outcome unknown; operator reconciliation required")
                    if item["next_attempt_at"] > time.time():return 0
            # A rate wait is definitely pre-send. Do not turn a long flood-control
            # delay/cancellation into a fictitious ambiguous Telegram send.
            await bridge._acp_wait_for_rate(chat_id)
            with db._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                current=c.execute("SELECT lease FROM acp_tg_cursor WHERE destination=?",(dest,)).fetchone()
                if current is None or current[0]!=lease:raise Busy("ACP Telegram stream lease changed during rate wait")
                c.execute("UPDATE acp_tg_cursor SET until=? WHERE destination=? AND lease=?",(time.time()+30,dest,lease))
                c.execute("INSERT INTO acp_tg_outbox (destination,log_id,chunk,digest,state,next_attempt_at) VALUES (?,?,?,?,?,0) "
                          "ON CONFLICT(destination,log_id,chunk) DO UPDATE SET state='sending',next_attempt_at=0",
                          (dest,log["id"],i,digest,"sending"))
            try:
                async with asyncio.timeout(10):
                    sent=await bridge._acp_send_once(chat_id,text,message_thread_id=topic,entities=entities,reply_markup=markup)
                mid=sent.message_id
            except TelegramRetryAfter as error:
                # Telegram explicitly rejected before delivery. Retry this same bound
                # chunk after the server delay, never an ambiguous transport failure.
                delay = max(1.0, float(error.retry_after))
                with db._conn() as c:c.execute("UPDATE acp_tg_outbox SET state='pending',next_attempt_at=? WHERE destination=? AND log_id=? AND chunk=?",
                    (time.time()+delay,dest,log["id"],i))
                return 0
            except BaseException:
                with db._conn() as c:c.execute("UPDATE acp_tg_outbox SET state='unknown' WHERE destination=? AND log_id=? AND chunk=?",(dest,log["id"],i))
                raise
            with db._conn() as c:c.execute("UPDATE acp_tg_outbox SET state='sent',message_id=? WHERE destination=? AND log_id=? AND chunk=?",(mid,dest,log["id"],i))
        with db._conn() as c:c.execute("UPDATE acp_tg_cursor SET last_id=? WHERE destination=? AND lease=?",(log["id"],dest,lease))
    return len(logs)


async def stream(session_id,chat_id,topic,bridge):
    try:dest,lease=start(session_id,chat_id,topic)
    except Busy:return
    try:
        while True:
            try:await pump(session_id,chat_id,topic,dest,lease,bridge)
            except (UnknownSend,Busy):return
            except asyncio.CancelledError:raise
            except Exception:return  # durable unknown is retained; no blind retry loop
            await asyncio.sleep(.2)
    finally:release(dest,lease)
