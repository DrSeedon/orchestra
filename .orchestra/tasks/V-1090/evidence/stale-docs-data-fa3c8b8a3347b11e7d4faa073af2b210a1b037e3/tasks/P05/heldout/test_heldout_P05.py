import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEADER = ["source", "count", "median", "p95", "max"]

FIRST = [
    "2024-05-01T10:00:00 INFO [api] GET /orders status=200 duration_ms=120",
    "2024-05-01T10:00:05 INFO [api] GET /orders status=200 duration_ms=80",
    "2024-05-01T10:00:10 WARNING [api] GET /report status=200 duration_ms=2400",
    "2024-05-01T10:00:15 INFO [api] health check ok",
    "not a log line",
    "2024-05-01T10:00:20 INFO [db] query done rows=4 duration_ms=15",
    "2024-05-01T10:00:25 ERROR [db] query failed duration_ms=n/a",
    "2024-05-01T10:00:30 INFO [api] GET /users status=200 duration_ms=95",
]

SECOND = [
    "2024-05-01T09:59:00 INFO [db] query done rows=1 duration_ms=22",
    "2024-05-01T10:00:40 INFO [db] query done rows=9 duration_ms=7",
    "2024-05-01T10:00:45 WARN [db] clock skew duration_ms=-3",
    "2024-05-01T10:00:50 INFO [db] query done rows=2 duration_ms=12.5",
    "2024-05-01T10:01:00 INFO [worker] job finished job=42 duration_ms=1500",
]


def run(*args):
    return subprocess.run([sys.executable, "-m", "logsift.latency", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write_lines(tmp_path, name, lines):
    path = str(tmp_path / name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def read_rows(path):
    with open(path, encoding="utf-8") as fh:
        return [line.split(",") for line in fh.read().splitlines() if line.strip()]


def test_rows_per_source(tmp_path):
    first = write_lines(tmp_path, "a.log", FIRST)
    second = write_lines(tmp_path, "b.log", SECOND)
    output = str(tmp_path / "latency.csv")
    result = run(output, first, second)
    assert result.returncode == 0, result.stderr
    assert read_rows(output) == [
        HEADER,
        ["api", "4", "95", "2400", "2400"],
        ["db", "3", "15", "22", "22"],
        ["worker", "1", "1500", "1500", "1500"],
    ]
    assert "10:00:25" in result.stdout + result.stderr


def test_nearest_rank_on_many_values(tmp_path):
    lines = [
        "2024-06-02T08:{:02d}:00 INFO [search] query served duration_ms={}".format(minute, value)
        for minute, value in enumerate([130, 250, 10, 240, 20, 120, 230, 30, 110, 220, 40, 100,
                                        210, 50, 90, 200, 60, 80, 190, 70, 180, 140, 170, 150, 160])
    ]
    source = write_lines(tmp_path, "search.log", lines)
    output = str(tmp_path / "out.csv")
    result = run(output, source)
    assert result.returncode == 0, result.stderr
    assert read_rows(output) == [HEADER, ["search", "25", "130", "240", "250"]]


def test_header_only_without_durations(tmp_path):
    source = write_lines(tmp_path, "plain.log", [
        "2024-05-01T10:00:00 INFO [api] started",
        "2024-05-01T10:00:01 ERROR [api] request failed duration_ms=slow",
    ])
    output = str(tmp_path / "none.csv")
    result = run(output, source)
    assert result.returncode == 0, result.stderr
    assert read_rows(output) == [HEADER]


def test_missing_file(tmp_path):
    source = write_lines(tmp_path, "a.log", FIRST)
    output = str(tmp_path / "latency.csv")
    result = run(output, source, str(tmp_path / "missing.log"))
    assert result.returncode == 2
    assert not os.path.exists(output)
