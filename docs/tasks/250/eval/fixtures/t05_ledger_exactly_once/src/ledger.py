class Ledger:
    def __init__(self):
        self.entries: list[dict] = []


def charge_invoice(ledger: Ledger, invoice_id: str, amount_cents: int) -> dict:
    for entry in ledger.entries:
        if entry.get("kind") == "debit" and entry.get("invoice_id") == invoice_id:
            return {"ok": True, "duplicate": True}
    ledger.entries.append({
        "kind": "debit",
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
    })
    return {"ok": True, "duplicate": False}

