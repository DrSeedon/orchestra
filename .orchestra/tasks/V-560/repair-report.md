# Offline runner check: repair total

Mode: **offline_synthetic**. Synthetic fixture prices are not provider charges.

| Arm | Oracle | Completion | Seconds | Cost USD | Accounting |
|---|---|---|---:|---:|---|
| correct-a | PASS | exited | 0.221 | 0.200000 | complete |
| correct-b | PASS | exited | 0.252 | 0.200000 | complete |
| wrong-control | FAIL | exited | 0.234 | 0.200000 | complete |

Closed receipts: 0.600000. Observed including partial receipts: 0.600000 (not a final total). Complete total: 0.600000.
Preparation: 0.168s; attributed cost: 0; fraction of preparation + arms: 0.00%.
Preparation attribution: Synthetic local demonstration; no model calls or billed preparation..

Result correctness, process completion and accounting completeness are separate. A deadline snapshot can pass its oracle while billing remains incomplete.
