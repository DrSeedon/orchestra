import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEDGER = (
    "date,category,kind,amount,note\n"
    "2024-03-02,groceries,expense,120.50,\n"
    "2024-03-05,rent,expense,900.00,March rent\n"
    "2024-03-09,fun,expense,60.10,cinema\n"
    "2024-03-12,groceries,expense,95.25,\n"
    "2024-03-15,groceries,refund,10.00,returned item\n"
    "2024-03-20,fun,expense,45.00,\n"
    "2024-03-25,salary,income,2500.00,\n"
    "2024-02-28,groceries,expense,300.00,\n"
    "2024-03-28,travel,expense,80.00,\n"
)

BUDGETS = "category,limit\ngroceries,250.00\nrent,900.00\nfun,100.00\nbooks,30.00\n"


def run(*args):
    return subprocess.run([sys.executable, "-m", "budgetbook.alerts", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_inputs(tmp_path):
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(LEDGER, encoding="utf-8")
    budgets = tmp_path / "budgets.csv"
    budgets.write_text(BUDGETS, encoding="utf-8")
    return str(ledger), str(budgets)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_alerts_with_near_threshold(tmp_path):
    ledger, budgets = make_inputs(tmp_path)
    out = tmp_path / "alerts.json"
    r = run(ledger, budgets, "2024-03", str(out), "--near", "80")
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "month": "2024-03",
        "near": 80,
        "categories": [
            {"category": "books", "budget": "30.00", "spent": "0.00", "remaining": "30.00", "level": "ok"},
            {"category": "fun", "budget": "100.00", "spent": "105.10", "remaining": "-5.10", "level": "over"},
            {"category": "groceries", "budget": "250.00", "spent": "205.75", "remaining": "44.25",
             "level": "near"},
            {"category": "rent", "budget": "900.00", "spent": "900.00", "remaining": "0.00", "level": "near"},
        ],
    }


def test_alerts_without_near_threshold(tmp_path):
    ledger, budgets = make_inputs(tmp_path)
    out = tmp_path / "alerts.json"
    r = run(ledger, budgets, "2024-03", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    data = read_json(out)
    assert data["month"] == "2024-03"
    assert data["near"] is None
    assert [(c["category"], c["spent"], c["level"]) for c in data["categories"]] == [
        ("books", "0.00", "ok"),
        ("fun", "105.10", "over"),
        ("groceries", "205.75", "ok"),
        ("rent", "900.00", "ok"),
    ]


def test_other_month(tmp_path):
    ledger, budgets = make_inputs(tmp_path)
    out = tmp_path / "alerts.json"
    r = run(ledger, budgets, "2024-02", str(out), "--near", "50")
    assert r.returncode == 0, r.stdout + r.stderr
    data = read_json(out)
    assert data["near"] == 50
    groceries = [c for c in data["categories"] if c["category"] == "groceries"][0]
    assert groceries == {"category": "groceries", "budget": "250.00", "spent": "300.00",
                         "remaining": "-50.00", "level": "over"}


def test_bad_percent_exits_2(tmp_path):
    ledger, budgets = make_inputs(tmp_path)
    out = tmp_path / "alerts.json"
    r = run(ledger, budgets, "2024-03", str(out), "--near", "150")
    assert r.returncode == 2
    assert not out.exists()


def test_bad_month_exits_2(tmp_path):
    ledger, budgets = make_inputs(tmp_path)
    out = tmp_path / "alerts.json"
    r = run(ledger, budgets, "2024-3", str(out))
    assert r.returncode == 2
    assert not out.exists()


def test_missing_budget_file_exits_2(tmp_path):
    ledger, _ = make_inputs(tmp_path)
    out = tmp_path / "alerts.json"
    r = run(ledger, str(tmp_path / "missing.csv"), "2024-03", str(out))
    assert r.returncode == 2
    assert not out.exists()
