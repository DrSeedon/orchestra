# #235 — test isolation diagnosis

## Red oracle

Command, run before any change with no `data/orchestra.db` in this worktree:

```text
uv run pytest -q tests/test_api.py::test_send_quota_refusal_is_canonical_429
F                                                                        [100%]
E       assert 500 == 429
sqlite3.OperationalError: no such table: fan_barriers
1 failed in 12.74s
```

The failed run created a 4 KiB untracked `data/orchestra.db`; it was removed after
the observation. The production checkout/database was not touched.

## Established cause

This is not early binding, a cached connection, or an import-by-value escape.
`app.fan_barrier` imports the `app.db` module and every operation calls
`db._conn()`; `_conn()` reads `db.DB_PATH` at call time.

The target test never activates the fixture that patches that attribute:

- `tests/test_api.py:18` defines `db(tmp_path, monkeypatch)`, patches
  `app.db.DB_PATH`, and runs `init_db()`.
- `client` depends on `db`.
- `test_send_quota_refusal_is_canonical_429` requests only `monkeypatch`, and
  invokes the route directly, so neither fixture runs. `pytest
  --fixtures-per-test` confirms that `db` and `client` are absent.
- Supplying `sender="root"` enters the fan-barrier branch added by `db381e31`.
  `peek_summary()` opens the default DB before the mocked `manager.send()` raises
  the expected `QuotaGateError`.

The narrow repair is therefore to make the target test depend on its existing
`db` fixture. A suite-wide regression guard should fail whenever a test attempts
to connect to the resolved production path.

## Similar patching sites

`rg` finds 62 `DB_PATH` monkeypatch sites in 48 test files. They are:

`test_adhoc_switch.py`, `test_api.py`, `test_auto_report_undelivered.py`,
`test_bg_jobs.py`, `test_blobs.py`, `test_bug_report_notify.py`,
`test_build_signal.py`, `test_cache_tokens.py`, `test_codex_review_artifact.py`,
`test_codex_review_sandbox.py`, `test_codex_usage.py`, `test_db.py`,
`test_fan_barrier.py`, `test_fan_barrier_gates.py`, `test_fan_enable.py`,
`test_identity_drift.py`, `test_limit_wake.py`, `test_log_write_loss.py`,
`test_logs_sync.py`, `test_mailbox.py`, `test_manager.py`,
`test_mcp_codex_review.py`, `test_merge_branch_drift.py`,
`test_merge_operations.py`, `test_merge_stuck.py`,
`test_orchestrators_payload.py`, `test_p1_union.py`, `test_quota_alert.py`,
`test_quota_alert_state.py`, `test_quota_headroom.py`,
`test_quota_runway_baseline.py`, `test_return_to_merged_branch.py`,
`test_runtime_history.py`, `test_runtime_router.py`,
`test_runtime_router_db.py`, `test_secret_mask.py`, `test_session.py`,
`test_session_id_guard.py`, `test_startup_bridge.py`, `test_subagents.py`,
`test_tg_bridge.py`, `test_tm.py`, `test_turn_usage.py`,
`test_undelivered.py`, `test_undelivered_queue.py`,
`test_usage_analytics.py`, `test_usage_history_resolution.py`, and
`test_workspace.py`.

This inventory is not evidence that those tests escape their patches; it is the
requested set using the same mutable-global technique. A global connection guard
is preferable to auditing this list once because future omissions are otherwise
silent whenever the production schema happens to satisfy the test.

## Production defect and repair

The same escape exposed a production defect independent of test isolation:
`peek_summary()` and `should_buffer()` run before the primary send. A database from
before #231 therefore turns an ordinary send into HTTP 500 until its schema is
migrated. `SessionTurnRuntime.fire_auto_report()` has the same optional lookup,
and `SessionManager.remove()` records a killed fan member before continuing the
primary removal.

`app/fan_barrier.py` now treats absence of exactly `fan_barriers` or `fan_members`
as "no active barrier" at those three entry points. Other
`sqlite3.OperationalError` values still propagate. The original red target now
reaches its mocked primary send and returns the expected canonical 429 even when
the local default database has no tables.

## Remaining blocker

The higher-priority worker contract forbids editing any test, fixture,
`conftest.py`, test helper, or test configuration, and also makes the received
acceptance test immutable. Consequently, the remaining two requested changes
cannot be made in this worktree:

- add the existing `db` fixture to the target test, so it never creates or opens
  the default path;
- add an autouse connection guard that rejects the resolved production path for
  every test.

The production fail-open makes the named oracle green, but does not repair this
isolation layer: the unpatched target still creates a 4 KiB empty default DB when
run here. That file was removed after every probe. The production checkout and
its database were never touched.
