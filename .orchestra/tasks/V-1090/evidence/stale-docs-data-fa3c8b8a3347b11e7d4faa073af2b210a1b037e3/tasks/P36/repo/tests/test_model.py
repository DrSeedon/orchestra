import pytest

from kanbanlite.model import Card, Column, Priority, card_from_dict, card_to_dict, parse_column


def test_parse_column_ignores_case_and_spaces():
    assert parse_column(" Doing ") is Column.DOING
    assert parse_column("done") is Column.DONE


def test_parse_column_rejects_unknown_name():
    with pytest.raises(ValueError, match="unknown column"):
        parse_column("testing")


def test_card_from_dict_fills_defaults():
    card = card_from_dict({"id": "K-1", "title": "Write notes", "column": "backlog"})
    assert card == Card(id="K-1", title="Write notes", column=Column.BACKLOG)
    assert card.priority is Priority.NORMAL
    assert card.owner is None


def test_card_from_dict_reports_missing_keys():
    with pytest.raises(ValueError, match="missing title, column"):
        card_from_dict({"id": "K-1"})


def test_card_from_dict_rejects_unknown_priority():
    with pytest.raises(ValueError, match="unknown priority"):
        card_from_dict({"id": "K-1", "title": "x", "column": "backlog", "priority": "urgent"})


def test_card_to_dict_round_trip():
    entry = {"id": "K-4", "title": "Fix login", "column": "review", "priority": "high",
             "owner": "ana"}
    assert card_to_dict(card_from_dict(entry)) == entry


def test_card_to_dict_leaves_out_missing_owner():
    card = Card(id="K-2", title="Docs", column=Column.DONE, priority=Priority.LOW)
    assert card_to_dict(card) == {"id": "K-2", "title": "Docs", "column": "done",
                                  "priority": "low"}
