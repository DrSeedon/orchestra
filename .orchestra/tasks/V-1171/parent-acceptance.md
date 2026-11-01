# V-1171 host acceptance

Accepted the test-only registry-isolation change at author source `c9f75426fc84cbdc16c6433db1ffe8763019355d`; canonical merge `b8819733ab09ff9e8a6f156e9fdae2eb84593d04`. Root read the full author report, complete test diff and synthetic reproduction helpers. Product code, timeouts, restart authorization and durable persistence were unchanged. The original CI producer of stale manager state remains unidentified.

Host baseline for the committed new regression passed. Two independent process-local mutations, restoring the old session-selection seam and bypassing the real durable barrier, each made that same regression fail with the intended TimeoutError. No repository source bytes were changed by these controls. The exact selected neighboring set passed 80 tests and four subtests in 8.01 seconds, with no failures/skips; the instruction contract passed. Four relevant source hashes matched before/after, and the author worktree remained clean. Full repository tests were not repeated locally; actual new CI remains the publication check.

The first SSH launcher attempt failed before any pytest because uv was absent from the SSH PATH. The corrected attempt used the absolute installed uv executable with the existing locked environment and passed. This is recorded as a launcher failure, not a test failure.

Seven ignored author evidence files (82639 bytes) were copied to canonical private storage and independently hash-verified. Host logs, actual import/source identity and mutation results remain under `.orchestra/private/V-1171/`. Public test/report/helper secret-form scans and diff checks passed. Model review remains frozen.

Publication and actual CI are pending. This test-only merge needs no service restart and activates no Terra model, eval grant or harness implementation.
