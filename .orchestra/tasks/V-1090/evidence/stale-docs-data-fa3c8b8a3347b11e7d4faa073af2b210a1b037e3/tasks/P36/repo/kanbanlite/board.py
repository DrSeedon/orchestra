"""Read and write the board file and change the cards on it."""
import json
import os

from kanbanlite.model import Card, Column, card_from_dict, card_to_dict, parse_priority


def load_board(path: str) -> list[Card]:
    """Return the cards of the board file; a missing file is an empty board."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    cards = [card_from_dict(entry) for entry in data.get("cards", [])]
    ids = [card.id for card in cards]
    duplicates = sorted({card_id for card_id in ids if ids.count(card_id) > 1})
    if duplicates:
        raise ValueError(f"{path}: duplicate card ids: {', '.join(duplicates)}")
    return cards


def save_board(path: str, cards: list[Card]) -> None:
    """Write the cards to the board file."""
    data = {"cards": [card_to_dict(card) for card in cards]}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def next_card_id(cards: list[Card]) -> str:
    """Return the next free card id: K-1, K-2, ..."""
    numbers = [int(card.id[2:]) for card in cards
               if card.id.startswith("K-") and card.id[2:].isdigit()]
    return f"K-{max(numbers, default=0) + 1}"


def find_card(cards: list[Card], card_id: str) -> Card:
    """Return the card with the given id."""
    for card in cards:
        if card.id == card_id:
            return card
    raise KeyError(f"no card with id {card_id}")


def add_card(cards: list[Card], title: str, settings: dict, owner: str | None = None) -> Card:
    """Add a new card to the backlog column and return it."""
    title = title.strip()
    if not title:
        raise ValueError("a card needs a title")
    if len(title) > settings["max_title_length"]:
        raise ValueError(f"title is longer than {settings['max_title_length']} characters")
    card = Card(
        id=next_card_id(cards),
        title=title,
        column=Column.BACKLOG,
        priority=parse_priority(settings["default_priority"]),
        owner=owner,
    )
    cards.append(card)
    return card


def move_card(cards: list[Card], card_id: str, column: Column) -> Card:
    """Move a card to another column and return it."""
    card = find_card(cards, card_id)
    card.column = column
    return card


def cards_by_column(cards: list[Card]) -> dict[Column, list[Card]]:
    """Group the cards by column, in board order; every column is present."""
    grouped: dict[Column, list[Card]] = {column: [] for column in Column}
    for card in cards:
        grouped[card.column].append(card)
    return grouped
