import json

from sensorhub.__main__ import main


def test_main_writes_summary(readings_file, write_file, tmp_path):
    settings = write_file("hub.ini", "[sensorhub]\nmin_readings = 2\ndecimals = 0\n")
    out = tmp_path / "summary.json"
    assert main([readings_file, str(out), "--settings", settings]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["max_gap"] == 30
    assert data["sensors"][1] == {"sensor": "cellar", "count": 2, "min": 11.0, "max": 12.0,
                                  "mean": 12.0, "gaps": 0, "last": "2026-10-01T08:30:00"}


def test_main_bad_settings(readings_file, write_file, tmp_path, capsys):
    settings = write_file("hub.ini", "[sensorhub]\nmax_gap = soon\n")
    out = tmp_path / "summary.json"
    assert main([readings_file, str(out), "--settings", settings]) == 2
    assert not out.exists()
    assert "whole number" in capsys.readouterr().err


def test_main_missing_readings(tmp_path):
    out = tmp_path / "summary.json"
    assert main([str(tmp_path / "none.csv"), str(out)]) == 2
    assert not out.exists()
