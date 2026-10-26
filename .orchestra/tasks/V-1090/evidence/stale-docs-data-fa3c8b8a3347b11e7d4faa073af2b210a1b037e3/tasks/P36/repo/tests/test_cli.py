import json

from kanbanlite.cli import format_board, main
from kanbanlite.board import load_board
from kanbanlite.model import Card, Column


def make_settings(tmp_path):
    board = tmp_path / "board.json"
    settings = tmp_path / "kanban.json"
    settings.write_text(json.dumps({"board_file": str(board)}), encoding="utf-8")
    return str(settings), str(board)


def test_add_then_move(tmp_path, capsys):
    settings, board = make_settings(tmp_path)
    assert main(["--settings", settings, "add", "Write release notes", "--owner", "ana"]) == 0
    assert main(["--settings", settings, "move", "K-1", "Review"]) == 0
    cards = load_board(board)
    assert [(card.id, card.column, card.owner) for card in cards] == [("K-1", Column.REVIEW, "ana")]
    out = capsys.readouterr().out
    assert "added K-1" in out
    assert "moved K-1 to review" in out


def test_move_unknown_card_fails(tmp_path, capsys):
    settings, _ = make_settings(tmp_path)
    assert main(["--settings", settings, "move", "K-5", "done"]) == 2
    assert "no card with id K-5" in capsys.readouterr().err


def test_format_board():
    cards = [Card(id="K-1", title="Login", column=Column.DOING, owner="ana")]
    text = format_board(cards)
    assert text.splitlines() == [
        "BACKLOG (0)",
        "DOING (1)",
        "  K-1 [normal] Login @ana",
        "REVIEW (0)",
        "DONE (0)",
    ]
