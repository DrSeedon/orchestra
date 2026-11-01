"""Command line of playlistr: list the playlists of a folder and check their files."""
import argparse
import os
import sys
from typing import Dict, List, Optional

from playlistr.library import load_playlists, missing_tracks
from playlistr.tracks import display_name, format_duration, total_seconds


def print_problems(problems: Dict[str, str]) -> None:
    """Tell the user about the playlist files that could not be read."""
    for name, reason in sorted(problems.items()):
        print(f"skipped {name}: {reason}")


def run_list(folder: str) -> int:
    """Show every playlist with its number of tracks and its length."""
    playlists, problems = load_playlists(folder)
    print_problems(problems)
    for playlist in playlists:
        length = format_duration(total_seconds(playlist.tracks))
        print(f"{playlist.name}: {len(playlist.tracks)} tracks, {length}")
    return 0


def run_check(folder: str) -> int:
    """Show the tracks whose file is missing; exit status 1 when there are any."""
    playlists, problems = load_playlists(folder)
    print_problems(problems)
    status = 0
    for playlist in playlists:
        for track in missing_tracks(playlist):
            print(f"{playlist.name}: missing {track.location} ({display_name(track)})")
            status = 1
    return status


def build_parser() -> argparse.ArgumentParser:
    """Build the parser with the list and check commands."""
    parser = argparse.ArgumentParser(prog="playlistr")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("list", "show the playlists"), ("check", "find missing files")):
        command = commands.add_parser(name, help=text)
        command.add_argument("folder")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Run one command and return its exit status."""
    args = build_parser().parse_args(argv)
    if not os.path.isdir(args.folder):
        print(f"error: {args.folder} is not a folder", file=sys.stderr)
        return 2
    if args.command == "list":
        return run_list(args.folder)
    return run_check(args.folder)


if __name__ == "__main__":
    sys.exit(main())
