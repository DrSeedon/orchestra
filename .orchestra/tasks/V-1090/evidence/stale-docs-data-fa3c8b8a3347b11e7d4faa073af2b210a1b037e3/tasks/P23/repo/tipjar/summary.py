"""Write a bill summary with the tip and an even split.

Run as ``python -m tipjar.summary BILL_CSV PEOPLE OUTPUT_TXT [--tip PERCENT]``.
"""
import argparse
import sys

from .bill import BillItem, load_bill, subtotal
from .money import format_amount
from .split import split_evenly
from .tips import parse_percent, tip_amount, total_with_tip

LINE = "{:<20} {:>10}"


def summary_lines(items: list[BillItem], people: int, percent: int | None) -> list[str]:
    """Build the lines of the summary: items, subtotal, tip, total and one line per person."""
    sub = subtotal(items)
    tip = tip_amount(sub, percent)
    total = total_with_tip(sub, tip)
    lines = [LINE.format(item.name, format_amount(item.amount)) for item in items]
    lines.append(LINE.format("subtotal", format_amount(sub)))
    if tip is None:
        lines.append(LINE.format("tip", "-"))
    else:
        lines.append(LINE.format("tip ({}%)".format(percent), format_amount(tip)))
    lines.append(LINE.format("total", format_amount(total)))
    lines.append("")
    for number, share in enumerate(split_evenly(total, people), start=1):
        lines.append(LINE.format("person {}".format(number), format_amount(share)))
    return lines


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line of the summary command."""
    parser = argparse.ArgumentParser(prog="python -m tipjar.summary")
    parser.add_argument("bill", help="bill CSV file with the header item,amount")
    parser.add_argument("people", type=int, help="number of people who share the bill")
    parser.add_argument("output", help="text file to write")
    parser.add_argument("--tip", help="tip percentage, such as 15 or 15%%")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the summary command and return its exit status."""
    args = parse_args(argv)
    try:
        items = load_bill(args.bill)
        percent = parse_percent(args.tip)
        lines = summary_lines(items, args.people, percent)
    except (OSError, ValueError) as error:
        sys.stderr.write("error: {}\n".format(error))
        return 2
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
