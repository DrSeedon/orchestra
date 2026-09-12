# Offline runner check: repair total

Mode: **offline_synthetic**. Synthetic fixture prices are not provider charges.

| Arm | Oracle | Completion | Seconds | Cost USD | Accounting |
|---|---|---|---:|---:|---|
| correct-a | PASS | exited | 0.217 | 0.200000 | complete |
| correct-b | PASS | exited | 0.232 | 0.200000 | complete |
| wrong-control | FAIL | exited | 0.246 | 0.200000 | complete |

Closed receipts: 0.600000. Observed including partial receipts: 0.600000 (not a final total). Complete total: 0.600000.
Preparation: 0.181s; attributed cost: None; fraction of preparation + arms: ?.
Preparation attribution: not supplied; not assumed zero.

Result correctness, process completion and accounting completeness are separate. A deadline snapshot can pass its oracle while billing remains incomplete.
