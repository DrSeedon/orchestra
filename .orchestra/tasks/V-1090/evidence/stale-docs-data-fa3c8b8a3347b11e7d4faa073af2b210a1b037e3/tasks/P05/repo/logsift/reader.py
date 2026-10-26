"""Read log files into entries, skipping lines that do not parse."""
import sys
from typing import Iterable, List

from logsift.parser import LogEntry, parse_line


def parse_lines(lines: Iterable[str], name: str = "<input>") -> List[LogEntry]:
    """Parse lines in order. Unparsable lines are reported on stderr and skipped."""
    entries: List[LogEntry] = []
    skipped = 0
    for number, line in enumerate(lines, start=1):
        text = line.rstrip("\n")
        if not text.strip():
            continue
        entry = parse_line(text)
        if entry is None:
            skipped += 1
            print(f"warning: {name}:{number}: unparsable line skipped", file=sys.stderr)
            continue
        entries.append(entry)
    if skipped:
        print(f"{name}: {skipped} line(s) skipped, {len(entries)} parsed", file=sys.stderr)
    return entries


def read_log_file(path: str) -> List[LogEntry]:
    """Read and parse one log file."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        return parse_lines(handle, path)


def read_log_files(paths: List[str]) -> List[LogEntry]:
    """Read several files and merge their entries in timestamp order."""
    entries: List[LogEntry] = []
    for path in paths:
        entries.extend(read_log_file(path))
    entries.sort(key=lambda entry: entry.timestamp)
    return entries
