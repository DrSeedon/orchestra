"""Semantic markers shared by turn lifecycle and delivery transports."""

SILENT_TURN_MARKER = "[[ORCHESTRA:SILENT_TURN]]"


def is_silent_turn_text(value: object) -> bool:
    """Return true only for the exact protocol token in an agent text row."""
    return isinstance(value, str) and value == SILENT_TURN_MARKER


def is_successful_silent_turn(last_text: object, turn_ok: bool) -> bool:
    """Recognize a successful turn by its last typed assistant text event."""
    return bool(turn_ok) and is_silent_turn_text(last_text)
