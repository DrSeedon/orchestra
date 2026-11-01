import json
from datetime import date

from plantcare.cli import main
from plantcare.history import read_history


def make_inputs(tmp_path, with_history=False):
    plants = tmp_path / "plants.json"
    plants.write_text(json.dumps({"plants": [
        {"name": "Fern", "interval": 3, "last_watered": "2026-07-08"},
        {"name": "Basil", "interval": 1, "last_watered": "2026-07-07"},
    ]}), encoding="utf-8")
    lines = [f"plants_file = {plants}"]
    if with_history:
        lines.append(f"history_file = {tmp_path / 'history.txt'}")
    settings = tmp_path / "plantcare.cfg"
    settings.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(settings)


def test_list(tmp_path, capsys):
    settings = make_inputs(tmp_path)
    assert main(["--settings", settings, "--date", "2026-07-10", "list"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Fern: every 3 days, next 2026-07-11",
        "Basil: every 1 days, next 2026-07-08",
    ]


def test_due(tmp_path, capsys):
    settings = make_inputs(tmp_path)
    assert main(["--settings", settings, "--date", "2026-07-10", "due"]) == 0
    assert capsys.readouterr().out.splitlines() == ["Basil (2 days late)"]


def test_water_saves_plants_and_history(tmp_path, capsys):
    settings = make_inputs(tmp_path, with_history=True)
    assert main(["--settings", settings, "--date", "2026-07-10", "water", "Basil"]) == 0
    data = json.loads((tmp_path / "plants.json").read_text(encoding="utf-8"))
    assert data["plants"][1]["last_watered"] == "2026-07-10"
    assert read_history(tmp_path / "history.txt") == [(date(2026, 7, 10), "Basil")]
    assert "watered Basil" in capsys.readouterr().out


def test_unknown_plant_gives_status_2(tmp_path, capsys):
    settings = make_inputs(tmp_path)
    assert main(["--settings", settings, "water", "Rose"]) == 2
    assert "unknown plant: Rose" in capsys.readouterr().err
