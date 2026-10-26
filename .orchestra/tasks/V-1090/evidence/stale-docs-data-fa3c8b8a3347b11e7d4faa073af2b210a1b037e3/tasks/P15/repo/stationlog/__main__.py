"""Command line: ``python -m stationlog INPUT_CSV [--out-dir DIR]``."""

import argparse
import logging
import sys

from .daily import daily_summaries
from .export import summary_path, write_summaries
from .qc import apply_qc
from .readings import load_readings

logger = logging.getLogger("stationlog")


def main(argv: list[str] | None = None) -> int:
    """Load, check and summarize one station export; return the exit status."""
    parser = argparse.ArgumentParser(prog="stationlog", description="Daily station summaries.")
    parser.add_argument("input_csv", help="station export with one row per reading")
    parser.add_argument("--out-dir", help="folder for the summary file (default: beside the input)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        readings = load_readings(args.input_csv)
    except (OSError, ValueError) as exc:
        logger.error("cannot load %s: %s", args.input_csv, exc)
        return 2
    summaries = daily_summaries(apply_qc(readings))
    write_summaries(summaries, summary_path(args.input_csv, args.out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
