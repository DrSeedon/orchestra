"""Command line: python -m fuelcost TRIPS VEHICLES OUTPUT [--settings FILE]."""
import argparse
import sys

from fuelcost.report import reportRows, writeReport
from fuelcost.settings import loadSettings
from fuelcost.trips import loadTrips
from fuelcost.vehicles import loadVehicles


def main(argv: list[str] | None = None) -> int:
    """Write the cost report. Return the exit status."""
    parser = argparse.ArgumentParser(prog="python -m fuelcost")
    parser.add_argument("trips")
    parser.add_argument("vehicles")
    parser.add_argument("output")
    parser.add_argument("--settings", default=None, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        settings = loadSettings(args.settings)
        vehicles = loadVehicles(args.vehicles)
        trips = loadTrips(args.trips)
        rows = reportRows(trips, vehicles, settings)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    writeReport(rows, args.output)
    currency = settings["currency"]
    total = rows[-1][-1]
    print(f"wrote {len(trips)} trips to {args.output}, total {total} {currency}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
