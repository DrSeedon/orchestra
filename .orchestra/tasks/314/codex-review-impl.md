<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Focused tests pass, but the implementation can silently lose a held direct message. The Fast/Sol enforcement logic also violates the required stale/unknown fallback and is not wired to real session Fast state.

Test run:

```text
uv run pytest -q docs/tasks/314/oracles/test_t314_enforcement.py docs/tasks/314/oracles/test_t314_session_integration.py docs/tasks/314/oracles/test_t314_analytics.py tests/test_t314_analytics_browser.py
..................                                                       [100%]
18 passed in 8.66s
```

## Findings

blocking: `app/session.py:1399` — A direct-send adaptive hold returns normally after the user message has been removed from the delivery path. It neither retains the message in `_pending_messages` nor raises a denial that lets the caller retry. The caller therefore observes success while the provider never receives the turn, causing message/data loss. The integration oracle only asserts that `backend.send` was not called and consequently blesses this loss. Retain the message with a defined retry/wakeup mechanism, or return an explicit admission failure to the caller.

suggestion: `app/quota_controller.py:73` — Fast and noncritical-Sol checks execute before proving that the adaptive decision is fresh and known. Thus `zone="FAIL_SAFE"` with stale/missing telemetry is held by these branches, directly contradicting “stale/drift/unknown fallback static.” The supplied parameterized oracle even codifies an unknown-confidence hold. Require a fresh, reason-free decision before applying these policies; otherwise return the static result.

suggestion: `app/session.py:1154` — Fast policy is not connected to actual session state. No `AgentSession.fast_mode` field or assignment exists in the named file, while `_shadow_reserve()` also constructs `ShadowDispatchContext` without `fast_mode`. Consequently production reservations and admission always see `False`; the test passes only because it invokes the pure helper with a fabricated context. Pass the server-owned Fast state through the real session path and add an integration oracle.

suggestion: `app/quota_controller.py:78` / `app/session.py:1153` — The Sol rule requires `task_class == "noncritical"`, but production supplies `self.role` as `task_class`. Unless a persisted role is literally named `noncritical`, ordinary noncritical Sol workers bypass this rule. Use the actual server-owned task classification or define an explicit role-to-class mapping, then cover the real `AgentSession` path.

suggestion: `app/quota_controller.py:694` — Rows are processed newest-first, but every bucket assignment overwrites the preceding value. The dashboard’s bucket cards therefore show the oldest observation among the latest 100 decisions, while `latest` and history show the newest decision. Populate a bucket only on its first occurrence or reverse iteration deliberately.

suggestion: `app/session.py:2086` — Queued messages are restored on hold, but nothing schedules another flush. Hot-disabling enforcement does not re-evaluate them “immediately”; they remain stranded until unrelated activity happens to trigger `_flush_pending()`. Add a bounded recheck/wakeup path or make the hold visible to the existing quota wake mechanism.

## Verdict

REJECT — one blocking delivery-loss defect and multiple admission-policy gaps remain.

## Round (2026-08-17T13:29:12Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

- Prior 1 — FIXED: direct adaptive hold now raises explicit `QuotaGateError(code="adaptive_quota_hold")`; the caller no longer receives false success.
- Prior 2 — FIXED: Fast/Sol policy now runs only after a known, fresh, reason-free decision.
- Prior 3 — STILL BROKEN: `task_class` and `fast_mode` fields exist, but the reviewed production diff does not populate or hydrate them. Tests manually assign them, so real sessions still default to `"worker"` and `False`.
- Prior 4 — STILL BROKEN: same missing production population means the noncritical-Sol rule cannot reliably activate.
- Prior 5 — FIXED: newest bucket observation is retained.
- Prior 6 — STILL BROKEN: the retry was added, but `_flush_pending()` no longer releases `_lifecycle_lock`.

## New findings

blocking: `app/session.py:1974-2138` — The previous `finally: self._lifecycle_lock.release()` was removed. Every path after the loop’s `break` retains the lock, including successful delivery, adaptive hold, and exceptions. On adaptive hold, `_retry_adaptive_hold()` wakes after five seconds, calls `_flush_pending()`, and blocks forever acquiring the same lock. Subsequent lifecycle operations can also deadlock. Restore unconditional lock release around the post-admission section.

suggestion: `app/session.py:339` — Adding defaulted dataclass fields alone does not establish server-owned values. The current diff has no production assignment or persistence/hydration for `task_class` or `fast_mode`; only tests mutate them directly. Wire them from authoritative session/task metadata and test construction or restoration through that real path.

Verification performed:

```text
uv run python -m pytest -q docs/tasks/314/oracles/test_t314_enforcement.py docs/tasks/314/oracles/test_t314_session_integration.py docs/tasks/314/oracles/test_t314_analytics.py
.................                                                        [100%]
17 passed in 0.98s
```

The green suite does not exercise queued-hold retry completion or assert that `_lifecycle_lock` becomes available afterward.

## Verdict

REJECT — the queued-hold fix introduces a shared-session deadlock.

## Round (2026-08-17T13:45:39Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

- Direct-send hold — FIXED: resets to IDLE and raises explicit `adaptive_quota_hold`.
- Queued lifecycle lock — FIXED: unconditional `finally: self._lifecycle_lock.release()` restored.
- Server-owned `task_class` / `fast_mode` — FIXED: derived in `AgentSession` and propagated through real shadow/admission contexts.
- Luna Fast admission — FIXED: Luna is no longer rejected in tight zones.
- Analytics/API fields and redaction — FIXED: routing fields are exposed without decision IDs or secrets.
- #291 T1–T4 immutability — FIXED: `git diff --exit-code` reports no changes.

## New findings

blocking: `app/mcp_stdio.py:588` — `_CODEX_REVIEW_DEFAULT_MODEL` remains `"gpt-5.6-sol"`. Therefore omitted-model review requests still default to Sol, contradicting the required server default of Luna Fast for all review paths. Conditional rerouting only helps when telemetry reports suppression; under normal or missing telemetry, the default remains Sol. Make the review default Luna and ensure the worker default follows the same server-owned policy.

suggestion: `app/quota_controller.py:949` — Sol suppression is derived from the globally latest shadow decision’s zone, regardless of provider or freshness. A latest Grok/Anthropic decision can suppress Codex Sol, while a stale Codex decision with `zone="FAIL_SAFE"` and merely `data_available=True` suppresses Sol instead of falling back static. Derive status from the newest fresh Codex-primary constraint and expose unavailable/stale telemetry as static fallback.

## Verification

```text
uv run python -m pytest -q docs/tasks/314/oracles/test_t314_enforcement.py docs/tasks/314/oracles/test_t314_session_integration.py docs/tasks/314/oracles/test_t314_analytics.py tests/test_t314_analytics_browser.py
.......................                                                  [100%]
23 passed in 8.99s
```

```text
uv run python -m pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py docs/tasks/291/oracles/test_t2_adaptive_gate.py docs/tasks/291/oracles/test_t3_shadow_delivery.py docs/tasks/291/oracles/test_t4_replay_evidence.py
.....................                                                    [100%]
21 passed in 2.48s
```

## Verdict

REJECT — the review path still defaults to Sol, so the new mandatory Luna-default policy is not fully enforced.

## Post-review mechanical closure (orchestrator-authorized; no round 4)

Round 3 remains **REJECT** above as the canonical Sol verdict. Per orchestrator direction,
the two findings were fixed after the review ceiling; this is mechanical evidence, not a
fourth reviewer round.

1. Review default closure:

   ```text
   grep -n '_CODEX_REVIEW_DEFAULT_MODEL' app/mcp_stdio.py
   590:_CODEX_REVIEW_DEFAULT_MODEL = "gpt-5.6-luna"
   uv run python -m pytest -q tests/test_mcp_stdio.py::test_codex_review_default_is_server_owned_luna_fast
   . [100%]
   1 passed
   ```

   Mutation `_CODEX_REVIEW_DEFAULT_MODEL = "gpt-5.6-sol"` was caught by that test
   (`rc=1`) and the source was restored and touched before the green rerun.

2. Provider/freshness closure:

   `ProductionShadowController._latest_codex_lane()` accepts only a fresh (<300 s),
   reason-free `codex:primary` constraint with known confidence. The scoped oracle covers
   fresh Codex suppression, fresh Grok non-suppression, and stale Codex fallback:

   ```text
   uv run python -m pytest -q docs/tasks/314/oracles/test_t314_enforcement.py
   .............. [100%]
   14 passed
   ```

   Replacing both `item.get("bucket") == "codex:primary"` checks with Grok checks was
   caught (`provider_scope_mutation caught=True rc=1`); the source was restored and touched.

   The real-session task-class spoof mutation was also caught:

   ```text
   uv run python -m pytest -q docs/tasks/314/oracles/test_t314_session_integration.py::test_t314_task_class_field_cannot_spoof_server_role
   . [100%]
   task_class_spoof_mutation caught=True rc=1
   ```

3. Scoped green evidence after closure:

   ```text
   uv run python -m pytest -q docs/tasks/314/oracles/test_t314_enforcement.py docs/tasks/314/oracles/test_t314_session_integration.py docs/tasks/314/oracles/test_t314_analytics.py
   24 passed
   uv run python -m pytest -q tests/test_t314_analytics_browser.py
   3 passed
   uv run python -m pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py docs/tasks/291/oracles/test_t2_adaptive_gate.py docs/tasks/291/oracles/test_t3_shadow_delivery.py docs/tasks/291/oracles/test_t4_replay_evidence.py
   21 passed
   git diff --exit-code f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b -- docs/tasks/291/oracles
   exit 0
   ```
