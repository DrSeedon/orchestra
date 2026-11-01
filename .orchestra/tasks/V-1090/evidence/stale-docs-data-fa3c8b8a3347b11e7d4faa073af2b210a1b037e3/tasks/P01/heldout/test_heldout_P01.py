import csv
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEADER = "supplier,invoice_no,date,amount_cents,currency"


def run(*args):
    return subprocess.run([sys.executable, "-m", "invoice_tool.batch", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(folder, name, text):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read_csv_lines(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return [line.rstrip("\r\n") for line in fh if line.strip()]


def make_input(folder):
    write(folder, "globex-07.csv", "invoice_no,date,amount,currency\nG-9,01.03.2024,12.5,EUR\n")
    write(folder, "acme_2024-03.csv",
          "Invoice,Date,Total,CCY\nA-1,2024-03-01,10.00,EUR\nA-2,2024-03-02,5.25,usd\n")
    write(folder, "broken.csv", "invoice_no,date\nB-1,2024-03-01\n")
    write(folder, "notes.txt", "not an invoice\n")


def test_batch_writes_records_and_summary(tmp_path):
    src, out = str(tmp_path / "in"), str(tmp_path / "out")
    make_input(src)
    r = run(src, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_csv_lines(os.path.join(out, "invoices.csv")) == [
        HEADER,
        "acme,A-1,2024-03-01,1000,EUR",
        "acme,A-2,2024-03-02,525,USD",
        "globex,G-9,2024-03-01,1250,EUR",
    ]
    with open(os.path.join(out, "summary.json"), encoding="utf-8") as fh:
        summary = json.load(fh)
    assert summary["processed"] == ["acme_2024-03.csv", "globex-07.csv"]
    assert list(summary["skipped"]) == ["broken.csv"]
    assert isinstance(summary["skipped"]["broken.csv"], str) and summary["skipped"]["broken.csv"]


def test_batch_applies_aliases(tmp_path):
    src, out = str(tmp_path / "in"), str(tmp_path / "out")
    write(src, "acmeco_2024-01.csv", "invoice_no,date,amount,currency\nX-1,2024-01-05,3.00,CHF\n")
    write(src, "aliases.txt", "acmeco = acme\n")
    r = run(src, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_csv_lines(os.path.join(out, "invoices.csv")) == [HEADER, "acme,X-1,2024-01-05,300,CHF"]


def test_batch_missing_input_dir(tmp_path):
    out = str(tmp_path / "out")
    r = run(str(tmp_path / "nope"), out)
    assert r.returncode == 2
    assert not os.path.exists(os.path.join(out, "summary.json"))


def test_batch_no_csv_files(tmp_path):
    src, out = str(tmp_path / "in"), str(tmp_path / "out")
    write(src, "notes.txt", "nothing here\n")
    r = run(src, out)
    assert r.returncode == 2
    assert not os.path.exists(os.path.join(out, "summary.json"))
