from src.ledger import Ledger, charge_invoice


def test_retry_creates_exactly_one_contract_debit():
    ledger = Ledger()
    charge_invoice(ledger, "inv-7", 1250)
    charge_invoice(ledger, "inv-7", 1250)

    debits = [
        entry for entry in ledger.entries
        if entry.get("kind") == "debit" and entry.get("invoice_id") == "inv-7"
    ]
    assert len(debits) == 1
    assert debits[0]["amount_cents"] == 1250

