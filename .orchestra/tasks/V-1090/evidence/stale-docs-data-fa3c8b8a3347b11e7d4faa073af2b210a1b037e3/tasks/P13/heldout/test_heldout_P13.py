import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEADER = "metric,stat,start,value,threshold,message"

SAMPLES = "\n".join([
    "# collector export",
    "cpu 1700000100 50",
    "cpu 1700000160 70",
    "mem 1700000100 512",
    "cpu 1700000220 95",
    "cpu 1700000280 99",
    "",
    "cpu 1700000400 20",
    "cpu 1700000500 30",
    "mem 1700000200 2048",
    "mem 1700000450 1024",
    "cpu 1700000700 91",
    "cpu 1700000800 92",
    "cpu 1700000900 93",
    "disk 1700000100 99999",
]) + "\n"

RULES = "\n".join([
    "# alert rules",
    "cpu max 99",
    "cpu p95 90",
    "",
    "mem max 1500",
    "cpu mean 80",
    "net max 1",
]) + "\n"


def run(*args):
    return subprocess.run([sys.executable, "-m", "metricroll.alerts", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(folder, name, text):
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read_lines(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def test_alerts_default_width(tmp_path):
    samples = write(tmp_path, "samples.txt", SAMPLES)
    rules = write(tmp_path, "rules.txt", RULES)
    out = os.path.join(str(tmp_path), "alerts.csv")
    r = run(samples, rules, out)
    assert r.returncode == 0, r.stderr
    assert read_lines(out) == [
        HEADER,
        "cpu,p95,1700000100,98.40,90.00,cpu p95 98.40 > 90.00 in window starting 1700000100",
        "cpu,p95,1700000700,92.90,90.00,cpu p95 92.90 > 90.00 in window starting 1700000700",
        "cpu,mean,1700000700,92.00,80.00,cpu mean 92.00 > 80.00 in window starting 1700000700",
        "mem,max,1700000100,2048.00,1500.00,"
        "mem max 2048.00 > 1500.00 in window starting 1700000100",
    ]


def test_alerts_custom_width(tmp_path):
    samples = write(tmp_path, "samples.txt", SAMPLES)
    rules = write(tmp_path, "rules.txt", "cpu max 95\n")
    out = os.path.join(str(tmp_path), "alerts.csv")
    r = run(samples, rules, out, "--width", "600")
    assert r.returncode == 0, r.stderr
    assert read_lines(out) == [
        HEADER,
        "cpu,max,1699999800,99.00,95.00,cpu max 99.00 > 95.00 in window starting 1699999800",
    ]


def test_no_alert_fires(tmp_path):
    samples = write(tmp_path, "samples.txt", SAMPLES)
    rules = write(tmp_path, "rules.txt", "cpu min 95\nmem p50 5000\n")
    out = os.path.join(str(tmp_path), "alerts.csv")
    r = run(samples, rules, out)
    assert r.returncode == 0, r.stderr
    assert read_lines(out) == [HEADER]


def test_bad_rule_lines(tmp_path):
    samples = write(tmp_path, "samples.txt", SAMPLES)
    out = os.path.join(str(tmp_path), "alerts.csv")
    for text in ("cpu p99 90\n", "cpu p95\n", "cpu p95 high\n"):
        rules = write(tmp_path, "rules.txt", "mem max 1500\n" + text)
        r = run(samples, rules, out)
        assert r.returncode == 2, text
        assert not os.path.exists(out)


def test_missing_samples_file(tmp_path):
    rules = write(tmp_path, "rules.txt", RULES)
    out = os.path.join(str(tmp_path), "alerts.csv")
    r = run(os.path.join(str(tmp_path), "missing.txt"), rules, out)
    assert r.returncode == 2
    assert not os.path.exists(out)
