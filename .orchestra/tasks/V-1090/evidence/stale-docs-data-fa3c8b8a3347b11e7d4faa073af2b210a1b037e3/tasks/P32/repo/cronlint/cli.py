"""Command line tool: ``python -m cronlint.cli check|next CRONTAB``."""
import argparse
import sys
from datetime import datetime
from typing import Optional

from cronlint.crontab import read_crontab
from cronlint.errors import CronError
from cronlint.parser import parse_expression

TIME_FORMAT = "%Y-%m-%d %H:%M"


def parse_time(text: str) -> datetime:
    """Parse a ``YYYY-MM-DD HH:MM`` argument."""
    try:
        return datetime.strptime(text, TIME_FORMAT)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD HH:MM, got {text!r}") from None


def check(path: str) -> int:
    """Show every entry of a crontab that does not parse; return their number."""
    bad = 0
    for entry in read_crontab(path):
        try:
            parse_expression(entry.expression)
        except CronError as err:
            print(f"line {entry.line}: {err}")
            bad += 1
    return bad


def show_next(path: str, start: datetime, count: int) -> None:
    """Show the next ``count`` runs of every entry of a crontab."""
    for entry in read_crontab(path):
        runs = parse_expression(entry.expression).runs(start, count)
        stamps = ", ".join(run.strftime(TIME_FORMAT) for run in runs) or "never"
        print(f"line {entry.line}: {stamps}  {entry.command}")


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the tool."""
    parser = argparse.ArgumentParser(prog="python -m cronlint.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    check_cmd = commands.add_parser("check", help="report entries that do not parse")
    check_cmd.add_argument("crontab")
    next_cmd = commands.add_parser("next", help="list the next runs of every entry")
    next_cmd.add_argument("crontab")
    next_cmd.add_argument("--start", type=parse_time, help="YYYY-MM-DD HH:MM, default now")
    next_cmd.add_argument("--count", type=int, default=3)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Run the tool; return 0 on success, 1 for bad entries, 2 for other errors."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            bad = check(args.crontab)
            noun = "entry" if bad == 1 else "entries"
            print(f"{bad} bad {noun}")
            return 1 if bad else 0
        start = args.start or datetime.now().replace(second=0, microsecond=0)
        show_next(args.crontab, start, args.count)
    except (CronError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
