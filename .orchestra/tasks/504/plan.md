> **RETRACTED как описание текущего main (08.09.2026, #530).** Ниже — историческое доказательство ветки #504, а не действующий контракт. Утверждения о живых площадках A, необходимости внедрить T1/T2/T3/T5, ожидании T4 и текущей пригодности прежних оракулов отменены коммитом `264daeb75484bbe9f97e53c654180fca11c8a12a`: main уже отделяет управление от прозы, удаляет T4-классификатор и safeguard-fork, использует `provider_limit`, завершение CLI и временный round hint. Исторические результаты тестов остаются результатами своих снимков, не текущего main. Адресная развязка всех десяти площадок и тестов: [дифференциал #530](../530/diff-main-vs-504.md). Исходные байты: `git show bf496f8828e4ae5859ac09fd1a20a864ac9e895b:.orchestra/tasks/504/plan.md`.

# #504 — typed control signals instead of model prose

## Resolved prerequisite: Claude already has the typed event

T1 does not need the fallback “classify only a provider-banner channel.” The production interpreter has `claude-agent-sdk==0.2.114`; its `RateLimitEvent` exposes `RateLimitInfo.status`, `resets_at`, `rate_limit_type`, utilization, overage fields, and exact raw payload. `status="rejected"` is the SDK's documented terminal signal. Orchestra already receives the event at `app/backend_claude.py:1390`, but throws the structure away into `RATE_LIMIT_RAW` status text.

A read-only production snapshot contained 613 real `RATE_LIMIT_RAW` events, proving the path is active. All 613 had primary `status="allowed"` while `overageStatus="rejected"`/`overageDisabledReason="org_level_disabled"`; therefore only primary `status` may control terminal behavior. No rejected event was captured, so the RED uses the exact installed SDK dataclass synthetically. Full evidence: `phase2-field-evidence.md`.

## Scope correction carried into the plan

Phase 1 reported 9 A sites. T2 inspection found a tenth at `app/mcp_stdio.py:3590`: `_CODEX_EXECUTION_FAILURE_JSONL_CHECK` regexes review-model `agent_message.text` and can set `failure_code="execution_guard"`. Research, KB, anchor inventory, and source-to-sink closure are corrected to **10 A / 9 B / 83 inspected C**. The missed site is the same review-execution decision as row 6, so it expands T2 rather than creating a sixth ticket.

## Invariants and implementation sequencing

Every ticket follows this internal order:

1. Add the typed producer signal or producer-owned identity.
2. Consume it at every decision site in the ticket.
3. Run the ticket's positive typed control and negative prose control.
4. Only after steps 1–3 pass, remove the text literal/regex branch.

This order is mandatory inside each Phase-3 ticket. A text guard is never removed while the typed positive control is red. Class B contracts are not changed. No prompt file changes in this task; `DONE`, `## Verdict`, finding headings, task prefixes, and `SILENT_TURN` stay as-is. If a later prompt change is proposed, it is a separate task and follows live typed-path proof.

## Production changes by ticket

- **T1:** `app/backend_claude.py`, `app/events.py`, `app/session.py`, `app/session_turns.py`, `app/limit_wake.py`.
  - Convert SDK `RateLimitEvent` to `AgentEvent(type="rate_limit", content="", metadata=...)` without flattening control fields.
  - `status="allowed"|"allowed_warning"` remains telemetry only. Primary `status="rejected"` arms terminal state.
  - Kind mapping is exact: `overage → monthly`; `five_hour|seven_day|seven_day_opus|seven_day_sonnet → timed`; unknown/missing → terminal `unknown`, no retry and no guessed automatic wake.
  - Persist rejected events as a deterministic `logs.type="rate_limit"` JSON object; `limit_wake` parses that typed artifact and never scans `text` rows. Existing `RATE_LIMIT_RAW` status telemetry may remain for observability, but controls nothing.
  - Legacy logs without a structured rate-limit row are not inferred from prose after deployment; they remain unknown/manual rather than falsely auto-woken.
- **T2:** `app/bg_jobs.py`, `app/mcp_stdio.py`, `app/codex_review_artifact.py` only if a shared JSONL evidence helper belongs there.
  - Remove `_BLIND_REVIEW` matching from artifacts/full stdout.
  - Replace `_CODEX_EXECUTION_FAILURE_JSONL_CHECK` prose regex with typed JSONL evidence: at least one completed `command_execution` with `exit_code=0` proves execution; command attempts with no success fail; model `agent_message.text` is ignored.
  - Preserve the B contract: nonzero process RC, missing/empty artifact, missing `## Verdict`, or structural execution-evidence failure remains loud and records a typed failure code.
- **T3:** `app/harness/loop.py`.
  - Track the exact platform-created round-guard entry objects in one owner collection; filter both `history` and `new_messages` through one identity predicate.
  - Do not add private keys to OpenAI-format message dicts; unknown message keys could break the external API. Byte-identical model output is a different object and survives.
- **T4:** `app/tg_bridge.py`, `app/tool_call_guard.py`, `app/static/js/chat.js`.
  - Overturn “centralize one classifier”: there is no typed runtime event meaning “the model attempted a tool call but printed it.” Centralizing a regex would keep class A.
  - Remove the warning decision from TG and dashboard; actual `tool_use`/`tool_result` events remain the only execution truth. Delete `app/tool_call_guard.py` if `rg` confirms no remaining consumers.
- **T5:** `app/backend_claude.py`, `app/session.py`, optionally new `app/provider_signals.py` as the single provider-banner classifier owner.
  - Safeguard fallback is allowed only inside `AssistantMessage.error == "invalid_request"`, a provider-error channel model prose cannot enter. Emit typed `AgentEvent("safeguard_refusal", metadata={model_error,event_id,...})`; session text handling never classifies it.
  - Compact accepts every nonempty successful summary regardless of words. Typed `rate_limit`, `safeguard_refusal`, or `error` events decide abort/retry; `_GARBAGE_PATTERNS` and `_is_terminal_subscription_limit(summary)` are removed only after typed positive tests pass.

## Tests converted before implementation

Eleven old assertions that encoded text-driven behavior were inverted or moved onto typed stimuli. Every converted test fails on unchanged production with RC=1; names, before/after assertions, and exact failures are in `converted-tests.md`. C01-C09 raw outputs are `converted-C01.txt` … `converted-C09.txt`; C10/C11 reuse `red-T2.txt`/`red-T4.txt`. Test collection is healthy: six modified legacy modules collected 476 tests with RC=0.

## What this plan does not touch

- All 9 class-B contracts and their prompts.
- The 83 inspected class-C deterministic-output lookalikes.
- Database schema: the existing `logs.type/content` envelope can carry deterministic rate-limit JSON.
- Quota thresholds, retry budgets, provider pricing, review verdict semantics, or unrelated dashboard rendering.
- Live-provider tests in the merge suite; no test intentionally exhausts a subscription or starts a second production client.

## Tickets

### T1 — Carry typed Claude limits through session and wake decisions
- Files: `app/backend_claude.py`, `app/events.py`, `app/session.py`, `app/session_turns.py`, `app/limit_wake.py`, `tests/test_rate_limit_capture_441.py`, `tests/test_session.py`, `tests/test_limit_wake.py`
- Test: `PYTHONPATH=. /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_session.py::TestRateLimitClassification::test_t1_monthly_spend_words_are_not_terminal_without_typed_event` — corrected oracle frozen in `58d41c4c`; `refreeze-T1-base.txt` proves RC=1 on unchanged production and `refreeze-T1-wip.txt` proves RC=0 on T1 WIP.
- AC: the named command is green; the exact converted nodes C01-C04 and C07-C09 from `converted-tests.md` are green; a synthetic installed-SDK `RateLimitEvent(rate_limit_info=RateLimitInfo(status="rejected", ...), uuid=..., session_id=...)` sets terminal state and persists typed kind, while `RateLimitInfo(status="allowed", overage_status="rejected")` does not; no control-flow caller reads `_subscription_limit_kind` or limit vocabulary from `text` rows.
- blocked-by: none

### T2 — Make paid review execution depend on typed JSONL/process evidence
- Files: `app/bg_jobs.py`, `app/mcp_stdio.py`, optionally `app/codex_review_artifact.py`, `tests/test_bg_jobs.py`, `tests/test_model_text_control_flow_504.py`
- Test: the prior T2 oracle in `58d41c4c` is superseded because its prose-independence arm had zero command evidence. Corrected snapshot `3a621352` keeps that expected RC=1 beside a completed typed command and adds `test_t2_jsonl_zero_command_events_signal_execution_failure`; mutation/restored outputs are `t2-mutation-red.txt` and `t2-guard-green.txt`.
- AC: the named command is green; `TestRunExecOutcome::test_nonzero_exit_is_failed_not_completed`, `::test_exit_zero_blind_artifact_without_verdict_is_failed`, and `::test_exit_zero_real_verdict_still_completes` are green; JSONL with only failed command events fails structurally, JSONL prose containing every former marker does not affect the result, and a completed `command_execution(status="completed", exit_code=0)` is accepted.
- blocked-by: T1

### T3 — Remove round guards by producer identity, once for both stores
- Files: `app/harness/loop.py`, `tests/test_harness_tools.py`
- Test: `PYTHONPATH=. /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_harness_tools.py::test_t3_model_authored_round_guard_prefix_survives_history_cleanup` — carried unchanged into corrected snapshot `58d41c4c`; `red-T3.txt` → RC=1: both stores lose the model-authored entry.
- AC: the named command and `tests/test_harness_tools.py::test_t6_winddown_warnings_before_cap` are green; one identity predicate removes the platform-created entries from both lists, and byte-identical assistant content survives.
- blocked-by: T2

### T4 — HELD: product decision on unexecuted-tool prose classifier
- Files: `app/tg_bridge.py`, `app/tool_call_guard.py`, `app/static/js/chat.js`, `tests/test_frontend.py`, `tests/test_model_text_control_flow_504.py`
- Test: `PYTHONPATH=. /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_frontend.py::test_t4_model_xml_prose_is_not_classified_as_unexecuted_tool_call tests/test_model_text_control_flow_504.py::test_t4_model_text_classifier_has_no_python_or_browser_owner` — carried unchanged into corrected snapshot `58d41c4c`; T4 remains HELD and `red-T4.txt` remains frozen.
- AC: the named command is green; XML-like model prose renders unchanged in dashboard and TG; actual typed tool cards/results still render through existing tool events; `app/` contains none of the four removed classifier symbols named by the ownership test.
- blocked-by: T3; implementation held pending owner decision

### T5 — Isolate safeguard banners and compact failures to typed provider events
- Files: `app/backend_claude.py`, `app/session.py`, optionally new `app/provider_signals.py`, `tests/test_rate_limit_capture_441.py`, `tests/test_session.py`
- Test: `PYTHONPATH=. /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_session.py::TestSafeguardRefusal::test_t5_text_event_does_not_raise_the_safeguard_flag tests/test_session.py::TestCompactReArmsPromptInjection::test_t5_compact_accepts_short_summary_that_discusses_rate_limits tests/test_rate_limit_capture_441.py::test_t5_safeguard_banner_isolated_by_typed_provider_error_channel` — carried unchanged into corrected snapshot `58d41c4c`; `red-T5.txt` → RC=1 with three seam-specific failures.
- AC: the named command and converted nodes C05/C06 are green; existing rewind/guidance/storage tests remain green; a plain `text` event can never set `_safeguard_refusal` or reject compact, while a typed provider-error/refusal event preserves the real refusal behavior.
- blocked-by: T3

## Frozen RED snapshot

Commit `58d41c4c` is the corrected immutable oracle snapshot. `f21b4ab5` is permanently superseded because T1 compared coroutine objects to names behind an unreachable assertion; replays against it are excluded. `refreeze.md` records the representation-only correction, unchanged-production RC=1, and T1-WIP RC=0. T2/T3/T4/T5 remain byte-identical to their prior oracle versions until the post-refreeze seam check below.

Subsequent authorized representation corrections are frozen in `2e531541`: T2 prose-independence now includes a successful typed command, zero command evidence has its own fail-closed test, and the unrelated resume-UUID fixture includes typed command success without changing its quoting assertions. `refreeze.md` is the supersession ledger; T4 remains held and unchanged in production.

## Review disposition

Luna round 1 found three blocking oracle gaps and one constructor-precision question; all were fixed and independently rerun. Round 2 marked all four prior items FIXED, then found one new blocker: T2 lacked a positive successful-command control. The prose review ceiling is two rounds, so no third review is permitted. The final blocker is resolved mechanically after the ceiling by `test_t2_jsonl_successful_command_event_is_accepted`, which is green on unchanged production inside the exact T2 command (`4 failed, 1 passed`, RC=1). Reviewer artifact: `review-plan.md`; its final recorded verdict remains `NEEDS CHANGES`, not APPROVED.
