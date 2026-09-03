# #290 — Codex implementation review journal

- Attempt 1 started 2026-08-16 against immutable implementation SHA
  `434f7a7df67ee8884f6f9c1040f43e13711e63ed`; target diff
  `/tmp/r290-impl-434f7a7d.diff` from merge-base
  `366367f5d6d3fe85c90be0aa91f2c7608ce95460`.
- Attempt 1 did not start a reviewer and spends no review round. Tool refusal (verbatim):
  `weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for gpt-5.6-sol is unavailable or stale (FileNotFoundError: FileNotFoundError: [Errno 2] No such file or directory).`
- Attempt 2: direct `codex exec` fallback against the same immutable diff.

## Round 1

### Summary

Reviewed the specified production paths, tests, and artifacts. The frozen oracle is
unchanged from `a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c`
(`cmp_exit=0`).

Test command:

```text
.venv/bin/python -m pytest -q tests/test_runtime_handoff_v2.py tests/test_runtime_handoff_recovery.py tests/test_runtime_history.py tests/test_session.py tests/test_native_history_import.py -k 'runtime_handoff or handoff or state_packet or cross_runtime_packet or codex_model_switch_preserves_native_thread or two_db_backed_claude'
```

Literal result:

```text
1 failed, 58 passed, 221 deselected, 2 warnings in 13.36s
```

The failure is the real Claude rate-limit canary and therefore blocked evidence, not
success.

### Findings

- **blocking — `app/runtime_history.py:589`:** “total model-visible context” is not
  actually counted. `build_model_visible_manifest()` records MCP server configuration
  under `tool_schemas`, but omits Claude Code’s preset system prompt, built-in tool
  schemas, resolved MCP schemas, loaded skills, and user/project/local setting contents.
  The validation canary may fit while the normal target overflows on its first useful
  turn. Build the manifest from the exact serialized provider request or conservative
  measured token counts for every effective prompt/tool/settings component.
- **blocking — `app/session.py:3212`:** the “independent normal-profile capability
  receipt” is only a constructor self-description. `actual_descriptor` and
  `actual_manifest` are computed before the normal backend connects; after connection,
  the code verifies only the native session ID. It never inspects the normal client’s
  effective tools, settings, hooks, or schemas. Provider/config discovery can therefore
  produce a different capability surface while the locally predicted fingerprint still
  passes. Connect the normal profile first, then obtain and validate a receipt from its
  effective live options/surface before releasing the source.
- **blocking — `app/session.py:1406`:** packet preparation silently tolerates failed log
  persistence. `_drain_handoff_log_writes()` uses `gather(...,
  return_exceptions=True)`, while completed failed futures are removed by callbacks before
  the drain can inspect them. If both a tool call and result fail to persist, the DB
  snapshot contains no pending effect and the switch may succeed after losing evidence of
  an external side effect. Track a durable log-write failure generation and reject handoff
  preparation whenever any write through the frozen boundary failed.
- **blocking — `app/manager.py:1628`:** lazy loading bypasses unfinished-handoff
  recovery. Startup only supplies `recovery_handoff` through the auto-resume loops;
  `ensure_loaded()`, `ensure_loaded_by_id()`, and `ensure_loaded_any()` call
  `_load_from_db()` without looking up a pending ledger entry. Sessions excluded from
  startup auto-resume—especially sources with `session_id=NULL`—can later load normally,
  send, or attempt another switch while an allocated/staged target remains unresolved.
  Every load path must resolve the latest unfinished handoff before exposing the session.

### Verdict

**REJECT — four blocking correctness/recovery issues remain.** Codex and Grok correctly
stay disabled, but Claude must also remain disabled until the live canary passes and these
blockers are fixed.

## Round 2

## Summary

All four Round 1 blockers are closed in the currently disabled release:

- Cross-runtime admission is false for Claude, Codex, Grok, and OpenCode.
- The future Claude path connects and inspects the normal target before source release.
- Failed log writes leave a monotonic failure marker that blocks snapshot preparation.
- Every `_load_from_db()` path now resolves unfinished handoffs, including lazy loads and
  `session_id=NULL`.
- The frozen oracle remains byte-identical: `cmp_exit=0`.

Exact test command:

```text
.venv/bin/python -m pytest -q tests/test_runtime_handoff_v2.py tests/test_runtime_handoff_recovery.py tests/test_runtime_history.py tests/test_session.py tests/test_backend_claude.py -k 'runtime_handoff or handoff or state_packet or codex_model_switch_preserves_native_thread or two_db_backed_claude or normal_surface or log_write'
```

Literal result:

```text
65 passed, 241 deselected, 2 warnings in 11.69s
```

Required artifact quote verification:

```text
$ grep -F 'cross-runtime admission remains fail-closed until that gate is rerun GREEN.' app/runtime_registry.py
        # cross-runtime admission remains fail-closed until that gate is rerun GREEN.
```

## Findings

blocking: `app/backend_claude.py:1120` — `ClaudeBackend.disconnect()` catches and suppresses
SDK disconnect failures, then clears `_client` and deletes its MCP configuration. Consequently
`_disconnect_backend()` and `_retire_staged_handoff()` cannot distinguish successful release from
an orphaned validation, normal-target, or source client. In the future cross-runtime path this can
advance to `source_released` after an unproven source release; in the currently enabled
same-provider switch it can silently leave the old tool-capable client alive after ownership moves
to the target. Perform local cleanup in `finally`, but re-raise the disconnect failure so ownership
becomes `recovery_required` and the staging locator is retained until cleanup is proven.

## Verdict

**REJECT — the negative cross-runtime release correctly closes the four prior blockers, but
cleanup/source ownership is still not fail-closed because Claude disconnect failures are reported
as success. Cross-runtime capabilities must remain disabled, and the connected-receipt path must
not be enabled until disconnect failure propagates into recovery handling.**

## Round 3

## Summary

Round 2’s direct disconnect blocker is fixed: `ClaudeBackend.disconnect()` now re-raises SDK
failure after local cleanup, both staged clients are retired, and the same-runtime path does not
adopt the target after ambiguous source release.

However, the new durable same-runtime recovery path is unreachable because preparation still
refuses to insert a ledger record when source and target runtimes match. This leaves the ambiguity
guard memory-only and unsafe across restart.

The frozen oracle remains byte-identical: `cmp_exit=0`.

Exact test command:

```text
.venv/bin/python -m pytest -q tests/test_runtime_handoff_v2.py tests/test_runtime_handoff_recovery.py tests/test_runtime_history.py tests/test_session.py tests/test_backend_claude.py -k 'runtime_handoff or handoff or state_packet or codex_model_switch_preserves_native_thread or same_runtime or disconnect or two_db_backed_claude or normal_surface or log_write'
```

Literal result:

```text
75 passed, 234 deselected, 2 warnings in 13.71s
```

Required quote verification:

```text
$ grep -F 'Freeze an eligible packet and its ledger row before target creation.' app/session.py
        """Freeze an eligible packet and its ledger row before target creation."""
```

## Findings

blocking: `app/session.py:1532` — same-runtime preparation returns `None, result` before inserting
`runtime_handoffs`, so `get_runtime_handoff(handoff_id)` at line 3950 is always false for real
same-provider switches. The newly added `native_resume` attempt, `source_released` state, and atomic
`confirm_runtime_handoff()` path are therefore unreachable outside mocked tests. If source
disconnect or target cleanup is ambiguous, `_handoff_recovery_required` exists only in memory; a
crash or restart loses the guard and lazily reloads the old DB owner without an unfinished ledger
operation. Insert the prepared ledger row for same-runtime changes so ambiguity and ownership
survive restart; distinguish `native_resume` through the attempt mode rather than skipping the
operation record.

## Verdict

**REJECT — the Round 2 disconnect propagation is correct, but its durable crash-recovery fix is
bypassed in production by the same-runtime early return. This is an actual blocking recovery
defect, not future hardening. Cross-runtime capabilities correctly remain disabled.**
