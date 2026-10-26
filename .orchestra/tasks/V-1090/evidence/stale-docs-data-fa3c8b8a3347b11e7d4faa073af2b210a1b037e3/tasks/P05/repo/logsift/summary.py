"""Counts and rates over parsed entries."""
import re
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from logsift.parser import LEVELS, LogEntry

NUMBER = re.compile(r"\d+")


def count_by_level(entries: List[LogEntry]) -> Dict[str, int]:
    """Number of entries per level, in severity order, including zero counts."""
    counts = Counter(entry.level for entry in entries)
    return {level: counts.get(level, 0) for level in LEVELS}


def count_by_source(entries: List[LogEntry]) -> Dict[str, int]:
    """Number of entries per source, most frequent first."""
    return dict(Counter(entry.source for entry in entries).most_common())


def message_shape(message: str) -> str:
    """Message with key=value pairs dropped and digits masked, so similar messages group."""
    words = [word for word in message.split() if "=" not in word]
    return NUMBER.sub("#", " ".join(words))


def top_messages(entries: List[LogEntry], limit: int = 5) -> List[Tuple[str, int]]:
    """The most common message shapes with their counts."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    return Counter(message_shape(entry.message) for entry in entries).most_common(limit)


def error_rate(entries: List[LogEntry]) -> float:
    """Share of entries at ERROR or CRITICAL; 0.0 for no entries."""
    if not entries:
        return 0.0
    errors = sum(1 for entry in entries if entry.level in ("ERROR", "CRITICAL"))
    return errors / len(entries)


def time_span(entries: List[LogEntry]) -> Optional[Tuple[datetime, datetime]]:
    """Earliest and latest timestamp, or None for no entries."""
    if not entries:
        return None
    stamps = [entry.timestamp for entry in entries]
    return min(stamps), max(stamps)
