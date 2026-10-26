import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = "cartkit.promo"

CATALOG = (
    "sku,name,price,weight_grams\n"
    "MUG-01,Coffee mug,12.50,400\n"
    "TEA-02,Green tea,4.99,120\n"
    "KET-03,Kettle,39.00,1300\n"
)
CODES = (
    "code,kind,value,min_spend\n"
    "SPRING15,percent,15,\n"
    "TENOFF,fixed,10.00,25.00\n"
    "BIG,fixed,500.00,\n"
    "ONE,percent,1,\n"
)


def run(tmp_path, order_rows, code):
    (tmp_path / "catalog.csv").write_text(CATALOG, encoding="ascii")
    (tmp_path / "codes.csv").write_text(CODES, encoding="ascii")
    (tmp_path / "order.csv").write_text("sku,quantity\n" + order_rows, encoding="ascii")
    out = tmp_path / "result.json"
    proc = subprocess.run(
        [sys.executable, "-m", ENTRY, str(tmp_path / "catalog.csv"), str(tmp_path / "order.csv"),
         str(tmp_path / "codes.csv"), code, str(out)],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    return proc, out


def load(out):
    with open(out, encoding="utf-8") as handle:
        return json.load(handle)


def test_percent_code(tmp_path):
    proc, out = run(tmp_path, "MUG-01,1\nTEA-02,1\nMUG-01,1\n", "SPRING15")
    assert proc.returncode == 0, proc.stderr
    assert load(out) == {
        "code": "SPRING15",
        "subtotal": "29.99",
        "discount": "4.50",
        "total": "25.49",
        "line": "Promo SPRING15: -$4.50",
    }


def test_fixed_code_matches_any_case(tmp_path):
    proc, out = run(tmp_path, "MUG-01,2\nTEA-02,1\n", "tenoff")
    assert proc.returncode == 0, proc.stderr
    assert load(out) == {
        "code": "TENOFF",
        "subtotal": "29.99",
        "discount": "10.00",
        "total": "19.99",
        "line": "Promo TENOFF: -$10.00",
    }


def test_discount_never_exceeds_subtotal(tmp_path):
    proc, out = run(tmp_path, "TEA-02,1\n", "BIG")
    assert proc.returncode == 0, proc.stderr
    assert load(out) == {
        "code": "BIG",
        "subtotal": "4.99",
        "discount": "4.99",
        "total": "0.00",
        "line": "Promo BIG: -$4.99",
    }


def test_percent_rounds_half_up(tmp_path):
    proc, out = run(tmp_path, "MUG-01,1\n", "One")
    assert proc.returncode == 0, proc.stderr
    data = load(out)
    assert data["discount"] == "0.13"
    assert data["total"] == "12.37"
    assert data["line"] == "Promo ONE: -$0.13"


def test_unknown_code_fails(tmp_path):
    proc, out = run(tmp_path, "MUG-01,1\n", "NOPE")
    assert proc.returncode == 2
    assert not out.exists()


def test_below_minimum_spend_fails(tmp_path):
    proc, out = run(tmp_path, "MUG-01,1\nTEA-02,1\n", "TENOFF")
    assert proc.returncode == 2
    assert not out.exists()
