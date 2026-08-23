# T05 — distant domain: idempotent invoice debit

Retrying the same invoice charge must create exactly one debit for that invoice and preserve its amount. A future implementation may add non-debit audit entries to the ledger; those are valid and must not break the test.

Write the smallest regression test through `charge_invoice`. This is deliberately a case where exact cardinality is the business contract, but only after filtering to the contract event.

