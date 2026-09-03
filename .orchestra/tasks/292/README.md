# #292 — frozen change-capsule pilot

This directory contains the preregistered, read-only pilot requested by #292.
The intervention is a derived capsule only; Orchestra runtime, prompts, config,
DB rows, and production files are not changed.

Execution order:

1. verify `protocol.json`, capsules, answer key, runner, scorer, and source
   snapshots;
2. run `python lock_protocol.py` before any model call;
3. run `python run_pilot.py` sequentially (27 agent runs);
4. run `python score_blind.py` twice with independent scorer homes;
5. run `python analyze.py` and write the final evidence/report.

The lock is immutable. Any mismatch stops the pilot.
