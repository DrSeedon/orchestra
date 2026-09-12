# Offline deadline accounting controls

Mode: **offline_synthetic**. Synthetic fixture prices are not provider charges.

| Arm | Oracle | Completion | Seconds | Cost USD | Accounting |
|---|---|---|---:|---:|---|
| graceful | PASS | deadline | 0.515 | 0.200000 | complete |
| hard-kill | PASS | deadline | 0.909 | ? | partial |

Closed receipts: 0.200000. Observed including partial receipts: 0.300000 (not a final total). Complete total: ?.
Preparation: 0.154s; attributed cost: None; fraction of preparation + arms: ?.
Preparation attribution: not supplied; not assumed zero.

Result correctness, process completion and accounting completeness are separate. A deadline snapshot can pass its oracle while billing remains incomplete.
