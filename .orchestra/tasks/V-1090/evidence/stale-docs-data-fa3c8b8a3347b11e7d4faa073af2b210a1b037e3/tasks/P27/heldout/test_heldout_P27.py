import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TENANTS = (
    "unit,name,rent,since\n"
    "2A,Cora Diaz,1100.00,2025-01-01\n"
    "1A,Ana Ruiz,1250.50,2024-03-01\n"
    "2B,Dev Patel,900,2022-06-01\n"
    "1B,Ben Cole,980.00,2023-09-15\n"
)

LEDGER = (
    "date,unit,kind,amount\n"
    "2026-09-01,1A,charge,1250.50\n"
    "2026-09-03,1A,payment,1250.50\n"
    "2026-09-01,1B,charge,980.00\n"
    "2026-09-12,1B,payment,479.95\n"
    "2026-10-01,1A,charge,1250.50\n"
    "2026-10-01,1B,charge,980.00\n"
    "2026-10-01,2A,charge,1100.00\n"
    "2026-10-02,2A,payment,1100.00\n"
    "2026-10-05,2A,credit,50.00\n"
    "2026-10-20,1A,payment,1250.50\n"
    "2026-10-21,1B,payment,2000.00\n"
)


def run(*args):
    return subprocess.run([sys.executable, "-m", "rentroll.latefees", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def make_input(tmp_path, ledger=LEDGER):
    tenants_path = str(tmp_path / "tenants.csv")
    ledger_path = str(tmp_path / "ledger.csv")
    write(tenants_path, TENANTS)
    write(ledger_path, ledger)
    return tenants_path, ledger_path


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_fees_mid_october(tmp_path):
    tenants_path, ledger_path = make_input(tmp_path)
    out = str(tmp_path / "fees.json")
    r = run(tenants_path, ledger_path, "2026-10-15", out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert load(out) == {
        "date": "2026-10-15",
        "tenants": [
            {"unit": "2A", "tenant": "Cora Diaz", "balance": "-50.00", "status": "current", "fee": "0.00"},
            {"unit": "1A", "tenant": "Ana Ruiz", "balance": "1250.50", "status": "late", "fee": "62.53"},
            {"unit": "2B", "tenant": "Dev Patel", "balance": "0.00", "status": "current", "fee": "0.00"},
            {"unit": "1B", "tenant": "Ben Cole", "balance": "1480.05", "status": "delinquent",
             "fee": "148.01"},
        ],
        "total": "210.54",
    }


def test_fees_end_of_september(tmp_path):
    tenants_path, ledger_path = make_input(tmp_path)
    out = str(tmp_path / "fees.json")
    r = run(tenants_path, ledger_path, "2026-09-30", out)
    assert r.returncode == 0, r.stdout + r.stderr
    data = load(out)
    assert data["date"] == "2026-09-30"
    assert [(t["unit"], t["balance"], t["status"], t["fee"]) for t in data["tenants"]] == [
        ("2A", "0.00", "current", "0.00"),
        ("1A", "0.00", "current", "0.00"),
        ("2B", "0.00", "current", "0.00"),
        ("1B", "500.05", "late", "49.00"),
    ]
    assert data["total"] == "49.00"


def test_unit_without_tenant(tmp_path):
    tenants_path, ledger_path = make_input(tmp_path, LEDGER + "2026-10-01,3C,charge,700.00\n")
    out = str(tmp_path / "fees.json")
    r = run(tenants_path, ledger_path, "2026-10-15", out)
    assert r.returncode == 2
    assert not os.path.exists(out)


def test_bad_date(tmp_path):
    tenants_path, ledger_path = make_input(tmp_path)
    out = str(tmp_path / "fees.json")
    r = run(tenants_path, ledger_path, "2026-13-01", out)
    assert r.returncode == 2
    assert not os.path.exists(out)


def test_missing_ledger(tmp_path):
    tenants_path, _ = make_input(tmp_path)
    out = str(tmp_path / "fees.json")
    r = run(tenants_path, str(tmp_path / "nope.csv"), "2026-10-15", out)
    assert r.returncode == 2
    assert not os.path.exists(out)
