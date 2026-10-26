"""Command line for the board: python -m kanbanlite.cli [--settings FILE] COMMAND ..."""
import argparse
import sys

from kanbanlite.board import add_card, cards_by_column, load_board, move_card, save_board
from kanbanlite.model import Card, parse_column
from kanbanlite.settings import load_settings


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the command line."""
    parser = argparse.ArgumentParser(prog="kanbanlite")
    parser.add_argument("--settings", help="JSON settings file")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="add a card to the backlog column")
    add.add_argument("title")
    add.add_argument("--owner")
    move = commands.add_parser("move", help="move a card to another column")
    move.add_argument("card_id")
    move.add_argument("column")
    commands.add_parser("show", help="show the board")
    return parser


def format_board(cards: list[Card]) -> str:
    """Return the board as text, one block per column."""
    lines = []
    for column, column_cards in cards_by_column(cards).items():
        lines.append(f"{column.value.upper()} ({len(column_cards)})")
        for card in column_cards:
            owner = f" @{card.owner}" if card.owner else ""
            lines.append(f"  {card.id} [{card.priority.value}] {card.title}{owner}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run one command and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.settings)
        board_file = settings["board_file"]
        cards = load_board(board_file)
        if args.command == "add":
            card = add_card(cards, args.title, settings, owner=args.owner)
            save_board(board_file, cards)
            print(f"added {card.id}")
        elif args.command == "move":
            card = move_card(cards, args.card_id, parse_column(args.column))
            save_board(board_file, cards)
            print(f"moved {card.id} to {card.column.value}")
        else:
            print(format_board(cards))
    except (OSError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
