"""Write daily summaries to CSV next to the input file."""

import csv
import logging
import os

from .daily import DailySummary

logger = logging.getLogger(__name__)

COLUMNS = ("station", "day", "count", "temp_min", "temp_max", "temp_mean", "humidity_mean")


def summary_path(input_path: str, out_dir: str | None = None) -> str:
    """Output file for an input CSV: ``<name>.daily.csv`` in ``out_dir`` or beside the input."""
    stem, _ = os.path.splitext(os.path.basename(input_path))
    folder = out_dir if out_dir is not None else os.path.dirname(input_path)
    return os.path.join(folder, stem + ".daily.csv")


def cell(value: object) -> str:
    """CSV text for one value; None becomes an empty cell."""
    return "" if value is None else str(value)


def write_summaries(summaries: list[DailySummary], target: str) -> str:
    """Write summaries as CSV to ``target``, creating its folder if needed."""
    folder = os.path.dirname(target)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for s in summaries:
            writer.writerow([cell(getattr(s, c)) for c in COLUMNS])
    logger.info("wrote %d summaries to %s", len(summaries), target)
    return target
