"""Audience classification for persisted status events."""

import re


_RAW_TELEMETRY_STATUS = re.compile(r"^[A-Z][A-Z0-9_]*_RAW\s+\{")


def is_internal_telemetry_status(content: str) -> bool:
    """Return whether a structured provider telemetry status is not user-facing."""
    return bool(_RAW_TELEMETRY_STATUS.match(str(content)))
