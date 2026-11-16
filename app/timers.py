"""Durable native alarms and recurring schedules; no sleeping model process."""
import math
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from app import db, mailbox
from app.always_on import seconds, start_loop
from app.events import MessageProvenance


def _cron_fields(expression):
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron_expr requires five fields")
    values = []
    for field, (low, high) in zip(fields, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))):
        selected = set()
        for part in field.split(","):
            pieces = part.split("/")
            if len(pieces) > 2:
                raise ValueError("invalid cron step")
            step = int(pieces[1]) if len(pieces) == 2 else 1
            if step < 1:
                raise ValueError("cron step must be positive")
            bounds = pieces[0]
            if bounds == "*":
                start, end = low, high
            elif "-" in bounds:
                start, end = map(int, bounds.split("-"))
            else:
                start = int(bounds)
                end = high if len(pieces) == 2 else start
            if not low <= start <= end <= high:
                raise ValueError("cron field out of range")
            selected.update(range(start, end + 1, step))
        values.append(selected)
    return fields, values


def next_cron_due(cron_expr, timezone_name, after):
    """Calendar search with DST round-trip checks, standard DOM/DOW OR semantics."""
    fields, (minutes, hours, days, months, weekdays) = _cron_fields(cron_expr)
    tz = ZoneInfo(timezone_name)
    day = datetime.fromtimestamp(after, tz).date()
    weekdays = {value % 7 for value in weekdays}
    for offset in range(366 * 5):
        date = day + timedelta(days=offset)
        if date.month not in months:
            continue
        dom, dow = date.day in days, (date.weekday() + 1) % 7 in weekdays
        matches = (dom and dow if fields[2] == "*" or fields[4] == "*" else dom or dow)
        if not matches:
            continue
        candidates = []
        for hour in sorted(hours):
            for minute in sorted(minutes):
                naive = datetime(date.year, date.month, date.day, hour, minute)
                for fold in (0, 1):
                    local = naive.replace(tzinfo=tz, fold=fold)
                    stamp = local.timestamp()
                    if stamp > after and datetime.fromtimestamp(stamp, tz).replace(tzinfo=None) == naive:
                        candidates.append(stamp)
        if candidates:
            return min(candidates)
    raise ValueError("cron_expr has no occurrence within five years")


def _epoch(value):
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            value = parsed.timestamp()
    return seconds(value)


def set_timer(recipient, scope, body, *, kind="follow_up", delay_seconds=None,
              due_at=None, interval_seconds=None, cron_expr="", timezone_name="UTC",
              max_fires=None, cancel_on_sender="", cancel_on_scope="", idempotency_key=None):
    now = time.time()
    ZoneInfo(timezone_name)
    if kind not in {"follow_up", "schedule"}:
        raise ValueError("kind must be follow_up or schedule")
    if due_at is not None and delay_seconds is not None:
        raise ValueError("choose due_at or delay_seconds")
    if max_fires is not None and (type(max_fires) is not int or max_fires < 1):
        raise ValueError("max_fires must be a positive integer")
    if kind == "schedule":
        if bool(cron_expr) == (interval_seconds is not None):
            raise ValueError("schedule requires either interval_seconds or cron_expr")
        if interval_seconds is not None:
            interval_seconds = seconds(interval_seconds, minimum=10)
        if cron_expr:
            next_cron_due(cron_expr, timezone_name, now)
    elif interval_seconds is not None or cron_expr:
        raise ValueError("follow_up cannot recur")
    if due_at is not None:
        due = _epoch(due_at)
    elif delay_seconds is not None:
        due = now + seconds(delay_seconds)
    elif kind == "schedule":
        due = (next_cron_due(cron_expr, timezone_name, now) if cron_expr
               else now + interval_seconds)
    else:
        raise ValueError("follow_up requires delay_seconds or due_at")
    with db._conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            row = c.execute("SELECT * FROM timers WHERE recipient=? AND scope=? AND idempotency_key=?",
                            (recipient, scope, idempotency_key)).fetchone()
            if row:
                return dict(row)
        timer_id = uuid4().hex
        c.execute("""INSERT INTO timers
            (id,recipient,scope,body,kind,next_due_at,interval_seconds,cron_expr,timezone_name,
             max_fires,cancel_on_sender,cancel_on_scope,idempotency_key,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (timer_id,recipient,scope,body,kind,due,interval_seconds,cron_expr,timezone_name,
             max_fires,cancel_on_sender,cancel_on_scope,idempotency_key or None,now,now))
        return dict(c.execute("SELECT * FROM timers WHERE id=?", (timer_id,)).fetchone())


def list_timers(recipient=None, scope=None):
    with db._conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM timers WHERE (? IS NULL OR recipient=?) AND (? IS NULL OR scope=?) ORDER BY created_at",
            (recipient,recipient,scope,scope))]


def cancel_timer(timer_id, reason="cancelled_by_agent"):
    with db._conn() as c:
        return c.execute("UPDATE timers SET state='cancelled',cancelled_reason=?,updated_at=? WHERE id=? AND state='active'",
                         (reason,time.time(),timer_id)).rowcount == 1


async def tick_timers(manager=None, *, now=None):
    now = time.time() if now is None else seconds(now)
    addresses = set()
    fired = 0
    with db._conn() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute("SELECT * FROM timers WHERE state='active' AND next_due_at<=? ORDER BY next_due_at", (now,)).fetchall()
        for row in rows:
            fire = row["fire_count"] + 1
            done = row["kind"] == "follow_up" or (row["max_fires"] is not None and fire >= row["max_fires"])
            due = row["next_due_at"]
            if not done:
                if row["cron_expr"]:
                    due = next_cron_due(row["cron_expr"], row["timezone_name"], now)
                else:
                    interval = row["interval_seconds"]
                    due += (math.floor((now - due) / interval) + 1) * interval
            c.execute("UPDATE timers SET fire_count=?,state=?,next_due_at=?,updated_at=? WHERE id=?",
                      (fire, "completed" if done else "active", due, now, row["id"]))
            mailbox.enqueue_event(row["recipient"], row["scope"], "timer", row["body"],
                provenance=MessageProvenance("background_task", ("timer",), "timer", row["id"]),
                idempotency_key=f"timer:{row['id']}:fire:{fire}", _connection=c)
            addresses.add((row["recipient"],row["scope"]))
            fired += 1
    if manager is not None:
        import asyncio
        await asyncio.gather(*(mailbox.wake_recipient(r,s,manager=manager) for r,s in addresses))
    return fired


class TimerScheduler:
    def __init__(self, manager):
        self.manager = manager

    async def tick(self):
        await tick_timers(self.manager)
        await mailbox.recover_event_wakes(self.manager)
        from app.approvals import sweep_expired_approvals
        await sweep_expired_approvals(manager=self.manager)

    def start(self):
        return start_loop("native-timers", self.tick, 1.0)


def start_scheduler(manager):
    return TimerScheduler(manager).start()
