"""The command line: summary and cheapest items of one price list."""
import argparse
import sys

from pricewatch.pricelist import loadPriceList
from pricewatch.report import cheapestItems, formatItem, summaryLines


def buildParser() -> argparse.ArgumentParser:
    """Return the argument parser of the command line."""
    parser = argparse.ArgumentParser(prog="pricewatch")
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summary", help="show the item count and the prices")
    summary.add_argument("file", help="price list CSV file")
    cheapest = commands.add_parser("cheapest", help="list the cheapest items")
    cheapest.add_argument("file", help="price list CSV file")
    cheapest.add_argument("--count", type=int, default=5, help="number of items (default 5)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = buildParser().parse_args(argv)
    try:
        items = loadPriceList(args.file)
        if args.command == "summary":
            lines = summaryLines(items)
        else:
            lines = [formatItem(item) for item in cheapestItems(items, args.count)]
    except (OSError, ValueError) as error:
        print("error: {}: {}".format(args.file, error), file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
