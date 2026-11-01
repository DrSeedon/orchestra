import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEADER = "station,start,end,minutes"
COLUMNS = "station,time,temp_c,humidity,pressure_hpa"

NORTH = "\n".join([
    COLUMNS,
    "B2,2026-05-01T00:00,10.0,80,1010",
    "A1,2026-05-01T00:00,11.0,70,1011",
    "A1,2026-05-01T00:10,11.2,70,1011",
    "A1,2026-05-01T00:20,11.4,71,1011",
    "A1,2026-05-01T00:30,11.5,71,NA",
    "A1,2026-05-01T01:30,12.0,72,1010",
    "A1,2026-05-01T01:40,12.1,,1010",
    "A1,2026-05-01T01:50,12.3,73,1010",
    "A1,2026-05-01T02:00,12.4,73,1010",
    "B2,2026-05-01T01:00,10.5,79,1010",
    "B2,2026-05-01T02:00,10.9,78,1009",
    "B2,2026-05-01T05:00,9.8,85,1009",
    "B2,2026-05-01T06:00,9.5,86,1008",
    "B2,2026-05-01T10:00,14.0,60,1008",
    "C3,2026-05-01T03:00,8.0,90,1012",
    "C3,not-a-time,1,1,1",
    "E5,2026-05-01T00:00,7.0,88,1013",
    "E5,2026-05-01T00:10,7.1,88,1013",
    "E5,2026-05-01T00:30,7.3,87,1013",
    "E5,2026-05-01T01:10,7.6,87,1012",
    "E5,2026-05-01T01:20,7.7,86,1012",
    "E5,2026-05-01T02:06,8.1,85,1012",
    "E5,2026-05-01T02:16,8.2,85,1012",
]) + "\n"


def run(*args):
    return subprocess.run([sys.executable, "-m", "stationlog.gaps", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(folder, name, text):
    os.makedirs(str(folder), exist_ok=True)
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read_lines(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def test_gaps_with_median_limit(tmp_path):
    source = write(tmp_path / "exports", "north.csv", NORTH)
    r = run(source)
    assert r.returncode == 0, r.stderr
    assert read_lines(os.path.join(str(tmp_path), "exports", "north.gaps.csv")) == [
        HEADER,
        "A1,2026-05-01T00:30,2026-05-01T01:30,60",
        "B2,2026-05-01T06:00,2026-05-01T10:00,240",
        "E5,2026-05-01T01:20,2026-05-01T02:06,46",
    ]


def test_gaps_with_fixed_limit(tmp_path):
    source = write(tmp_path, "north.csv", NORTH)
    r = run(source, "--max-minutes", "45")
    assert r.returncode == 0, r.stderr
    assert read_lines(os.path.join(str(tmp_path), "north.gaps.csv")) == [
        HEADER,
        "A1,2026-05-01T00:30,2026-05-01T01:30,60",
        "B2,2026-05-01T00:00,2026-05-01T01:00,60",
        "B2,2026-05-01T01:00,2026-05-01T02:00,60",
        "B2,2026-05-01T02:00,2026-05-01T05:00,180",
        "B2,2026-05-01T05:00,2026-05-01T06:00,60",
        "B2,2026-05-01T06:00,2026-05-01T10:00,240",
        "E5,2026-05-01T01:20,2026-05-01T02:06,46",
    ]


def test_no_gaps_still_writes_header(tmp_path):
    rows = [line for line in NORTH.splitlines() if line.startswith(("station", "C3"))]
    rows += ["D4,2026-05-01T23:50,5.0,90,1000", "D4,2026-05-02T00:05,5.0,90,1000"]
    source = write(tmp_path, "quiet.csv", "\n".join(rows) + "\n")
    r = run(source)
    assert r.returncode == 0, r.stderr
    assert read_lines(os.path.join(str(tmp_path), "quiet.gaps.csv")) == [HEADER]


def test_bad_input_and_bad_limit(tmp_path):
    assert run(os.path.join(str(tmp_path), "missing.csv")).returncode == 2
    assert not os.path.exists(os.path.join(str(tmp_path), "missing.gaps.csv"))
    bad = write(tmp_path, "bad.csv", "station,time,temp_c\nA1,2026-05-01T00:00,1.0\n")
    assert run(bad).returncode == 2
    assert not os.path.exists(os.path.join(str(tmp_path), "bad.gaps.csv"))
    source = write(tmp_path, "north.csv", NORTH)
    for value in ("0", "-5"):
        assert run(source, "--max-minutes", value).returncode == 2, value
        assert not os.path.exists(os.path.join(str(tmp_path), "north.gaps.csv"))
