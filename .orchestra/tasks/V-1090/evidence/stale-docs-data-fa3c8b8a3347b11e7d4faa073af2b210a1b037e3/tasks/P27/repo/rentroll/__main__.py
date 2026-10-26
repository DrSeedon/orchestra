"""Command line: python -m rentroll TENANTS LEDGER OUTPUT [--sort unit|balance]."""
import argparse
import logging
import sys
from typing import List, Optional

from rentroll.ledger import load_ledger
from rentroll.report import SortOrder, rent_roll, write_rent_roll
from rentroll.tenants import load_tenants

logger = logging.getLogger("rentroll")


def main(argv: Optional[List[str]] = None) -> int:
    """Write the rent roll. Return the exit status."""
    parser = argparse.ArgumentParser(prog="python -m rentroll")
    parser.add_argument("tenants")
    parser.add_argument("ledger")
    parser.add_argument("output")
    parser.add_argument("--sort", choices=[order.value for order in SortOrder],
                        default=SortOrder.UNIT.value)
    args = parser.parse_args(argv)
    try:
        tenants = load_tenants(args.tenants)
        entries = load_ledger(args.ledger)
    except (OSError, ValueError) as exc:
        logger.error(f"error: {exc}")
        return 2
    known = {tenant.unit for tenant in tenants}
    strays = sorted({entry.unit for entry in entries} - known)
    if strays:
        logger.warning(f"left out ledger lines of units without a tenant: {', '.join(strays)}")
    lines = rent_roll(tenants, entries, SortOrder(args.sort))
    write_rent_roll(lines, args.output)
    logger.info(f"wrote {len(lines)} rent roll lines to {args.output}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
