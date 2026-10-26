import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CARDS = [
    {"id": "K-1", "title": "Login page", "column": "doing", "priority": "high"},
    {"id": "K-2", "title": "Password reset", "column": "doing", "blocked": "dependency"},
    {"id": "K-3", "title": "Payment keys", "column": "review", "blocked": "external"},
    {"id": "K-4", "title": "Pricing copy", "column": "review"},
    {"id": "K-5", "title": "New logo", "column": "backlog", "blocked": "decision"},
    {"id": "K-6", "title": "Footer links", "column": "done"},
    {"id": "K-7", "title": "Search cache", "column": "doing", "blocked": "dependency"},
]


def run(module, *args):
    return subprocess.run([sys.executable, "-m", module, *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_inputs(tmp_path, cards, **settings):
    board = tmp_path / "board.json"
    board.write_text(json.dumps({"cards": cards}), encoding="utf-8")
    data = {"board_file": str(board)}
    data.update(settings)
    path = tmp_path / "kanban.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path), board


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_report_with_limits_and_blocked_cards(tmp_path):
    settings, _ = make_inputs(tmp_path, CARDS, wip_limits={"backlog": 4, "doing": 3, "review": 1})
    out = tmp_path / "wip.json"
    r = run("kanbanlite.wip", settings, str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    report = read_json(out)
    assert report["columns"] == [
        {"name": "backlog", "cards": 1, "limit": 4, "status": "ok"},
        {"name": "doing", "cards": 3, "limit": 3, "status": "full"},
        {"name": "review", "cards": 2, "limit": 1, "status": "over"},
        {"name": "done", "cards": 1, "limit": None, "status": "ok"},
    ]
    assert report["blocked"] == {"dependency": ["K-2", "K-7"], "external": ["K-3"],
                                 "decision": ["K-5"]}
    assert list(report["blocked"]) == ["dependency", "external", "decision"]
    assert sorted(report) == ["blocked", "columns"]


def test_no_limits_set(tmp_path):
    cards = [dict(card) for card in CARDS]
    for card in cards:
        card.pop("blocked", None)
    settings, _ = make_inputs(tmp_path, cards)
    out = tmp_path / "wip.json"
    r = run("kanbanlite.wip", settings, str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    report = read_json(out)
    assert [(c["name"], c["cards"], c["limit"], c["status"]) for c in report["columns"]] == [
        ("backlog", 1, None, "ok"), ("doing", 3, None, "ok"),
        ("review", 2, None, "ok"), ("done", 1, None, "ok"),
    ]
    assert report["blocked"] == {"dependency": [], "external": [], "decision": []}


def test_limit_for_unknown_column(tmp_path):
    settings, _ = make_inputs(tmp_path, CARDS, wip_limits={"doing": 5, "testing": 2})
    out = tmp_path / "wip.json"
    r = run("kanbanlite.wip", settings, str(out))
    assert r.returncode == 2
    assert not out.exists()


def test_limit_that_is_not_a_positive_whole_number(tmp_path):
    for bad in (0, 2.5):
        settings, _ = make_inputs(tmp_path, CARDS, wip_limits={"doing": bad})
        out = tmp_path / "wip.json"
        r = run("kanbanlite.wip", settings, str(out))
        assert r.returncode == 2, bad
        assert not out.exists()


def test_unknown_blocked_kind(tmp_path):
    cards = CARDS + [{"id": "K-8", "title": "Holiday", "column": "backlog", "blocked": "vacation"}]
    settings, _ = make_inputs(tmp_path, cards, wip_limits={"doing": 5})
    out = tmp_path / "wip.json"
    r = run("kanbanlite.wip", settings, str(out))
    assert r.returncode == 2
    assert not out.exists()


def test_board_commands_keep_blocked_value(tmp_path):
    settings, board = make_inputs(tmp_path, CARDS)
    r = run("kanbanlite.cli", "--settings", settings, "move", "K-1", "review")
    assert r.returncode == 0, r.stdout + r.stderr
    saved = {card["id"]: card for card in read_json(board)["cards"]}
    assert saved["K-2"]["blocked"] == "dependency"
    assert saved["K-3"]["blocked"] == "external"
    assert saved["K-5"]["blocked"] == "decision"
    assert "blocked" not in saved["K-1"]
    assert "blocked" not in saved["K-4"]
