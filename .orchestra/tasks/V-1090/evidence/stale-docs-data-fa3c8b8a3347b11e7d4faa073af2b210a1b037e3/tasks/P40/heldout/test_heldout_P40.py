import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COUPONS = {"coupons": [
    {"code": "SAVE10", "kind": "percent", "value": "10"},
    {"code": "FIVE", "kind": "amount", "value": "5.00"},
    {"code": "BIG20", "kind": "percent", "value": "20", "minimum": "100.00"},
    {"code": "HALF", "kind": "percent", "value": "50"},
    {"code": "TWENTY", "kind": "amount", "value": "20.00", "minimum": "50.00"},
    {"code": "TWO", "kind": "amount", "value": "2.00"},
]}

CART = "sku,quantity,price\nTEA-01,2,12.50\nMUG-02,1,18.00\nBAG-03,3,9.90\n"


def run(*args):
    return subprocess.run([sys.executable, "-m", "couponkit.stack", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_inputs(tmp_path, cart=CART, **extra):
    coupons = tmp_path / "coupons.json"
    coupons.write_text(json.dumps(COUPONS), encoding="utf-8")
    settings = tmp_path / "shop.json"
    settings.write_text(json.dumps(dict({"coupons_file": str(coupons)}, **extra)), encoding="utf-8")
    cart_file = tmp_path / "cart.csv"
    cart_file.write_text(cart, encoding="utf-8")
    return str(cart_file), str(settings)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_stack_with_default_limit(tmp_path):
    cart, settings = make_inputs(tmp_path)
    out = tmp_path / "result.json"
    result = run(cart, str(out), "SAVE10", "FIVE", "BIG20", "SAVE10", "TWENTY", "HALF", "TWO",
                 "--settings", settings)
    assert result.returncode == 0, result.stderr
    assert read_json(out) == {
        "subtotal": "72.70",
        "discount": "36.35",
        "total": "36.35",
        "applied": [
            {"code": "SAVE10", "discount": "7.27"},
            {"code": "FIVE", "discount": "5.00"},
            {"code": "TWENTY", "discount": "20.00"},
            {"code": "HALF", "discount": "4.08"},
        ],
        "rejected": [
            {"code": "BIG20", "reason": "minimum"},
            {"code": "SAVE10", "reason": "repeated"},
            {"code": "TWO", "reason": "limit"},
        ],
    }


def test_limit_from_settings(tmp_path):
    cart, settings = make_inputs(tmp_path, max_discount_percent=20)
    out = tmp_path / "result.json"
    result = run(cart, str(out), "HALF", "FIVE", "BIG20", "--settings", settings)
    assert result.returncode == 0, result.stderr
    assert read_json(out) == {
        "subtotal": "72.70",
        "discount": "14.54",
        "total": "58.16",
        "applied": [{"code": "HALF", "discount": "14.54"}],
        "rejected": [{"code": "FIVE", "reason": "limit"}, {"code": "BIG20", "reason": "minimum"}],
    }


def test_zero_limit(tmp_path):
    cart, settings = make_inputs(tmp_path, max_discount_percent=0)
    out = tmp_path / "result.json"
    result = run(cart, str(out), "FIVE", "--settings", settings)
    assert result.returncode == 0, result.stderr
    assert read_json(out) == {
        "subtotal": "72.70",
        "discount": "0.00",
        "total": "72.70",
        "applied": [],
        "rejected": [{"code": "FIVE", "reason": "limit"}],
    }


def test_unknown_coupon(tmp_path):
    cart, settings = make_inputs(tmp_path)
    out = tmp_path / "result.json"
    result = run(cart, str(out), "SAVE10", "NOPE", "--settings", settings)
    assert result.returncode == 2
    assert not out.exists()


def test_bad_limit_setting(tmp_path):
    out = tmp_path / "result.json"
    for value in (150, -5):
        cart, settings = make_inputs(tmp_path, max_discount_percent=value)
        result = run(cart, str(out), "SAVE10", "--settings", settings)
        assert result.returncode == 2
        assert not out.exists()


def test_bad_cart(tmp_path):
    cart, settings = make_inputs(tmp_path, cart=CART.replace("9.90", "9.9O"))
    out = tmp_path / "result.json"
    result = run(cart, str(out), "SAVE10", "--settings", settings)
    assert result.returncode == 2
    assert not out.exists()
