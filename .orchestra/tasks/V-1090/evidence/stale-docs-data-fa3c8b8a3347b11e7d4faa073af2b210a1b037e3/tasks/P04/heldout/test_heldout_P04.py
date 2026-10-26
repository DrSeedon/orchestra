import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPORT = {
    "code": "MATH200",
    "assessments": [{"name": "exam", "weight": 1, "max": 100}],
    "students": [
        {"id": "s2", "name": "Alan Turing"},
        {"id": "s4", "name": "Edsger Dijkstra"},
        {"id": "s1", "name": "Ada Lovelace", "email": "ada@example.edu"},
        {"id": "s3", "name": "Grace Hopper"},
    ],
    "scores": [
        {"student": "s1", "assessment": "exam", "points": 95},
        {"student": "s2", "assessment": "exam", "points": 72.5},
        {"student": "s3", "assessment": "exam", "points": None},
        {"student": "s4", "assessment": "exam", "points": 60},
    ],
}


def run(*args):
    return subprocess.run([sys.executable, "-m", "gradebook.curve", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write_export(tmp_path, data):
    path = str(tmp_path / "course.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def student(sid, original, curved, letter):
    return {"id": sid, "original": original, "curved": curved, "letter": letter}


def test_default_curve_lifts_best_to_100(tmp_path):
    out = str(tmp_path / "curve.json")
    r = run(write_export(tmp_path, EXPORT), out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "course": "MATH200",
        "shift": 5,
        "students": [
            student("s1", 95, 100, "A"),
            student("s2", 72.5, 77.5, "C"),
            student("s3", None, None, None),
            student("s4", 60, 65, "D"),
        ],
    }


def test_target_mean(tmp_path):
    out = str(tmp_path / "curve.json")
    r = run(write_export(tmp_path, EXPORT), out, "--target", "80")
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "course": "MATH200",
        "shift": 4.17,
        "students": [
            student("s1", 95, 99.17, "A"),
            student("s2", 72.5, 76.67, "C"),
            student("s3", None, None, None),
            student("s4", 60, 64.17, "D"),
        ],
    }


def test_cap_and_negative_shift(tmp_path):
    export = write_export(tmp_path, EXPORT)
    out = str(tmp_path / "curve.json")
    r = run(export, out, "--target", "90")
    assert r.returncode == 0, r.stdout + r.stderr
    data = read_json(out)
    assert data["shift"] == 14.17
    assert [(s["curved"], s["letter"]) for s in data["students"]] == [
        (100, "A"), (86.67, "B"), (None, None), (74.17, "C")]
    out2 = str(tmp_path / "curve2.json")
    r = run(export, out2, "--target", "50")
    assert r.returncode == 0, r.stdout + r.stderr
    data = read_json(out2)
    assert data["shift"] == 0
    assert [s["curved"] for s in data["students"]] == [95, 72.5, None, 60]


def test_weighted_percentages(tmp_path):
    export = {
        "code": "CS101",
        "assessments": [{"name": "midterm", "weight": 0.4, "max": 50}, {"name": "final", "weight": 0.6, "max": 120}],
        "students": [{"id": "b", "name": "Bea"}, {"id": "a", "name": "Abe"}],
        "scores": [
            {"student": "a", "assessment": "midterm", "points": 40},
            {"student": "a", "assessment": "final", "points": 90},
            {"student": "b", "assessment": "midterm", "points": None},
            {"student": "b", "assessment": "final", "points": 102},
        ],
    }
    out = str(tmp_path / "curve.json")
    r = run(write_export(tmp_path, export), out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "course": "CS101",
        "shift": 15,
        "students": [student("a", 77, 92, "A"), student("b", 85, 100, "A")],
    }


def test_errors_exit_2_without_output(tmp_path):
    out = str(tmp_path / "curve.json")
    r = run(str(tmp_path / "missing.json"), out)
    assert r.returncode == 2
    assert not os.path.exists(out)
    excused = dict(EXPORT, scores=[{"student": "s1", "assessment": "exam", "points": None}])
    r = run(write_export(tmp_path, excused), out)
    assert r.returncode == 2
    assert not os.path.exists(out)
    r = run(write_export(tmp_path, EXPORT), out, "--target", "120")
    assert r.returncode == 2
    assert not os.path.exists(out)
