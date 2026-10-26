import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BILL = "item,amount\npizza,12.50\npasta,14.00\nwine,28.00\n"
SHARES = "name,weight\nann,2\nben,1\ncat,1\ndan,3\n"


def write(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "tipjar.shares", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_weighted_shares_with_tip(tmp_path):
    folder = str(tmp_path)
    bill = write(folder, "bill.csv", BILL)
    shares = write(folder, "shares.csv", SHARES)
    output = os.path.join(folder, "out.json")
    result = run(bill, shares, output, "--tip", "15")
    assert result.returncode == 0, result.stderr
    data = read_json(output)
    assert data["subtotal"] == "54.50"
    assert data["tip"] == "8.18"
    assert data["total"] == "62.68"
    assert data["shares"] == [
        {"name": "ann", "weight": 2, "amount": "17.91"},
        {"name": "ben", "weight": 1, "amount": "8.96"},
        {"name": "cat", "weight": 1, "amount": "8.95"},
        {"name": "dan", "weight": 3, "amount": "26.86"},
    ]


def test_without_tip_the_tip_is_null(tmp_path):
    folder = str(tmp_path)
    bill = write(folder, "bill.csv", BILL)
    shares = write(folder, "shares.csv", SHARES)
    output = os.path.join(folder, "out.json")
    result = run(bill, shares, output)
    assert result.returncode == 0, result.stderr
    data = read_json(output)
    assert data["tip"] is None
    assert data["total"] == "54.50"
    assert [share["amount"] for share in data["shares"]] == ["15.58", "7.79", "7.78", "23.35"]


def test_zero_tip_is_a_tip(tmp_path):
    folder = str(tmp_path)
    bill = write(folder, "bill.csv", BILL)
    shares = write(folder, "shares.csv", "name,weight\nann,1\nben,1\n")
    output = os.path.join(folder, "out.json")
    result = run(bill, shares, output, "--tip", "0%")
    assert result.returncode == 0, result.stderr
    data = read_json(output)
    assert data["tip"] == "0.00"
    assert data["total"] == "54.50"
    assert [share["amount"] for share in data["shares"]] == ["27.25", "27.25"]


def test_bad_weight_exits_2(tmp_path):
    folder = str(tmp_path)
    bill = write(folder, "bill.csv", BILL)
    shares = write(folder, "shares.csv", "name,weight\nann,2\nben,1.5\n")
    output = os.path.join(folder, "out.json")
    result = run(bill, shares, output)
    assert result.returncode == 2
    assert not os.path.exists(output)


def test_duplicate_name_exits_2(tmp_path):
    folder = str(tmp_path)
    bill = write(folder, "bill.csv", BILL)
    shares = write(folder, "shares.csv", "name,weight\nann,2\nben,1\nann,1\n")
    output = os.path.join(folder, "out.json")
    result = run(bill, shares, output, "--tip", "10")
    assert result.returncode == 2
    assert not os.path.exists(output)


def test_missing_bill_exits_2(tmp_path):
    folder = str(tmp_path)
    shares = write(folder, "shares.csv", SHARES)
    output = os.path.join(folder, "out.json")
    result = run(os.path.join(folder, "missing.csv"), shares, output)
    assert result.returncode == 2
    assert not os.path.exists(output)
