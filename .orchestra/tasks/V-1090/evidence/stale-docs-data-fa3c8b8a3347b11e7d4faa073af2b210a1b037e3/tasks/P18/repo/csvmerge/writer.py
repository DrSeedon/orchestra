"""Writing tables to CSV files."""

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write_table(path: str | Path, columns: list[str], rows: list[dict[str, str]]) -> Path:
    """Write rows as a comma-separated file with the given header.

    Values for columns that a row does not have are written empty. The parent
    folders of the file are created when needed. Returns the written path.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, restval="", extrasaction="ignore",
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    logger.debug("wrote {} rows to {}".format(len(rows), target))
    return target
