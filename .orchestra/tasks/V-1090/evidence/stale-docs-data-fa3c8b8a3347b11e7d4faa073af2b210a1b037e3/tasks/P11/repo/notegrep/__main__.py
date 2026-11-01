"""Command line for notegrep: ``build`` an index, ``search`` it."""

import argparse
import sys
from pathlib import Path

from notegrep.index import build_index, load_index, save_index
from notegrep.search import search, search_any


def build_parser() -> argparse.ArgumentParser:
    """Create the parser for the ``build`` and ``search`` commands.

    :returns: the argument parser.
    """
    parser = argparse.ArgumentParser(prog="notegrep", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="index a notes folder")
    build.add_argument("root", type=Path, help="the notes folder")
    find = commands.add_parser("search", help="search the saved index of a notes folder")
    find.add_argument("root", type=Path, help="the notes folder")
    find.add_argument("words", nargs="+", help="the words to look for")
    find.add_argument("--any", action="store_true", help="rank notes that contain any word")
    return parser


def run_build(root: Path) -> int:
    """Index a notes folder and save the index next to the notes.

    :param root: the notes folder.
    :returns: the exit status.
    """
    index = build_index(root)
    target = save_index(index, root)
    print(f"indexed {len(index)} words into {target}")
    return 0


def run_search(root: Path, words: list[str], any_word: bool) -> int:
    """Search the saved index of a notes folder and show the matching notes.

    :param root: the notes folder.
    :param words: the query words.
    :param any_word: rank notes by hit count instead of requiring every word.
    :returns: the exit status; 1 when no note matches.
    """
    index = load_index(root)
    query = " ".join(words)
    if any_word:
        lines = [f"{name}\t{hits}" for name, hits in search_any(index, query)]
    else:
        lines = search(index, query)
    for line in lines:
        print(line)
    return 0 if lines else 1


def main(argv: list[str] | None = None) -> int:
    """Run the notegrep command line.

    :param argv: the arguments; the process arguments when ``None``.
    :returns: the exit status; 2 when the notes folder is missing.
    """
    args = build_parser().parse_args(argv)
    if not args.root.is_dir():
        print(f"error: {args.root} is not a folder", file=sys.stderr)
        return 2
    if args.command == "build":
        return run_build(args.root)
    return run_search(args.root, args.words, args.any)


if __name__ == "__main__":
    sys.exit(main())
