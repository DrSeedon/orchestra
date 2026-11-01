"""Command line of meterread: the usage and cost reports."""
import argparse
import sys

from meterread.money import format_amount
from meterread.readings import load_readings
from meterread.settings import Settings, load_settings
from meterread.usage import Usage, average_per_day, flat_cost, meter_usage


def usage_line(usage: Usage) -> str:
    """Describe the usage of one meter on one line.

    :param usage: the usage of one meter
    :returns: the line, without a newline
    """
    average = average_per_day(usage)
    per_day = "n/a" if average is None else f"{average} kWh/day"
    return f"{usage.meter}: {usage.kwh} kWh in {usage.days} days ({per_day})"


def cost_line(usage: Usage, settings: Settings) -> str:
    """Describe the flat-rate cost of one meter on one line.

    :param usage: the usage of one meter
    :param settings: the prices and the currency
    :returns: the line, without a newline
    """
    cost = format_amount(flat_cost(usage, settings))
    return f"{usage.meter}: {usage.kwh} kWh, {usage.days} days, {cost} {settings.currency}"


def build_parser() -> argparse.ArgumentParser:
    """Build the parser of the command line.

    :returns: the parser with the usage and cost commands
    """
    parser = argparse.ArgumentParser(prog="meterread")
    commands = parser.add_subparsers(dest="command", required=True)
    usage_cmd = commands.add_parser("usage", help="energy used per meter")
    usage_cmd.add_argument("readings")
    cost_cmd = commands.add_parser("cost", help="flat-rate cost per meter")
    cost_cmd.add_argument("readings")
    cost_cmd.add_argument("--settings", default=None, metavar="FILE")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command.

    :param argv: the arguments, or None for ``sys.argv``
    :returns: the exit status: 0, or 2 when a file is missing or broken
    """
    args = build_parser().parse_args(argv)
    settings, error = load_settings(getattr(args, "settings", None))
    if error is None:
        readings, error = load_readings(args.readings)
    if error is None:
        usages, error = meter_usage(readings)
    if error is not None:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for usage in usages:
        if args.command == "usage":
            print(usage_line(usage))
        else:
            print(cost_line(usage, settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
