import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = "flagstore.audit"

FLAGS = [
    {"name": "beta-banner", "state": "on"},
    {"name": "dark-mode", "state": "off"},
    {"name": "checkout-v2", "state": "rollout", "rollout_percent": 20},
    {"name": "search-box", "state": "on"},
]
EVALUATIONS = {
    "beta-banner": "2024-05-30T12:00:00+00:00",
    "dark-mode": "2024-04-01T09:15:00+00:00",
    "search-box": "2024-05-02T12:00:00+00:00",
    "gone-flag": "2024-05-31T00:00:00+00:00",
}
NOW = "2024-06-01T12:00:00+00:00"


def run(tmp_path, settings=None, now=NOW, evaluations=None):
    (tmp_path / "flags.json").write_text(json.dumps(FLAGS), encoding="utf-8")
    (tmp_path / "evals.json").write_text(
        json.dumps(EVALUATIONS if evaluations is None else evaluations), encoding="utf-8"
    )
    out = tmp_path / "audit.json"
    cmd = [sys.executable, "-m", ENTRY, str(tmp_path / "flags.json"), str(tmp_path / "evals.json"),
           str(out)]
    if settings is not None:
        (tmp_path / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        cmd += ["--settings", str(tmp_path / "settings.json")]
    if now is not None:
        cmd += ["--now", now]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
    return proc, out


def load(out):
    with open(out, encoding="utf-8") as handle:
        return json.load(handle)


def test_default_threshold(tmp_path):
    proc, out = run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert load(out) == {
        "now": "2024-06-01T12:00:00+00:00",
        "stale_after_days": 30,
        "flags": [
            {"name": "beta-banner", "group": "active",
             "last_evaluated": "2024-05-30T12:00:00+00:00"},
            {"name": "checkout-v2", "group": "unused", "last_evaluated": None},
            {"name": "dark-mode", "group": "stale",
             "last_evaluated": "2024-04-01T09:15:00+00:00"},
            {"name": "search-box", "group": "active",
             "last_evaluated": "2024-05-02T12:00:00+00:00"},
        ],
    }


def test_threshold_from_settings_file(tmp_path):
    proc, out = run(tmp_path, settings={"stale_after_days": 7})
    assert proc.returncode == 0, proc.stderr
    data = load(out)
    assert data["stale_after_days"] == 7
    groups = {item["name"]: item["group"] for item in data["flags"]}
    assert groups == {
        "beta-banner": "active",
        "checkout-v2": "unused",
        "dark-mode": "stale",
        "search-box": "stale",
    }


def test_times_are_written_in_utc(tmp_path):
    proc, out = run(
        tmp_path,
        now="2024-06-01T14:00:00+02:00",
        evaluations={"dark-mode": "2024-05-31T23:30:00-04:00"},
    )
    assert proc.returncode == 0, proc.stderr
    data = load(out)
    assert data["now"] == "2024-06-01T12:00:00+00:00"
    assert data["flags"][2] == {
        "name": "dark-mode",
        "group": "active",
        "last_evaluated": "2024-06-01T03:30:00+00:00",
    }


def test_reference_time_may_be_left_out(tmp_path):
    proc, out = run(tmp_path, now=None)
    assert proc.returncode == 0, proc.stderr
    data = load(out)
    now = datetime.fromisoformat(data["now"])
    assert now.utcoffset().total_seconds() == 0
    assert now.year >= 2025
    assert [item["group"] for item in data["flags"]] == ["stale", "unused", "stale", "stale"]


def test_bad_threshold_fails(tmp_path):
    for value in (0, "ten"):
        proc, out = run(tmp_path, settings={"stale_after_days": value})
        assert proc.returncode == 2
        assert not out.exists()
