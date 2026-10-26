"""Plain-text summary report."""
import argparse
import os
import sys
from typing import List, Optional

from logsift.parser import LogEntry
from logsift.reader import read_log_files
from logsift.summary import count_by_level, count_by_source, error_rate, time_span, top_messages


def render_summary(entries: List[LogEntry], top: int = 3) -> List[str]:
    """Report lines: span, level counts, error rate, busiest sources, top messages."""
    span = time_span(entries)
    if span is None:
        return ["no entries"]
    lines = [f"{len(entries)} entries from {span[0].isoformat()} to {span[1].isoformat()}"]
    levels = count_by_level(entries)
    lines.append("levels: " + ", ".join(f"{name}={count}" for name, count in levels.items()))
    lines.append(f"error rate: {error_rate(entries):.1%}")
    sources = list(count_by_source(entries).items())[:top]
    lines.append("sources: " + ", ".join(f"{name} ({count})" for name, count in sources))
    for shape, count in top_messages(entries, top):
        lines.append(f"  {count:>5}  {shape}")
    return lines


def print_summary(entries: List[LogEntry], top: int = 3) -> None:
    """Print the summary report to stdout."""
    for line in render_summary(entries, top):
        print(line)


def main(argv: Optional[List[str]] = None) -> int:
    """Print the summary report of one or more files; exit status 2 if a file is missing."""
    parser = argparse.ArgumentParser(prog="python -m logsift.report", description="Summarize log files.")
    parser.add_argument("files", nargs="+", metavar="FILE", help="log file to read")
    parser.add_argument("--top", type=int, default=3, help="number of sources and messages to show")
    args = parser.parse_args(argv)
    for path in args.files:
        if not os.path.isfile(path):
            print(f"error: file not found: {path}", file=sys.stderr)
            return 2
    print_summary(read_log_files(args.files), args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
