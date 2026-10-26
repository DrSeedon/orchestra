import json

from couponkit.cli import main


def make_inputs(tmp_path):
    coupons = tmp_path / "coupons.json"
    coupons.write_text(json.dumps({"coupons": [
        {"code": "SAVE10", "kind": "percent", "value": "10"},
        {"code": "BIG", "kind": "amount", "value": "20", "minimum": "100"},
    ]}), encoding="utf-8")
    settings = tmp_path / "shop.json"
    settings.write_text(json.dumps({"coupons_file": str(coupons)}), encoding="utf-8")
    cart = tmp_path / "cart.csv"
    cart.write_text("sku,quantity,price\nTEA-01,2,12.50\nMUG-02,1,18.00\n", encoding="utf-8")
    return str(settings), str(cart)


def test_total_without_coupon(tmp_path, capsys):
    settings, cart = make_inputs(tmp_path)
    assert main(["--settings", settings, cart]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "subtotal 43.00 EUR", "discount 0.00 EUR", "total 43.00 EUR",
    ]


def test_total_with_coupon(tmp_path, capsys):
    settings, cart = make_inputs(tmp_path)
    assert main(["--settings", settings, cart, "--coupon", "save10"]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == ["discount 4.30 EUR", "total 38.70 EUR"]


def test_coupon_below_minimum_gives_nothing(tmp_path, capsys):
    settings, cart = make_inputs(tmp_path)
    assert main(["--settings", settings, cart, "--coupon", "BIG"]) == 0
    assert "discount 0.00 EUR" in capsys.readouterr().out


def test_unknown_coupon(tmp_path, capsys):
    settings, cart = make_inputs(tmp_path)
    assert main(["--settings", settings, cart, "--coupon", "NOPE"]) == 2
    assert "unknown coupon: NOPE" in capsys.readouterr().err
