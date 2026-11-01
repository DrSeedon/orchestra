"""The command line: list the plants, show what is due, record a watering."""
import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from plantcare.history import append_history
from plantcare.plants import load_plants, save_plants
from plantcare.schedule import days_late, due_plants, next_watering, water
from plantcare.settings import load_settings


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the command line."""
    parser = argparse.ArgumentParser(prog="plantcare")
    parser.add_argument("--settings", type=Path, help="settings file with key = value lines")
    parser.add_argument("--date", type=date.fromisoformat, help="the day to use as today, YYYY-MM-DD")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the plants and their next watering day")
    commands.add_parser("due", help="list the plants that need water today")
    record = commands.add_parser("water", help="record that plants were watered today")
    record.add_argument("names", nargs="+", metavar="NAME")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    today = args.date or date.today()
    try:
        settings = load_settings(args.settings)
        plants = load_plants(settings.plants_file, settings.default_interval)
        if args.command == "water":
            watered = water(plants, args.names, today)
            save_plants(settings.plants_file, plants)
            if settings.history_file is not None:
                append_history(settings.history_file, today, [plant.name for plant in watered])
            lines = [f"watered {plant.name}" for plant in watered]
        elif args.command == "due":
            lines = [f"{plant.name} ({days_late(plant, today)} days late)"
                     for plant in due_plants(plants, today)]
        else:
            lines = [f"{plant.name}: every {plant.interval} days, next {next_watering(plant, today)}"
                     for plant in plants]
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
