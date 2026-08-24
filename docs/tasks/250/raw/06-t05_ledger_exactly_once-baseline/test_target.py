from src.ledger import Ledger, charge_invoice


def test_retrying_invoice_charge_creates_one_debit_with_original_amount():
    ledger = Ledger()

    charge_invoice(ledger, "inv-1", 1250)
    charge_invoice(ledger, "inv-1", 1250)

    debits = [
        entry
        for entry in ledger.entries
        if entry.get("kind") == "debit" and entry.get("invoice_id") == "inv-1"
    ]

    assert len(debits) == 1
    assert debits[0]["amount_cents"] == 1250
