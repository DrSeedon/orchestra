"""Owner activity telemetry: metadata-only events and deterministic allocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


UTC = timezone.utc
PRESENCE_TTL = timedelta(seconds=60)
INPUT_MAX_AGE = timedelta(minutes=5)
MESSAGE_BASE = timedelta(minutes=1)
MESSAGE_LENGTH_STEP = 500
MESSAGE_MAX = timedelta(minutes=10)


def utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def message_window_seconds(content_length: int, voice_duration_sec: float = 0) -> float:
    """One minute of pre-send thinking, extended by message size or voice length.

    500 characters buy one extra minute, capped at ten minutes.  This is a
    metadata-only proxy for typing/thinking: it avoids pretending that the text
    itself is telemetry while not making a long request look like a one-line one.
    A known voice duration is the stronger signal and is never shortened below
    the one-minute floor.
    """
    length = max(0, int(content_length or 0))
    text_seconds = 60.0 + 60.0 * (length // MESSAGE_LENGTH_STEP)
    voice_seconds = max(0.0, float(voice_duration_sec or 0))
    return min(MESSAGE_MAX.total_seconds(), max(MESSAGE_BASE.total_seconds(), text_seconds, voice_seconds))


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    scope: str
    source: str
    event_id: str = ""
    priority: int = 0
    event_ts: datetime | None = None
    token: str = ""
    estimated: bool = False

    def clipped(self, start: datetime, end: datetime) -> "Interval | None":
        left = max(utc(self.start), utc(start))
        right = min(utc(self.end), utc(end))
        if right <= left:
            return None
        return Interval(left, right, self.scope, self.source, self.event_id,
                        self.priority, self.event_ts, self.token, self.estimated)


def _active(state: dict, at: datetime) -> bool:
    return bool(
        state.get("visible")
        and state.get("focused")
        and state.get("scope")
        and state.get("last_input_at")
        and at - state["last_input_at"] <= INPUT_MAX_AGE
    )


def presence_intervals(events: Iterable[dict], start: datetime, end: datetime) -> list[Interval]:
    """Turn tab events into 60-second heartbeats, cutting at every state event."""
    start, end = utc(start), utc(end)
    grouped: dict[str, list[dict]] = {}
    for raw in events:
        token = str(raw.get("tab_token") or "")
        if token:
            grouped.setdefault(token, []).append(raw)
    result: list[Interval] = []
    for token, rows in grouped.items():
        rows.sort(key=lambda row: (utc(row["ts"]), str(row.get("event_id") or "")))
        state = {"scope": "", "visible": False, "focused": False, "last_input_at": None}
        previous_at: datetime | None = None
        for row in rows:
            at = utc(row["ts"])
            if previous_at is not None and at > previous_at and _active(state, previous_at):
                right = min(at, previous_at + PRESENCE_TTL)
                item = Interval(previous_at, right, str(state["scope"]), "presence",
                                str(row.get("event_id") or ""), priority=2,
                                event_ts=previous_at, token=token)
                clipped = item.clipped(start, end)
                if clipped:
                    result.append(clipped)
            for key in ("scope", "visible", "focused"):
                if row.get(key) is not None:
                    state[key] = row[key]
            if row.get("last_input_at"):
                state["last_input_at"] = utc(row["last_input_at"])
            previous_at = at
        if previous_at is not None and _active(state, previous_at):
            item = Interval(previous_at, previous_at + PRESENCE_TTL,
                            str(state["scope"]), "presence", str(rows[-1].get("event_id") or ""),
                            priority=2, event_ts=previous_at, token=token)
            clipped = item.clipped(start, end)
            if clipped:
                result.append(clipped)
    return _coalesce_same(result)


def message_intervals(rows: Iterable[dict], start: datetime, end: datetime) -> list[Interval]:
    result: list[Interval] = []
    for row in rows:
        ts = utc(row.get("ts"))
        duration = message_window_seconds(row.get("content_length", 0), row.get("voice_duration_sec", 0))
        left = utc(row.get("start_ts")) if row.get("start_ts") else ts - timedelta(seconds=duration)
        right = utc(row.get("end_ts")) if row.get("end_ts") else ts
        if right <= left:
            left = ts - timedelta(seconds=duration)
            right = ts
        item = Interval(left, right, str(row.get("scope") or ""),
                        "estimated" if row.get("estimated") else "message",
                        str(row.get("event_id") or ""), priority=1,
                        event_ts=ts, estimated=bool(row.get("estimated")))
        clipped = item.clipped(start, end)
        if clipped:
            result.append(clipped)
    return result


def allocate_intervals(intervals: Iterable[Interval], start: datetime, end: datetime) -> list[Interval]:
    """Union intervals and assign every second to exactly one winning scope.

    Presence wins over message estimates.  Within one source the most recent
    event wins, then the token/id tie-breaks make replay order irrelevant.
    """
    start, end = utc(start), utc(end)
    clipped = [item.clipped(start, end) for item in intervals]
    items = [item for item in clipped if item]
    boundaries = {start, end}
    for item in items:
        boundaries.add(item.start)
        boundaries.add(item.end)
    points = sorted(boundaries)
    allocated: list[Interval] = []
    for left, right in zip(points, points[1:]):
        if right <= left:
            continue
        active = [item for item in items if item.start < right and item.end > left]
        if not active:
            continue
        winner = max(active, key=lambda item: (
            item.priority,
            utc(item.event_ts or item.start),
            item.token,
            item.event_id,
            item.scope,
        ))
        allocated.append(Interval(left, right, winner.scope, winner.source,
                                  winner.event_id, winner.priority, winner.event_ts,
                                  winner.token, winner.estimated))
    return _coalesce_same(allocated)


def _coalesce_same(intervals: Iterable[Interval]) -> list[Interval]:
    ordered = sorted(intervals, key=lambda item: (item.start, item.end, item.scope, item.source, item.event_id))
    result: list[Interval] = []
    for item in ordered:
        if item.end <= item.start:
            continue
        if result and result[-1].end == item.start and result[-1].scope == item.scope \
                and result[-1].source == item.source and result[-1].estimated == item.estimated:
            previous = result[-1]
            result[-1] = Interval(previous.start, item.end, previous.scope, previous.source,
                                  previous.event_id, previous.priority, previous.event_ts,
                                  previous.token, previous.estimated)
        else:
            result.append(item)
    return result


def split_local_days(intervals: Iterable[Interval], tz, start: datetime, end: datetime) -> list[Interval]:
    result: list[Interval] = []
    for item in intervals:
        cursor = max(item.start, utc(start))
        right = min(item.end, utc(end))
        while cursor < right:
            local = cursor.astimezone(tz)
            next_day = (local.replace(hour=0, minute=0, second=0, microsecond=0)
                        + timedelta(days=1)).astimezone(UTC)
            chunk_end = min(right, next_day)
            result.append(Interval(cursor, chunk_end, item.scope, item.source,
                                   item.event_id, item.priority, item.event_ts,
                                   item.token, item.estimated))
            cursor = chunk_end
    return result


def group_sessions(intervals: Iterable[Interval], gap_seconds: int = 300, tz=UTC) -> list[dict]:
    """Merge allocated intervals per scope/day; preserve source and estimate labels."""
    ordered = sorted(intervals, key=lambda item: (item.scope, item.start, item.end))
    result: list[dict] = []
    for item in ordered:
        day = item.start.astimezone(tz).date().isoformat()
        if result:
            current = result[-1]
            gap = (item.start - current["end"]).total_seconds()
            if current["scope"] == item.scope and current["day"] == day and gap <= gap_seconds:
                current["end"] = max(current["end"], item.end)
                current["duration_sec"] = (current["end"] - current["start"]).total_seconds()
                sources = set(current["source"].split("+")) | {item.source}
                current["source"] = "+".join(sorted(sources))
                current["estimated"] = current["estimated"] or item.estimated
                continue
        result.append({
            "day": day, "scope": item.scope, "start": item.start,
            "end": item.end, "duration_sec": (item.end - item.start).total_seconds(),
            "source": item.source, "estimated": item.estimated,
        })
    return result
