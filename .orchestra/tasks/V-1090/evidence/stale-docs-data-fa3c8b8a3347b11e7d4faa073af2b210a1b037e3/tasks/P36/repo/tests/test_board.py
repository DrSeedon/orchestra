import json

import pytest

from kanbanlite.board import (add_card, cards_by_column, find_card, load_board, move_card,
                              next_card_id, save_board)
from kanbanlite.model import Card, Column, Priority
from kanbanlite.settings import DEFAULTS


@pytest.fixture
def cards():
    return [
        Card(id="K-1", title="Login page", column=Column.DOING, priority=Priority.HIGH),
        Card(id="K-2", title="Footer links", column=Column.BACKLOG, owner="ben"),
        Card(id="K-7", title="Release notes", column=Column.DONE),
    ]


def test_missing_board_file_is_empty(tmp_path):
    assert load_board(str(tmp_path / "none.json")) == []


def test_save_and_load_round_trip(tmp_path, cards):
    path = str(tmp_path / "board.json")
    save_board(path, cards)
    assert load_board(path) == cards


def test_load_rejects_duplicate_ids(tmp_path):
    entry = {"id": "K-1", "title": "x", "column": "backlog"}
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"cards": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate card ids: K-1"):
        load_board(str(path))


def test_next_card_id(cards):
    assert next_card_id(cards) == "K-8"
    assert next_card_id([]) == "K-1"


def test_add_card_uses_settings(cards):
    settings = dict(DEFAULTS, default_priority="low")
    card = add_card(cards, "  Pricing page ", settings, owner="ana")
    assert card == Card(id="K-8", title="Pricing page", column=Column.BACKLOG,
                        priority=Priority.LOW, owner="ana")
    assert cards[-1] is card


def test_add_card_rejects_long_title(cards):
    settings = dict(DEFAULTS, max_title_length=5)
    with pytest.raises(ValueError, match="longer than 5"):
        add_card(cards, "Too long a title", settings)


def test_move_card(cards):
    card = move_card(cards, "K-2", Column.REVIEW)
    assert card.column is Column.REVIEW


def test_find_card_unknown_id(cards):
    with pytest.raises(KeyError):
        find_card(cards, "K-99")


def test_cards_by_column_keeps_board_order(cards):
    grouped = cards_by_column(cards)
    assert list(grouped) == [Column.BACKLOG, Column.DOING, Column.REVIEW, Column.DONE]
    assert [card.id for card in grouped[Column.DOING]] == ["K-1"]
    assert grouped[Column.REVIEW] == []
