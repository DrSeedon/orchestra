import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLANTS = [
    {"name": "Fern", "interval": 2},
    {"name": "Cactus", "interval": 14},
    {"name": "Basil", "interval": 1, "last_watered": "2026-07-01"},
    {"name": "Monstera"},
    {"name": "Orchid", "interval": 5},
]


def run(*args):
    return subprocess.run([sys.executable, "-m", "plantcare.vacation", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_inputs(tmp_path, *lines):
    plants = tmp_path / "plants.json"
    plants.write_text(json.dumps({"plants": PLANTS}), encoding="utf-8")
    settings = tmp_path / "plantcare.cfg"
    text = "\n".join(["plants_file = " + str(plants)] + list(lines)) + "\n"
    settings.write_text(text, encoding="utf-8")
    return str(settings)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_plan_with_default_max_dry(tmp_path):
    settings = make_inputs(tmp_path)
    out = tmp_path / "plans" / "summer" / "trip.json"
    result = run("2026-07-10", "2026-07-20", str(out), "--settings", settings)
    assert result.returncode == 0, result.stderr
    assert read_json(out) == {
        "plants": [
            {"name": "Fern", "visits": ["2026-07-13", "2026-07-17"]},
            {"name": "Cactus", "visits": []},
            {"name": "Basil", "visits": ["2026-07-12", "2026-07-15", "2026-07-18"]},
            {"name": "Monstera", "visits": ["2026-07-18"]},
            {"name": "Orchid", "visits": ["2026-07-16"]},
        ],
        "days": [
            {"date": "2026-07-12", "plants": ["Basil"]},
            {"date": "2026-07-13", "plants": ["Fern"]},
            {"date": "2026-07-15", "plants": ["Basil"]},
            {"date": "2026-07-16", "plants": ["Orchid"]},
            {"date": "2026-07-17", "plants": ["Fern"]},
            {"date": "2026-07-18", "plants": ["Basil", "Monstera"]},
        ],
    }


def test_max_dry_from_settings(tmp_path):
    settings = make_inputs(tmp_path, "max_dry_days = 5")
    out = tmp_path / "trip.json"
    result = run("2026-07-10", "2026-07-20", str(out), "--settings", settings)
    assert result.returncode == 0, result.stderr
    assert read_json(out) == {
        "plants": [
            {"name": "Fern", "visits": ["2026-07-16"]},
            {"name": "Cactus", "visits": []},
            {"name": "Basil", "visits": ["2026-07-15"]},
            {"name": "Monstera", "visits": []},
            {"name": "Orchid", "visits": ["2026-07-19"]},
        ],
        "days": [
            {"date": "2026-07-15", "plants": ["Basil"]},
            {"date": "2026-07-16", "plants": ["Fern"]},
            {"date": "2026-07-19", "plants": ["Orchid"]},
        ],
    }


def test_max_dry_flag_wins_over_setting(tmp_path):
    settings = make_inputs(tmp_path, "max_dry_days = 5")
    out = tmp_path / "trip.json"
    result = run("2026-07-10", "2026-07-20", str(out), "--settings", settings, "--max-dry", "0")
    assert result.returncode == 0, result.stderr
    plan = read_json(out)
    assert plan["plants"] == [
        {"name": "Fern", "visits": ["2026-07-11", "2026-07-13", "2026-07-15", "2026-07-17",
                                    "2026-07-19"]},
        {"name": "Cactus", "visits": []},
        {"name": "Basil", "visits": ["2026-07-%02d" % day for day in range(10, 20)]},
        {"name": "Monstera", "visits": ["2026-07-16"]},
        {"name": "Orchid", "visits": ["2026-07-14", "2026-07-19"]},
    ]
    assert len(plan["days"]) == 10


def test_back_must_be_after_leave(tmp_path):
    settings = make_inputs(tmp_path)
    out = tmp_path / "trip.json"
    for back in ("2026-07-10", "2026-07-02"):
        result = run("2026-07-10", back, str(out), "--settings", settings)
        assert result.returncode == 2
        assert not out.exists()


def test_negative_max_dry(tmp_path):
    out = tmp_path / "trip.json"
    settings = make_inputs(tmp_path)
    result = run("2026-07-10", "2026-07-20", str(out), "--settings", settings, "--max-dry=-1")
    assert result.returncode == 2
    assert not out.exists()
    settings = make_inputs(tmp_path, "max_dry_days = -1")
    result = run("2026-07-10", "2026-07-20", str(out), "--settings", settings)
    assert result.returncode == 2
    assert not out.exists()
