# V-743: historical quota lines

## Implementation

Added append-only `quota_policy_history` storage in SQLite. Each event keeps `effective_from`, a canonical JSON snapshot, and its source. `quota_policy_snapshot()` serializes every field of `QuotaPolicy`, including lane sets and caps, so newly added line parameters travel in later snapshots. `quota_policy()` appends only when the snapshot differs from the last observed policy; startup appends the active policy if it differs from the stored tail. The quota-map response carries the most recent rule at/before the visible 84-hour past edge and every following event through the 84-hour future edge.

The timeline splits each weekly cycle at both reset boundaries and rule effective times. Past subsegments use their saved snapshots, while the current and future subsegments use the current rule. Gated lanes and hard stops are selected from each segment's rule, so historical Sol curve/cap and Claude shift changes do not leak backwards.

## Reconstruction and limits

The chart displays 84 hours behind and ahead, so it needs a baseline as of 2026-09-29, not a guessed exact start for older Sol rules. The initial snapshot records the owner-specified state at that boundary: hard stop 99%, Sol cap 95%, tolerance 10→1 p.p., exponent 2.5, gated lanes Claude/Sol, curved lane Sol, and Claude shift 0 hours.

Earlier rule-change bounds were reconstructed from commits and restart interruption markers in the read-only production `data/orchestra.db` `logs` table. Commit `b757e834` introduced Sol's curve at 2026-08-28 09:12:40 UTC; the first following `[system] рестарт: дренаж` marker found is log row 232326 at 2026-08-28 11:52:52.674 UTC. Commit `084a989e` introduced the 95% Sol cap at 2026-09-11 08:38:05 UTC; the first following marker found is row 371845 at 2026-09-16 06:31:08.449 UTC. The effective times are only bounded by each commit and its following marker: the marker is emitted only when a restart interrupts a turn, so a restart without an interrupted turn is not recorded. Both bounds end before the chart's 2026-09-29 baseline.

V-732's Claude shift uses the owner-reported restart time 2026-10-06 11:43 Krasnoyarsk (UTC+7), stored as 2026-10-06 04:43 UTC. A separate drain marker was not present for that restart. Since the Claude weekly reset was 07:00 UTC that day, the old cycle is genuinely split: it keeps the old line until 04:43 UTC, and uses the shifted line for its final 2 h 17 min. The following cycle uses the shifted rule throughout. This follows the restart timestamp; it cannot show the entire previous cycle as unshifted.

These historical marker checks covered the two bounded windows around commits `b757e834` and `084a989e`; each returned the exact row above. They do not establish that no unrecorded restart occurred between a commit and marker. No exact restart time is claimed for either older change.

## Verification

`uv run --frozen python -m pytest tests/test_quota_gate.py tests/test_quota_admission_e2e.py tests/test_quota_wait_queue.py tests/test_quota_map_api.py tests/test_quota_headroom_447.py tests/test_usage_readiness.py tests/test_mcp_quota_gate.py tests/test_codex_quota_103.py tests/test_turn_ended_no_quota_suffix.py -q` → 159 passed.

`uv run --frozen python -m pytest tests/test_t344_quota_lines_browser.py tests/test_audit0901_sysquota.py tests/test_model_gates.py -q` → 38 passed. The browser assertion checks an old Claude point before the V-732 effective time, the V-732 tail split, and a point in the current cycle. A mutation making every chart segment use today's policy failed that committed browser test.

Restart idempotency follow-up: `test_quota_policy_history_reconstruction_is_idempotent_after_process_restart` initializes twice after clearing the module caches and verifies there is one row per reconstructed epoch. A mutation removing `reconstructed:` from the source labels produced four rows instead of two and failed the test.

`git diff --check` passed. Imported `app.quota_gate` path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-ratelimit/app/quota_gate.py`; system Python lacks `python-dotenv`, so project checks used `uv run --frozen python -m pytest`. The browser tests rewrote `.orchestra/tasks/V-652/quota-timeline.png`; it was restored to its tracked content after testing.

The database table is created additively at startup; no `user_version` change is required. Python changes require a restart to load into the live process; no restart was performed.
