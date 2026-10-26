"""Columns, priorities and the card record of a board."""
from dataclasses import dataclass
from enum import Enum


class Column(Enum):
    """The columns of the board, in board order."""

    BACKLOG = "backlog"
    DOING = "doing"
    REVIEW = "review"
    DONE = "done"


class Priority(Enum):
    """How urgent a card is."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass
class Card:
    """One card on the board."""

    id: str
    title: str
    column: Column
    priority: Priority = Priority.NORMAL
    owner: str | None = None


def parse_column(name: str) -> Column:
    """Return the column called ``name``; case does not matter."""
    try:
        return Column(str(name).strip().lower())
    except ValueError:
        raise ValueError(f"unknown column: {name!r}") from None


def parse_priority(name: str) -> Priority:
    """Return the priority called ``name``; case does not matter."""
    try:
        return Priority(str(name).strip().lower())
    except ValueError:
        raise ValueError(f"unknown priority: {name!r}") from None


def card_from_dict(data: dict) -> Card:
    """Build a card from one entry of the board file."""
    missing = [key for key in ("id", "title", "column") if not data.get(key)]
    if missing:
        raise ValueError(f"card is missing {', '.join(missing)}")
    return Card(
        id=str(data["id"]),
        title=str(data["title"]),
        column=parse_column(data["column"]),
        priority=parse_priority(data.get("priority", "normal")),
        owner=data.get("owner") or None,
    )


def card_to_dict(card: Card) -> dict:
    """Return the board file entry for a card."""
    data = {
        "id": card.id,
        "title": card.title,
        "column": card.column.value,
        "priority": card.priority.value,
    }
    if card.owner:
        data["owner"] = card.owner
    return data
