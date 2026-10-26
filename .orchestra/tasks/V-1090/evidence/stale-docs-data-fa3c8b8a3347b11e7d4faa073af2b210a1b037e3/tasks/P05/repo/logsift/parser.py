"""Parse single application log lines.

A line looks like::

    2024-05-01T12:00:03 ERROR [api] request failed path=/orders status=500 duration_ms=812
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"\[(?P<source>[^\]]+)\]\s+(?P<message>.*)$"
)
FIELD_PATTERN = re.compile(r"\b(\w+)=(\S+)")
LEVELS: Tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LEVEL_ALIASES: Dict[str, str] = {"WARN": "WARNING", "ERR": "ERROR", "FATAL": "CRITICAL"}


@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    source: str
    message: str
    fields: Dict[str, str] = field(default_factory=dict)


def normalize_level(name: str) -> Optional[str]:
    """Return the canonical level name, or None if the name is not a level."""
    upper = name.strip().upper()
    upper = LEVEL_ALIASES.get(upper, upper)
    return upper if upper in LEVELS else None


def level_rank(level: str) -> int:
    """Position of a level in LEVELS (DEBUG is 0); unknown levels raise ValueError."""
    canonical = normalize_level(level)
    if canonical is None:
        raise ValueError(f"unknown level: {level}")
    return LEVELS.index(canonical)


def parse_fields(message: str) -> Dict[str, str]:
    """Extract key=value pairs from a message; later keys win."""
    return {key: value for key, value in FIELD_PATTERN.findall(message)}


def parse_line(line: str) -> Optional[LogEntry]:
    """Parse one line, or return None when the line is not a log entry."""
    match = LINE_PATTERN.match(line.strip())
    if match is None:
        return None
    level = normalize_level(match.group("level"))
    if level is None:
        return None
    try:
        timestamp = datetime.fromisoformat(match.group("timestamp"))
    except ValueError:
        return None
    message = match.group("message").strip()
    return LogEntry(timestamp, level, match.group("source").strip(), message, parse_fields(message))
