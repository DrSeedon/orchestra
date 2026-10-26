import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = "meter,from,to,kwh,energy,standing,total"


def run(*args):
    return subprocess.run([sys.executable, "-m", "meterread.bill", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return str(path)


def read_lines(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return [line.rstrip("\r\n") for line in fh if line.strip()]


def test_default_tiers_and_standing_charge(tmp_path):
    readings = write(tmp_path / "readings.csv", "meter,date,kwh\n"
                     "M2,2026-03-15,140\nM1,2026-03-31,1350\nM2,2026-03-05,40\n"
                     "M1,2026-03-01,1000\nM3,2026-03-01,500\nM3,2026-03-02,500\n")
    out = str(tmp_path / "bills.csv")
    r = run(readings, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_lines(out) == [
        HEADER,
        "M2,2026-03-05,2026-03-15,100,24.00,4.50,28.50",
        "M1,2026-03-01,2026-03-31,350,94.50,13.50,108.00",
        "M3,2026-03-01,2026-03-02,0,0.00,0.45,0.45",
    ]


def test_tiers_from_settings_file(tmp_path):
    readings = write(tmp_path / "readings.csv", "meter,date,kwh\n"
                     "M1,2026-03-01,1000\nM1,2026-03-31,1350\nM4,2026-02-27,0\nM4,2026-03-01,100\n"
                     "M5,2026-03-01,500\nM5,2026-03-04,800\nM5,2026-03-08,1000\n")
    conf = write(tmp_path / "meterread.conf", "# March prices\ncurrency = EUR\n"
                 "tiers = 100:0.20, 300:0.25, 0.32\nstanding_charge = 0.40\nunit_price = 0.99\n")
    out = str(tmp_path / "nested" / "dir" / "bills.csv")
    r = run(readings, out, "--settings", conf)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_lines(out) == [
        HEADER,
        "M1,2026-03-01,2026-03-31,350,86.00,12.00,98.00",
        "M4,2026-02-27,2026-03-01,100,20.00,0.80,20.80",
        "M5,2026-03-01,2026-03-08,500,134.00,2.80,136.80",
    ]
    flat = write(tmp_path / "flat.conf", "tiers = 0.30\nstanding_charge = 0\n")
    out = str(tmp_path / "flat.csv")
    r = run(readings, out, "--settings", flat)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_lines(out)[1] == "M1,2026-03-01,2026-03-31,350,105.00,0.00,105.00"


def test_meter_with_one_reading_exits_2(tmp_path):
    readings = write(tmp_path / "readings.csv", "meter,date,kwh\n"
                     "M1,2026-03-01,1000\nM1,2026-03-31,1350\nM2,2026-03-05,40\n")
    out = str(tmp_path / "bills.csv")
    r = run(readings, out)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(out)


@pytest.mark.parametrize("tiers", [
    "300:0.25, 100:0.20, 0.32",
    "100:0.20",
    "0.20, 0.30",
    "0:0.20, 0.30",
    "100:cheap, 0.30",
    "100:0.20, , 0.30",
])
def test_bad_tiers_exit_2(tmp_path, tiers):
    readings = write(tmp_path / "readings.csv", "meter,date,kwh\nM1,2026-03-01,1000\nM1,2026-03-31,1350\n")
    conf = write(tmp_path / "meterread.conf", "tiers = %s\n" % tiers)
    out = str(tmp_path / "bills.csv")
    r = run(readings, out, "--settings", conf)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(out)


def test_bad_readings_exit_2(tmp_path):
    readings = write(tmp_path / "readings.csv", "meter,date,kwh\nM1,2026-03-01,1000\nM1,2026-03-31,990\n")
    out = str(tmp_path / "bills.csv")
    r = run(readings, out)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(out)
    r = run(str(tmp_path / "missing.csv"), out)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(out)
