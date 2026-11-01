"""Command line: python -m sensorhub READINGS OUTPUT [--settings FILE]."""
import argparse
import sys

from sensorhub.readings import load_readings
from sensorhub.report import build_summary, write_summary
from sensorhub.settings import load_settings
from sensorhub.stats import sensor_stats


def main(argv: list[str] | None = None) -> int:
    """Write the sensor summary. Return the exit status."""
    parser = argparse.ArgumentParser(prog="python -m sensorhub")
    parser.add_argument("readings")
    parser.add_argument("output")
    parser.add_argument("--settings", default=None, metavar="FILE")
    args = parser.parse_args(argv)
    settings, error = load_settings(args.settings)
    if settings is None:
        print(f"error: {error}", file=sys.stderr)
        return 2
    readings, error = load_readings(args.readings)
    if readings is None:
        print(f"error: {error}", file=sys.stderr)
        return 2
    stats = sensor_stats(readings, settings)
    error = write_summary(build_summary(stats, settings), args.output)
    if error is not None:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"wrote {len(stats)} sensors from {len(readings)} readings to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
