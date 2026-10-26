"""The command line: the size to order for each person."""
import argparse
import sys
from typing import Optional

from sizechart.chart import load_chart
from sizechart.people import load_people
from sizechart.recommend import recommend


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the command line.

    Returns:
        A parser for ``CHART PEOPLE``.
    """
    parser = argparse.ArgumentParser(prog="sizechart")
    parser.add_argument("chart", help="size chart CSV file")
    parser.add_argument("people", help="people CSV file with the measurements")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Show the size to order for each person in the people file.

    Args:
        argv: The command line arguments, without the program name.

    Returns:
        The exit status: 0 on success, 2 if a file cannot be read.
    """
    args = build_parser().parse_args(argv)
    try:
        chart = load_chart(args.chart)
        people = load_people(args.people)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for person in people:
        size = recommend(chart, person)
        print(f"{person.name}: {size.label if size else 'no size'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
