"""Select subsets of parsed entries."""
from datetime import datetime
from typing import Iterable, List

from logsift.parser import LogEntry, level_rank


def at_least(entries: List[LogEntry], level: str) -> List[LogEntry]:
    """Entries at or above a level, e.g. 'warning' keeps WARNING, ERROR and CRITICAL."""
    minimum = level_rank(level)
    return [entry for entry in entries if level_rank(entry.level) >= minimum]


def from_sources(entries: List[LogEntry], sources: Iterable[str]) -> List[LogEntry]:
    """Entries whose source is one of the given names."""
    wanted = {source.strip() for source in sources}
    return [entry for entry in entries if entry.source in wanted]


def between(entries: List[LogEntry], start: datetime, end: datetime) -> List[LogEntry]:
    """Entries with start <= timestamp < end."""
    if end <= start:
        raise ValueError(f"empty time window: {start} .. {end}")
    return [entry for entry in entries if start <= entry.timestamp < end]


def containing(entries: List[LogEntry], text: str) -> List[LogEntry]:
    """Entries whose message contains the text, ignoring case."""
    needle = text.lower()
    return [entry for entry in entries if needle in entry.message.lower()]
