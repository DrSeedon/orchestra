"""Owner-time telemetry API. Payloads contain metadata only, never message text."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator

from app.db import _conn
from app.owner_activity import (
    allocate_intervals,
    group_sessions,
    message_intervals,
    presence_intervals,
    split_local_days,
    utc,
)


router = APIRouter(prefix="/api/owner-activity", tags=["owner-activity"])
KRASNOYARSK = ZoneInfo("Asia/Krasnoyarsk")


class PresenceEventRequest(BaseModel):
    event_id: str = Field(min_length=8, max_length=128)
    tab_token: str = Field(min_length=8, max_length=128)
    event_type: Literal["focus", "blur", "scope", "input", "ping", "visibility"]
    scope: str = Field(default="", max_length=4096)
    ts: datetime | None = None
    visible: bool | None = None
    focused: bool | None = None
    last_input_at: datetime | None = None

    @field_validator("scope")
    @classmethod
    def valid_scope(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("scope contains NUL")
        return value.rstrip("/") or value


def _parse_bound(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    try:
        return utc(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid datetime: {value!r}") from error


def _events(start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
    # One heartbeat can cross the requested boundary; the extra five minutes also
    # preserves an input-age state when a report starts in the middle of a session.
    presence_start = (start - timedelta(minutes=5)).isoformat()
    with _conn() as connection:
        presence_rows = connection.execute(
            """SELECT event_id, event_type, ts, scope, tab_token, visible, focused,
                      last_input_at
                 FROM owner_activity_events
                WHERE kind='presence' AND ts >= ? AND ts < ?
                ORDER BY tab_token, ts, event_id""",
            (presence_start, end.isoformat()),
        ).fetchall()
        message_rows = connection.execute(
            """SELECT event_id, ts, start_ts, end_ts, scope, content_length,
                      voice_duration_sec, estimated
                 FROM owner_activity_events
                WHERE kind='message' AND end_ts > ? AND start_ts < ?
                ORDER BY ts, event_id""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return ([dict(row) for row in presence_rows], [dict(row) for row in message_rows])


def activity_result(start: datetime, end: datetime, scope: str = "") -> dict:
    start, end = utc(start), utc(end)
    if end <= start:
        raise ValueError("to must be after from")
    presence_rows, message_rows = _events(start, end)
    raw = presence_intervals(presence_rows, start, end)
    raw.extend(message_intervals(message_rows, start, end))
    allocated = allocate_intervals(raw, start, end)
    if scope:
        allocated = [item for item in allocated if item.scope == scope]
    day_intervals = split_local_days(allocated, KRASNOYARSK, start, end)
    sessions = group_sessions(day_intervals, tz=KRASNOYARSK)
    totals: dict[tuple[str, str, str, bool], float] = {}
    for item in day_intervals:
        key = (item.start.astimezone(KRASNOYARSK).date().isoformat(), item.scope,
               item.source, item.estimated)
        totals[key] = totals.get(key, 0.0) + (item.end - item.start).total_seconds()
    total_rows = [
        {"day": day, "scope": item_scope, "source": source, "estimated": estimated,
         "seconds": round(seconds, 3), "hours": round(seconds / 3600, 4)}
        for (day, item_scope, source, estimated), seconds in sorted(totals.items())
    ]
    return {
        "timezone": "Asia/Krasnoyarsk",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "sessions": [
            {**row, "start": row["start"].isoformat(), "end": row["end"].isoformat(),
             "hours": round(row["duration_sec"] / 3600, 4)}
            for row in sessions
        ],
        "totals": total_rows,
        "seconds": round(sum((item.end - item.start).total_seconds() for item in allocated), 3),
        "hours": round(sum((item.end - item.start).total_seconds() for item in allocated) / 3600, 4),
    }


@router.post("/events")
def record_event(req: PresenceEventRequest):
    at = utc(req.ts or datetime.now(timezone.utc))
    last_input = utc(req.last_input_at) if req.last_input_at else None
    with _conn() as connection:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO owner_activity_events
               (event_id, kind, event_type, ts, start_ts, end_ts, scope, tab_token,
                visible, focused, last_input_at, source, estimated, created_at)
               VALUES (?, 'presence', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'presence', 0, ?)""",
            (
                req.event_id, req.event_type, at.isoformat(), at.isoformat(), at.isoformat(),
                req.scope, req.tab_token,
                None if req.visible is None else int(req.visible),
                None if req.focused is None else int(req.focused),
                last_input.isoformat() if last_input else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return {"ok": True, "duplicate": cursor.rowcount == 0}


@router.get("/sessions")
def sessions(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    scope: str = "",
):
    now = datetime.now(timezone.utc)
    start = _parse_bound(from_, now - timedelta(days=1))
    end = _parse_bound(to, now)
    return activity_result(start, end, scope)


@router.get("/summary")
def summary(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    scope: str = "",
):
    now = datetime.now(timezone.utc)
    return activity_result(_parse_bound(from_, now - timedelta(days=1)),
                           _parse_bound(to, now), scope)
