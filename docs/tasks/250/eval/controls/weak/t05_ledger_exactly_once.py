from src.ledger import Ledger, charge_invoice


def test_charge_reports_success():
    assert charge_invoice(Ledger(), "inv-7", 1250)["ok"] is True

