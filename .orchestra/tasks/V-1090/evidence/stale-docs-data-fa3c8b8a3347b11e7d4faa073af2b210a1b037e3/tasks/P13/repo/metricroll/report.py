"""Plain-text capacity report: ``python -m metricroll.report SAMPLES OUTPUT [--width SECONDS]``."""

import argparse
import sys
from typing import Dict, List, Optional, Tuple

from metricroll.series import read_series
from metricroll.stats import Summary
from metricroll.windows import DEFAULT_WIDTH, rollup_all


def format_summary(name: str, start: int, summary: Summary) -> str:
    """One report line for one metric window."""
    return (
        f"{name:<12} {start:>10}  n={summary.n:<4} "
        f"min={summary.min:.2f} max={summary.max:.2f} "
        f"mean={summary.mean:.2f} p50={summary.p50:.2f} p95={summary.p95:.2f}"
    )


def render_report(rolled: Dict[str, List[Tuple[int, Summary]]]) -> List[str]:
    """Report lines for all metrics, with a header line per metric."""
    lines: List[str] = []
    for name in sorted(rolled):
        windows = rolled[name]
        lines.append(f"== {name} ({len(windows)} windows) ==")
        lines.extend(format_summary(name, start, summary) for start, summary in windows)
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    """Write the report for a samples file and return the exit status."""
    parser = argparse.ArgumentParser(prog="metricroll.report", description="Roll up metrics.")
    parser.add_argument("samples", help="file with '<metric> <timestamp> <value>' lines")
    parser.add_argument("output", help="text file to write the report to")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH,
                        help=f"window width in seconds (default {DEFAULT_WIDTH})")
    args = parser.parse_args(argv)
    if args.width <= 0:
        parser.error(f"--width must be positive, got {args.width}")
    try:
        series = read_series(args.samples)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    lines = render_report(rollup_all(series, args.width))
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} lines for {len(series)} metrics to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
