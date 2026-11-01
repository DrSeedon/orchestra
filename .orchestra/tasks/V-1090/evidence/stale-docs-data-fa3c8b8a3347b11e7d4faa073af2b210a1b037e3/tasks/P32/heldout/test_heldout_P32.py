import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CRONTAB = (
    "# maintenance jobs\n"
    "MAILTO=ops@example.com\n"
    "* * * * * /usr/bin/heartbeat\n"
    "*/15 * * * * /usr/local/bin/sync --quiet\n"
    "\n"
    "30 2 * * * /opt/backup.sh\n"
    "0 */5 * * * /opt/rotate.sh\n"
    "0 9 * * mon /opt/weekly.sh\n"
    "0 9 * * 1-5 /opt/standup.sh\n"
    "0 0 1 * * /opt/bill.sh\n"
    "@yearly /opt/archive.sh\n"
    "0 12 1 jan,jul * /opt/half.sh\n"
)


def run(*args):
    return subprocess.run([sys.executable, "-m", "cronlint.classify", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_report_lists_every_entry_and_totals(tmp_path):
    crontab = str(tmp_path / "crontab")
    report = str(tmp_path / "report.txt")
    write(crontab, CRONTAB)
    r = run(crontab, report)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read(report) == (
        "line 3: minutely (every 1 min) /usr/bin/heartbeat\n"
        "line 4: hourly (every 15 min) /usr/local/bin/sync --quiet\n"
        "line 6: daily (every 1440 min) /opt/backup.sh\n"
        "line 7: daily (irregular) /opt/rotate.sh\n"
        "line 8: weekly (every 10080 min) /opt/weekly.sh\n"
        "line 9: weekly (irregular) /opt/standup.sh\n"
        "line 10: monthly (irregular) /opt/bill.sh\n"
        "line 11: yearly (irregular) /opt/archive.sh\n"
        "line 12: yearly (irregular) /opt/half.sh\n"
        "minutely=1 hourly=1 daily=2 weekly=2 monthly=1 yearly=2\n"
    )


def test_intervals_wrap_around_the_cycle(tmp_path):
    crontab = str(tmp_path / "jobs" / "crontab")
    report = str(tmp_path / "out" / "sub" / "report.txt")
    write(crontab, (
        "5,35 * * * * /opt/a.sh\n"
        "0 0,12 * * * /opt/b.sh\n"
        "0 0 * * 0,7 /opt/c.sh\n"
        "*/1 * * * * /opt/d.sh\n"
        "10 * * * * /opt/e.sh\n"
        "0 0 29 2 * /opt/leap.sh\n"
        "0 0 30 2 1 /opt/mon.sh\n"
    ))
    r = run(crontab, report)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read(report) == (
        "line 1: hourly (every 30 min) /opt/a.sh\n"
        "line 2: daily (every 720 min) /opt/b.sh\n"
        "line 3: weekly (every 10080 min) /opt/c.sh\n"
        "line 4: minutely (every 1 min) /opt/d.sh\n"
        "line 5: hourly (every 60 min) /opt/e.sh\n"
        "line 6: yearly (irregular) /opt/leap.sh\n"
        "line 7: yearly (irregular) /opt/mon.sh\n"
        "minutely=1 hourly=2 daily=1 weekly=1 monthly=0 yearly=2\n"
    )


def test_crontab_without_entries(tmp_path):
    crontab = str(tmp_path / "crontab")
    report = str(tmp_path / "report.txt")
    write(crontab, "# nothing scheduled\nSHELL=/bin/sh\n\n")
    r = run(crontab, report)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read(report) == "minutely=0 hourly=0 daily=0 weekly=0 monthly=0 yearly=0\n"


@pytest.mark.parametrize("entry", ["0 0 30 2 * /opt/never.sh", "15 4 31 4,6,9,11 * /opt/never.sh"])
def test_entry_that_never_runs_exits_2(tmp_path, entry):
    crontab = str(tmp_path / "crontab")
    report = str(tmp_path / "report.txt")
    write(crontab, "@daily /opt/a.sh\n" + entry + "\n0 * * * * /opt/b.sh\n")
    r = run(crontab, report)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(report)


@pytest.mark.parametrize("entry", ["61 * * * * /opt/x.sh", "0 0 * * funday /opt/x.sh", "@daily"])
def test_unparsable_entry_exits_2(tmp_path, entry):
    crontab = str(tmp_path / "crontab")
    report = str(tmp_path / "report.txt")
    write(crontab, "0 * * * * /opt/b.sh\n" + entry + "\n")
    r = run(crontab, report)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(report)


def test_missing_crontab_exits_2(tmp_path):
    report = str(tmp_path / "report.txt")
    r = run(str(tmp_path / "nope"), report)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not os.path.exists(report)
