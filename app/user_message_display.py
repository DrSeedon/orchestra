"""Presentation helpers for user messages.

The timestamp is part of the durable message sent to the model.  These helpers
only derive a separate display value for human-facing channels.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any


USER_MESSAGE_TIMEZONE = timezone(timedelta(hours=7))
USER_MESSAGE_TIME_PREFIX_RE = re.compile(
    r"^\[(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d)\] "
)
TIMESTAMPED_USER_MESSAGE_SUBTYPES = frozenset({
    "http_send", "telegram", "telegram_fallback", "tg_restart_inbox",
})


def add_user_message_time_prefix(content: str, now: datetime | None = None) -> str:
    """Add the durable local-time prefix used for model context."""
    current = (now or datetime.now(USER_MESSAGE_TIMEZONE)).astimezone(USER_MESSAGE_TIMEZONE)
    return f"[{current:%H:%M}] {content}"


def strip_user_message_time_prefix(content: str, ts: Any = None) -> str:
    """Strip a generated prefix when it matches the log's local timestamp.

    Matching the log timestamp keeps a quoted ``[HH:MM]`` at the beginning of a
    message intact; arbitrary text has no authority to identify itself as the
    bridge-generated prefix.
    """
    match = USER_MESSAGE_TIME_PREFIX_RE.match(content)
    if not match or ts is None:
        return content
    if isinstance(ts, datetime):
        logged_at = ts
    elif isinstance(ts, str):
        try:
            logged_at = datetime.fromisoformat(ts)
        except ValueError:
            return content
    else:
        return content
    if logged_at.tzinfo is None:
        logged_at = logged_at.replace(tzinfo=timezone.utc)
    expected = logged_at.astimezone(USER_MESSAGE_TIMEZONE)
    prefix_minutes = int(match["hour"]) * 60 + int(match["minute"])
    expected_minutes = expected.hour * 60 + expected.minute
    distance = abs(prefix_minutes - expected_minutes)
    distance = min(distance, 24 * 60 - distance)
    if distance > 1:
        return content
    return content[match.end():]


def user_message_display_content(log: dict) -> str:
    """Return a user-message body for a human-facing channel."""
    content = str(log.get("content") or "")
    detail = log.get("origin_detail")
    subtype = detail.get("subtype") if isinstance(detail, dict) else ""
    if subtype in TIMESTAMPED_USER_MESSAGE_SUBTYPES:
        match = USER_MESSAGE_TIME_PREFIX_RE.match(content)
        return content[match.end():] if match else content
    if subtype:
        return content
    return strip_user_message_time_prefix(content, log.get("ts"))


def annotate_user_message(log: dict) -> dict:
    """Attach a display-only body without changing the durable content field."""
    if log.get("type") != "user_message":
        return log
    return {**log, "display_content": user_message_display_content(log)}
