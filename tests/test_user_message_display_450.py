from datetime import datetime, timezone

from app.tg_bridge import _format_user_message_log
from app.user_message_display import (
    add_user_message_time_prefix,
    annotate_user_message,
    strip_user_message_time_prefix,
)


def _log(content: str, ts: str) -> dict:
    return {
        "type": "user_message",
        "content": content,
        "ts": ts,
        "origin": "user",
        "origin_detail": {"senders": ["user"]},
    }


def test_display_annotation_preserves_durable_content_and_strips_generated_prefix():
    ts = "2026-09-03T10:38:30+00:00"
    row = _log("[17:38] вопрос", ts)

    displayed = annotate_user_message(row)

    assert row["content"] == "[17:38] вопрос"
    assert displayed["content"] == "[17:38] вопрос"
    assert displayed["display_content"] == "вопрос"
    assert _format_user_message_log(row, "orch") == "👤\nвопрос"


def test_display_prefix_accepts_generation_and_write_minute_boundary():
    generated = add_user_message_time_prefix(
        "вопрос",
        datetime(2026, 9, 3, 10, 38, 59, 500000, tzinfo=timezone.utc),
    )
    written_at = "2026-09-03T10:39:00+00:00"

    assert generated == "[17:38] вопрос"
    assert strip_user_message_time_prefix(generated, written_at) == "вопрос"


def test_display_prefix_does_not_strip_similar_quoted_timestamp():
    quoted = "[17:38] — это цитата из лога"
    row = _log(quoted, "2026-09-03T10:00:00+00:00")

    assert annotate_user_message(row)["display_content"] == quoted
    assert _format_user_message_log(row, "orch") == f"👤\n{quoted}"
