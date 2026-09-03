# #313 raw evidence

The parent `evidence/` directory contains captured collection logs, targeted pytest output, static-analysis JSON, and runtime-only mutant output. Files are generated from the frozen `main` SHA recorded in `inventory.json`; no provider/live-probe body was run. Fixture-like secret forms copied by AST output were redacted, and `../secret-scan.txt` records the scan result.
