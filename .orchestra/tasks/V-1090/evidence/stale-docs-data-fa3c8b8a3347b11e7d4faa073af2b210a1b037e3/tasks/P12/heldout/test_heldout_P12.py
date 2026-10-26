import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REGISTRY = "# id,name,rate,pension\nE01,Ana Silva,18.50,0.05\nE07,Ben Okafor,22.00,0.00\n"

CLAIMS = "\n".join([
    "E01,travel,125.40",
    "E07,travel,620.00",
    "E01,meals,75.50",
    "# second week",
    "",
    "E07,equipment,1099.99",
    "E99,meals,10.00",
    "E01,taxi,20.00",
    "E01,meals,12.345",
    "E07,meals",
    "E01,meals,0",
    "E07,meals,8.5",
    "E01,meals,abc",
]) + "\n"


def run(*args):
    return subprocess.run([sys.executable, "-m", "payrun.expenses", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(folder, name, text):
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_expense_report(tmp_path):
    registry = write(tmp_path, "staff.txt", REGISTRY)
    claims = write(tmp_path, "claims.txt", CLAIMS)
    out = os.path.join(str(tmp_path), "expenses.json")
    r = run(registry, claims, out)
    assert r.returncode == 0, r.stderr
    report = read_json(out)
    assert sorted(report) == ["paid", "rejected", "total"]
    assert report["paid"] == {"E01": "185.40", "E07": "1608.49"}
    assert report["total"] == "1793.89"
    assert [item["line"] for item in report["rejected"]] == [7, 8, 9, 10, 11, 13]
    for item in report["rejected"]:
        assert sorted(item) == ["line", "reason"]
        assert isinstance(item["reason"], str) and item["reason"].strip()


def test_all_claims_rejected(tmp_path):
    registry = write(tmp_path, "staff.txt", REGISTRY)
    claims = write(tmp_path, "claims.txt", "E02,meals,10.00\n\nE01,meals,-5.00\n")
    out = os.path.join(str(tmp_path), "expenses.json")
    r = run(registry, claims, out)
    assert r.returncode == 0, r.stderr
    report = read_json(out)
    assert report["paid"] == {}
    assert report["total"] == "0.00"
    assert [item["line"] for item in report["rejected"]] == [1, 3]


def test_caps_are_per_claim(tmp_path):
    registry = write(tmp_path, "staff.txt", REGISTRY)
    claims = write(tmp_path, "claims.txt", "E07,meals,60.01\nE07,meals,59.99\nE07,travel,500\n")
    out = os.path.join(str(tmp_path), "expenses.json")
    r = run(registry, claims, out)
    assert r.returncode == 0, r.stderr
    assert read_json(out) == {"paid": {"E07": "619.99"}, "total": "619.99", "rejected": []}


def test_missing_claims_file(tmp_path):
    registry = write(tmp_path, "staff.txt", REGISTRY)
    out = os.path.join(str(tmp_path), "expenses.json")
    r = run(registry, os.path.join(str(tmp_path), "nope.txt"), out)
    assert r.returncode == 2
    assert not os.path.exists(out)


def test_invalid_registry(tmp_path):
    registry = write(tmp_path, "staff.txt", REGISTRY + "E09,Cleo Park,abc,0.05\n")
    claims = write(tmp_path, "claims.txt", "E01,travel,10.00\n")
    out = os.path.join(str(tmp_path), "expenses.json")
    r = run(registry, claims, out)
    assert r.returncode == 2
    assert not os.path.exists(out)
