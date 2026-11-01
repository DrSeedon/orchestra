import logging

from stationlog.__main__ import main

HEADER = "station,time,temp_c,humidity,pressure_hpa\n"
ROWS = "A1,2026-05-01T10:00,15.0,70,1010\nA1,2026-05-01T16:00,21.0,50,1008\n"
SUMMARY = [
    "station,day,count,temp_min,temp_max,temp_mean,humidity_mean",
    "A1,2026-05-01,2,15.0,21.0,18.0,60.0",
]


def test_main_writes_summary_beside_input(tmp_path):
    source = tmp_path / "north.csv"
    source.write_text(HEADER + ROWS, encoding="utf-8")
    assert main([str(source)]) == 0
    assert (tmp_path / "north.daily.csv").read_text(encoding="utf-8").splitlines() == SUMMARY


def test_main_out_dir(tmp_path):
    source = tmp_path / "north.csv"
    source.write_text(HEADER + ROWS, encoding="utf-8")
    assert main([str(source), "--out-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "north.daily.csv").is_file()
    assert not (tmp_path / "north.daily.csv").exists()


def test_main_missing_input(tmp_path, caplog):
    with caplog.at_level(logging.ERROR):
        assert main([str(tmp_path / "none.csv")]) == 2
    assert "cannot load" in caplog.text
