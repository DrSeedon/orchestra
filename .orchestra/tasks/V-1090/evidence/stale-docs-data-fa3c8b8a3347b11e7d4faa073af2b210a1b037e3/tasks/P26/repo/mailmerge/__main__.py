"""Command line: python -m mailmerge TEMPLATE RECIPIENTS OUTBOX."""
import argparse
import logging
import sys
from typing import Optional

from .merge import build_messages, missing_fields
from .outbox import write_outbox
from .recipients import load_recipients
from .template import load_template

logger = logging.getLogger("mailmerge")


def parse_defaults(items: list[str]) -> dict[str, str]:
    """Turn FIELD=VALUE arguments into a mapping of default values."""
    defaults: dict[str, str] = {}
    for item in items:
        name, sep, value = item.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"bad default {item!r}, expected FIELD=VALUE")
        defaults[name.strip().lower()] = value.strip()
    return defaults


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mailmerge")
    parser.add_argument("template")
    parser.add_argument("recipients")
    parser.add_argument("outbox")
    parser.add_argument("--subject", default="Hello")
    parser.add_argument("--default", action="append", default=[], metavar="FIELD=VALUE")
    args = parser.parse_args(argv)
    try:
        defaults = parse_defaults(args.default)
        body = load_template(args.template)
        recipients = load_recipients(args.recipients)
    except (OSError, ValueError) as exc:
        logger.error(f"error: {exc}")
        return 2
    columns = list(recipients[0]) if recipients else ["email"]
    missing = missing_fields(args.subject + body, columns, defaults)
    if missing:
        logger.warning(f"fields without a column or a default: {', '.join(missing)}")
    messages = build_messages(args.subject, body, recipients, defaults)
    if not messages:
        logger.error("error: no messages to write")
        return 1
    write_outbox(messages, args.outbox)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
