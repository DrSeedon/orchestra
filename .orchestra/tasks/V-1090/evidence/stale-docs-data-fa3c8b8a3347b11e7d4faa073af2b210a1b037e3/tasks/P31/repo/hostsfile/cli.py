"""Command line for looking up and editing host names in a hosts file.

Run it as ``python -m hostsfile.cli COMMAND HOSTS_FILE ...`` with one of the
commands show, add and remove.
"""
import argparse
import sys
from pathlib import Path

from .editor import add_entry, find_name, remove_name
from .model import HostsFileError
from .parser import read_hosts
from .writer import write_hosts


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the command line.

    Returns:
        A parser with the show, add and remove commands.
    """
    parser = argparse.ArgumentParser(prog="python -m hostsfile.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="list the entries that map a name")
    show.add_argument("hosts")
    show.add_argument("name")
    add = commands.add_parser("add", help="add an entry at the end of the file")
    add.add_argument("hosts")
    add.add_argument("address")
    add.add_argument("names", nargs="+")
    add.add_argument("--comment", default="")
    remove = commands.add_parser("remove", help="remove a name from all entries")
    remove.add_argument("hosts")
    remove.add_argument("name")
    return parser


def run(args: argparse.Namespace) -> int:
    """Carry out one parsed command.

    Args:
        args: The parsed arguments.

    Returns:
        The exit status: 0 on success, 1 if show finds no entry.

    Raises:
        HostsFileError: If the file does not exist or the edit is not valid.
    """
    path = Path(args.hosts)
    if not path.is_file():
        raise HostsFileError(f"hosts file not found: {path}")
    lines = read_hosts(path)
    if args.command == "show":
        found = find_name(lines, args.name)
        for line in found:
            print(f"{line.number}: {line.address}")
        return 0 if found else 1
    if args.command == "add":
        lines = add_entry(lines, args.address, args.names, args.comment)
    else:
        lines = remove_name(lines, args.name)
    write_hosts(path, lines)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: The arguments without the program name. None means sys.argv[1:].

    Returns:
        The exit status of the command, or 2 if the request fails.
    """
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except HostsFileError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
