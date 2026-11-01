import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HABITS = """# week 18
2024-05-01 run
2024-05-01 read
2024-05-03 run
2024-05-02 run
2024-05-03 Read
2024-05-03 run

2024-05-06 run
2024-05-05 run
2024-05-06 read
2024-05-07 stretch
"""


def run(*args):
    return subprocess.run([sys.executable, "-m", "habitlog.streaks", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write_habits(tmp_path, text=HABITS, name="habits.log"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def streak(habit, current, longest, total, last):
    return {"habit": habit, "current": current, "longest": longest, "total": total, "last": last}


def test_default_as_of_is_latest_day(tmp_path):
    out = tmp_path / "streaks.json"
    r = run(write_habits(tmp_path), str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "as_of": "2024-05-07",
        "habits": [
            streak("read", 0, 1, 3, "2024-05-06"),
            streak("run", 0, 3, 5, "2024-05-06"),
            streak("stretch", 1, 1, 1, "2024-05-07"),
        ],
    }


def test_as_of_ignores_later_entries(tmp_path):
    habits = write_habits(tmp_path)
    out = tmp_path / "streaks.json"
    r = run(habits, str(out), "--as-of", "2024-05-06")
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "as_of": "2024-05-06",
        "habits": [
            streak("read", 1, 1, 3, "2024-05-06"),
            streak("run", 2, 3, 5, "2024-05-06"),
        ],
    }
    r = run(habits, str(out), "--as-of", "2024-05-03")
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out)["habits"] == [
        streak("read", 1, 1, 2, "2024-05-03"),
        streak("run", 3, 3, 3, "2024-05-03"),
    ]


def test_as_of_after_latest_day(tmp_path):
    out = tmp_path / "streaks.json"
    r = run(write_habits(tmp_path), str(out), "--as-of", "2024-05-20")
    assert r.returncode == 0, r.stdout + r.stderr
    result = read_json(out)
    assert result["as_of"] == "2024-05-20"
    assert [(h["habit"], h["current"], h["longest"]) for h in result["habits"]] == [
        ("read", 0, 1), ("run", 0, 3), ("stretch", 0, 1)]


def test_as_of_before_first_day_exits_2(tmp_path):
    out = tmp_path / "streaks.json"
    r = run(write_habits(tmp_path), str(out), "--as-of", "2024-04-30")
    assert r.returncode == 2
    assert not out.exists()


def test_invalid_input_exits_2(tmp_path):
    out = tmp_path / "streaks.json"
    habits = write_habits(tmp_path)
    assert run(habits, str(out), "--as-of", "2024-02-30").returncode == 2
    bad = write_habits(tmp_path, HABITS + "2024-13-01 run\n", "bad.log")
    assert run(bad, str(out)).returncode == 2
    empty = write_habits(tmp_path, "# nothing yet\n\n", "empty.log")
    assert run(empty, str(out)).returncode == 2
    assert run(str(tmp_path / "missing.log"), str(out)).returncode == 2
    assert not out.exists()
