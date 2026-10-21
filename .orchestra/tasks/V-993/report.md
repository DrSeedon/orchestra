# V-993 — Luna deliveries not held at Codex 5h=100%

**Finding: no code defect on the live path; the V-983 fix was simply not loaded in the running process.**

Evidence:
- V-983 (6579ac81b) was merged 2026-10-20 10:23 CEST. The orchestra service's ActiveEnterTimestamp is 2026-10-21 11:29:57 CEST (09:29:57Z), i.e. the first restart after that merge came with V-991 (main checkout de503ac1d, 11:28:49 CEST). The failing cases (spawn ~08:3xZ, send ~09:2xZ) all precede it. Python in app/** only takes effect after a restart (V-983 report said so).
- Real snapshot from `usage_snapshots` (id at 2026-10-21T08:30:46Z, `provider_usage.codex`: 5h utilization 100, resets_at `2026-10-21T12:01:30Z` in `Z` format, 7d 45) fed to current `evaluate_worker_admission('gpt-6-luna', …)` → `blocked`, `at_reset`, release_in 12630 s. So bucket name, `Z` timestamp parsing, observation shape and window shape are all fine. Every delivery path (send preflight → `Session.preflight_delivery_admission`, initial delivery, quota_queue release) calls `get_worker_admission`, i.e. the same function; override_left was not involved.
- Not proven live: the DB has no `WAITING_QUOTA` delivery after the restart (no Luna delivery was sent in the 1 min window); first post-restart Luna send during the exhausted window is the live confirmation.

Added regression test `test_live_codex_snapshot_shape_holds_luna_until_the_five_hour_reset` (tests/test_quota_gate.py): the live-shaped snapshot through `get_worker_admission` with an observation loader → blocked with ETA = 12:01:30Z; with V-983's `_exhausted_window_reset` branch disabled, it and the V-983 test go red. `uv run --frozen python -m pytest tests/test_quota_gate.py -q` → 104 passed.

Restart: none needed for this change (test only); the fix is already live as of the 11:29:57 CEST restart.

## Correction (re-open): real cause = owner gate override

The "not loaded" diagnosis above is wrong (journalctl: V-983 live since 20.10 10:27 CEST; failures were under pids 1396285 / 2167276). Real cause: `POST /api/usage/quota-override` at 21.10 10:23:44 CEST (journal; "quota gate open: released 14 waiting deliveries"); `kv.quota_gate_override_until` = 1792592580 (~14:03Z) is still active. V-983's branch was written as `None if (override_left or …)`, so while the owner's override was active the exhausted-window check was skipped → Luna deliveries (spawn 10:28:06 CEST, send ~11:2x) went through into a dead pool (journal shows `codex_connect_stage … stage=quota_gate duration=0.000s`, i.e. admitted). My earlier test never exercised an active override, and the pure-function check on the 08:30Z snapshot ran with override=0.

Fix (`app/quota_gate.py`): the exhausted-window check no longer depends on `override_left`; override lifts the lane line/ceilings, not a provider-exhausted pool (same principle as the hard stop that override already keeps). Test `test_owner_gate_override_does_not_release_an_exhausted_codex_window` fails on the previous code and passes now; `tests/test_quota_gate.py`, `test_quota_wait_queue.py`, `test_mcp_quota_gate.py`, `test_quota_admission_e2e.py` → 144 passed. Restart REQUIRED (app/**). Until restart, the active override (until ~14:03Z) keeps hiding the exhaustion.
