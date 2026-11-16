"""Durable outbound queue, pacing, quiet hours, retries and a said ledger."""
import hashlib
import ipaddress
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from app import db
from app.always_on import seconds, start_loop


def enqueue(recipient, scope, channel, target, body, *, urgent=False,
            min_interval_seconds=None, quiet_start_hour=None, quiet_end_hour=None,
            timezone_name="UTC", dedupe_key="", dedupe_window_seconds=86400, max_attempts=5):
    if channel not in {"telegram", "webhook", "dashboard"}:
        raise ValueError("unsupported outbox channel")
    if not target or not body.strip():
        raise ValueError("target and body are required")
    if channel == "webhook":
        url = urlsplit(target)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("webhook target must be an HTTPS URL without credentials or fragment")
    ZoneInfo(timezone_name)
    if (quiet_start_hour is None) != (quiet_end_hour is None):
        raise ValueError("quiet hours require both start and end")
    for hour in (quiet_start_hour,quiet_end_hour):
        if hour is not None and (type(hour) is not int or not 0 <= hour <= 23):
            raise ValueError("quiet hours must be integers in 0..23")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
        raise ValueError("max_attempts must be in 1..100")
    pacing = seconds(min_interval_seconds if min_interval_seconds is not None
                     else os.environ.get("ORCHESTRA_OUTBOX_MIN_INTERVAL_SECONDS", "2"))
    window = seconds(dedupe_window_seconds)
    fingerprint = hashlib.sha256(" ".join(body.split()).encode()).hexdigest()
    now, message_id = time.time(), uuid4().hex
    with db._conn() as c:
        c.execute("""INSERT INTO outbox_messages
            (id,recipient,scope,channel,target,body,urgent,min_interval_seconds,quiet_start_hour,
             quiet_end_hour,timezone_name,dedupe_key,content_fingerprint,dedupe_window_seconds,
             max_attempts,next_attempt_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (message_id,recipient,scope,channel,target,body,int(urgent),pacing,quiet_start_hour,
             quiet_end_hour,timezone_name,dedupe_key,fingerprint,window,max_attempts,now,now))
        return dict(c.execute("SELECT * FROM outbox_messages WHERE id=?", (message_id,)).fetchone())


outbox_enqueue = enqueue


def list_messages(recipient=None, scope=None, limit=100):
    with db._conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT * FROM outbox_messages WHERE (? IS NULL OR recipient=?) AND
               (? IS NULL OR scope=?) ORDER BY created_at DESC LIMIT ?""",
            (recipient,recipient,scope,scope,max(1,min(int(limit),1000))))]


def quiet_until(row, now):
    if row["urgent"] or row["quiet_start_hour"] is None:
        return now
    start,end = row["quiet_start_hour"],row["quiet_end_hour"]
    if start == end:  # An equal pair disables quiet hours.
        return now
    tz = ZoneInfo(row["timezone_name"])
    local = datetime.fromtimestamp(now,tz)
    quiet = start <= local.hour < end if start < end else local.hour >= start or local.hour < end
    if not quiet:
        return now
    day = local.date() + timedelta(days=int(start > end and local.hour >= start))
    end_local = datetime(day.year,day.month,day.day,end,tzinfo=tz)
    return end_local.timestamp()


async def _send(row, manager):
    if row["channel"] == "dashboard":
        session = manager.get_by_name(row["target"],row["scope"])
        if session is None:
            raise ValueError("dashboard target does not exist")
        event_id = f"outbox:{row['id']}"
        # Replays after a crash reuse the durable log instead of adding another.
        with db._conn() as c:
            exists = c.execute("SELECT 1 FROM logs WHERE session_id=? AND event_id=?",
                               (session.id,event_id)).fetchone()
        if not exists:
            db.add_log(session.id,datetime.now(timezone.utc),"text",row["body"],event_id=event_id)
        from app.live_broker import broker
        broker.publish(session.id,{"type":"text","content":row["body"],"event_id":event_id})
    elif row["channel"] == "telegram":
        # Do not import/start the bridge in an inactive process (or in tests).
        bridge = sys.modules.get("app.tg_bridge")
        if bridge is None or not bridge.bot:
            raise RuntimeError("TG bridge not active")
        result = await bridge.send_text_to_tg(row["body"],scope=row["target"],sender=row["recipient"])
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "TG delivery failed"))
    else:
        parsed = urlsplit(row["target"])
        # Explicit outbound-only transport. No redirects, env proxies, credentials,
        # private/loopback/link-local destinations or DNS rebinding to internal hosts.
        addresses = await __import__("asyncio").get_running_loop().getaddrinfo(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("webhook destination must resolve to public addresses")
        address = addresses[0][4][0]
        netloc = f"[{address}]" if ":" in address else address
        netloc += f":{parsed.port or 443}"
        url = parsed._replace(netloc=netloc).geturl()
        async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=15) as client:
            response = await client.post(url, json={"text":row["body"],"event_id":f"outbox:{row['id']}"},
                headers={"Host":parsed.netloc,"Idempotency-Key":row["id"]},
                extensions={"sni_hostname":parsed.hostname})
            response.raise_for_status()


def _claim(now):
    with db._conn() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("""UPDATE outbox_messages
                     SET state=CASE WHEN attempts>=max_attempts THEN 'failed' ELSE 'pending' END,
                         lease_until=NULL, last_error='ExpiredDispatchLease'
                     WHERE state='dispatching' AND lease_until<=?""",(now,))
        rows = c.execute("""SELECT * FROM outbox_messages WHERE state='pending' AND next_attempt_at<=?
                            ORDER BY urgent DESC,created_at LIMIT 100""",(now,)).fetchall()
        for row in rows:
            duplicate = c.execute("""SELECT 1 FROM outbox_said_ledger
                WHERE channel=? AND target=? AND said_at>=?
                AND ((? != '' AND dedupe_key=?) OR content_fingerprint=?) LIMIT 1""",
                (row["channel"],row["target"],now-row["dedupe_window_seconds"],row["dedupe_key"],
                 row["dedupe_key"],row["content_fingerprint"])).fetchone()
            if duplicate:
                c.execute("UPDATE outbox_messages SET state='suppressed_duplicate' WHERE id=?",(row["id"],))
                continue
            held = quiet_until(row,now)
            last = c.execute("SELECT MAX(said_at) FROM outbox_said_ledger WHERE channel=? AND target=?",
                             (row["channel"],row["target"])).fetchone()[0]
            if last is not None:
                held = max(held,last+row["min_interval_seconds"])
            busy = c.execute("SELECT 1 FROM outbox_messages WHERE channel=? AND target=? AND state='dispatching'",
                             (row["channel"],row["target"])).fetchone()
            if busy or held > now:
                c.execute("UPDATE outbox_messages SET next_attempt_at=? WHERE id=?",
                          (max(held,now+0.1),row["id"]))
                continue
            c.execute("UPDATE outbox_messages SET state='dispatching',lease_until=?,attempts=attempts+1 WHERE id=?",
                      (now+60,row["id"]))
            return dict(c.execute("SELECT * FROM outbox_messages WHERE id=?",(row["id"],)).fetchone())
    return None


async def dispatch_outbox(manager=None, *, now=None):
    now = time.time() if now is None else seconds(now)
    sent = 0
    # Bounded pass; transport is outside SQLite transactions.
    for _ in range(100):
        row = _claim(now)
        if row is None:
            break
        try:
            await _send(row,manager)
        except Exception as error:
            transient = not isinstance(error, ValueError)
            if isinstance(error,httpx.HTTPStatusError):
                transient = error.response.status_code in {408,425,429} or error.response.status_code >= 500
            retry = transient and row["attempts"] < row["max_attempts"]
            # URLs/transport error strings may contain credentials; retain only class/status.
            detail = type(error).__name__
            if isinstance(error,httpx.HTTPStatusError):
                detail += f": HTTP {error.response.status_code}"
            with db._conn() as c:
                c.execute("""UPDATE outbox_messages SET state=?,lease_until=NULL,last_error=?,next_attempt_at=?
                             WHERE id=? AND state='dispatching'""",
                          ("pending" if retry else "failed",detail,
                           now+min(3600,2 ** min(row["attempts"],12)),row["id"]))
        else:
            with db._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("UPDATE outbox_messages SET state='sent',sent_at=?,lease_until=NULL WHERE id=?",
                          (now,row["id"]))
                c.execute("""INSERT OR IGNORE INTO outbox_said_ledger
                    (id,channel,target,dedupe_key,content_fingerprint,said_at) VALUES (?,?,?,?,?,?)""",
                    (row["id"],row["channel"],row["target"],row["dedupe_key"],row["content_fingerprint"],now))
            sent += 1
    return sent


def start_outbox_dispatcher(manager):
    return start_loop("outbox",lambda: dispatch_outbox(manager),1.0)
