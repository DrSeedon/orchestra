"""Command line: ``python -m grantpot.cli status|award FUND_DIR ...``."""
import argparse
import sys
from datetime import date

from grantpot.ledger import check_award, status_lines
from grantpot.models import Award
from grantpot.money import format_cents, parse_cents
from grantpot.store import append_award, load_awards, load_fund


def run_status(args: argparse.Namespace) -> int:
    """Show the budget, the awards and the money left."""
    fund = load_fund(args.fund_dir)
    for line in status_lines(fund, load_awards(args.fund_dir)):
        print(line)
    return 0


def run_award(args: argparse.Namespace) -> int:
    """Pay one award from the fund."""
    fund = load_fund(args.fund_dir)
    amount_cents = parse_cents(args.amount)
    check_award(fund, load_awards(args.fund_dir), amount_cents)
    day = date.fromisoformat(args.date) if args.date else date.today()
    append_award(args.fund_dir, Award(day, args.recipient, amount_cents))
    print(f"awarded {format_cents(amount_cents)} to {args.recipient}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the tool."""
    parser = argparse.ArgumentParser(prog="python -m grantpot.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="show budget, awards and money left")
    status.add_argument("fund_dir")
    status.set_defaults(func=run_status)
    award = commands.add_parser("award", help="pay an award from the fund")
    award.add_argument("fund_dir")
    award.add_argument("recipient")
    award.add_argument("amount", help="amount such as 250.00")
    award.add_argument("--date", help="YYYY-MM-DD, default today")
    award.set_defaults(func=run_award)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the tool; return 0 on success and 2 on bad input."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
