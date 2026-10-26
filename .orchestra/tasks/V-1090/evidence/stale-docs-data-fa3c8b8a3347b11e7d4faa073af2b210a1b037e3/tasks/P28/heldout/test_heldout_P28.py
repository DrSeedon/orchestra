import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

READINGS = (
    "time,sensor,value\n"
    "2026-10-01T08:30:00,boiler,40.0\n"
    "2026-10-01T08:00:00,boiler,61.0\n"
    "2026-10-01T08:05:00,boiler,75.5\n"
    "2026-10-01T08:10:00,boiler,72.0\n"
    "2026-10-01T08:20:00,boiler,71.0\n"
    "2026-10-01T08:00:00,cellar,9.5\n"
    "2026-10-01T08:10:00,cellar,30.0\n"
    "2026-10-01T09:00:00,cellar,8.0\n"
    "2026-10-01T08:15:00,attic,99.0\n"
    "noon,boiler,99.0\n"
)

LIMITS = (
    "sensor,low,high\n"
    "boiler,45,70\n"
    "cellar,10,\n"
    "garage,,35.5\n"
)


def run(*args):
    return subprocess.run([sys.executable, "-m", "sensorhub.alerts", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def make_input(tmp_path, limits=LIMITS):
    readings_path = str(tmp_path / "readings.csv")
    limits_path = str(tmp_path / "limits.csv")
    write(readings_path, READINGS)
    write(limits_path, limits)
    return readings_path, limits_path


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_alerts_with_default_cooldown(tmp_path):
    readings_path, limits_path = make_input(tmp_path)
    out = str(tmp_path / "alerts.json")
    r = run(readings_path, limits_path, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert load(out) == {
        "alerts": [
            {"time": "2026-10-01T08:00:00", "sensor": "cellar", "value": 9.5, "kind": "low"},
            {"time": "2026-10-01T08:05:00", "sensor": "boiler", "value": 75.5, "kind": "high"},
            {"time": "2026-10-01T08:20:00", "sensor": "boiler", "value": 71.0, "kind": "high"},
            {"time": "2026-10-01T09:00:00", "sensor": "cellar", "value": 8.0, "kind": "low"},
        ],
        "suppressed": {"boiler": 2, "cellar": 0, "garage": 0},
    }


def test_cooldown_from_settings(tmp_path):
    readings_path, limits_path = make_input(tmp_path)
    settings_path = str(tmp_path / "hub.ini")
    write(settings_path, "[sensorhub]\nmin_readings = 2\nalert_cooldown = 5\n")
    out = str(tmp_path / "alerts.json")
    r = run(readings_path, limits_path, out, "--settings", settings_path)
    assert r.returncode == 0, r.stdout + r.stderr
    data = load(out)
    assert [(a["time"][11:16], a["sensor"], a["kind"]) for a in data["alerts"]] == [
        ("08:00", "cellar", "low"),
        ("08:05", "boiler", "high"),
        ("08:10", "boiler", "high"),
        ("08:20", "boiler", "high"),
        ("08:30", "boiler", "low"),
        ("09:00", "cellar", "low"),
    ]
    assert data["suppressed"] == {"boiler": 0, "cellar": 0, "garage": 0}


def test_invalid_limits(tmp_path):
    for limits in ("sensor,low,high\nboiler,80,70\n",
                   "sensor,low,high\nboiler,cold,70\n",
                   "sensor,low,high\nboiler,,\n",
                   "sensor,low,high\nboiler,1,2\nboiler,3,4\n",
                   "sensor,low\nboiler,1\n"):
        readings_path, limits_path = make_input(tmp_path, limits)
        out = str(tmp_path / "alerts.json")
        r = run(readings_path, limits_path, out)
        assert r.returncode == 2, limits
        assert not os.path.exists(out)


def test_invalid_cooldown_setting(tmp_path):
    readings_path, limits_path = make_input(tmp_path)
    settings_path = str(tmp_path / "hub.ini")
    write(settings_path, "[sensorhub]\nalert_cooldown = soon\n")
    out = str(tmp_path / "alerts.json")
    r = run(readings_path, limits_path, out, "--settings", settings_path)
    assert r.returncode == 2
    assert not os.path.exists(out)


def test_missing_limits_file(tmp_path):
    readings_path, _ = make_input(tmp_path)
    out = str(tmp_path / "alerts.json")
    r = run(readings_path, str(tmp_path / "nope.csv"), out)
    assert r.returncode == 2
    assert not os.path.exists(out)
