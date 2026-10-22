# V-1020: restart drain spin

Cause (reproduced): `_drain_handoff_log_writes` looped `while self._log_futures: await gather(*tuple(set))`. If the set holds a
finished future (or producers keep adding), each gather returns after one loop turn, the set is still non-empty, and the loop
never gets to run timers: `/tmp/spin.py` on plain asyncio hung even under `asyncio.wait_for(..., 2)` inside an outer 10 s guard
(exit 124). That is why `RESTART_DURABLE_STATE_BUDGET_S=30` in `routes/system.py` did not rescue the 22.10 hang
(journal: silence from 08:10:43 to the manual restart at 08:27:59).
Not established: how a finished future stays in the set in production — all add sites (`_log`, `_submit_db_write`) register a callback whose first action is `discard`. Backlog/producer livelock and a lost callback are both consistent; the fix does not depend on which.

Fix: `AgentSession._await_log_futures` — snapshot, prune done futures, `asyncio.wait(pending, timeout=10s)`, warning on timeout, no
cancellation of pending writes (gather cancelled them). Used by `_drain_handoff_log_writes` and `_build_claude_history_import`.
Other `while <set>: await gather/wait` patterns in app/: none (rg multi-line over app/*.py).

Checks: tests/test_v1020_log_drain_bounded.py (stuck done future; hung write → warning, not cancelled; continuous producers) — all 3 red with the
old loop restored (mutation.log, via pytest-timeout), green now. With session/handoff/restart_liveness/log_write_loss suites: 309 passed (tests.log).
Restart needed (Python); no live process touched.
