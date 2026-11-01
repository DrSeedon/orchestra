# V-1028: quota-held worker reports and missed auto-reports

Implementation is ready for review; exact historical attribution of the four listed turns remains unverified because this private copy contains neither their event rows nor a live DB. No service restart, deployment, repository commit, push, or credential access was performed. The platform owns committing this copy on `task-V-1028/fix-api`.

Suggested commit header: `V-1028: make quota-held reports visible and fix parent report tracking`.

## Confirmed causes and changes

1. `app/turn_signals.py` retries quota-blocked reports by keeping them `pending` with `QuotaGateError:` in `last_error`. It formerly had no worker status or upstream diagnostic. `app/message_deliveries.py` likewise retained `WAITING_QUOTA` receipts without notifying the target parent's parent.
2. `app/report_holds.py` now projects the canonical queues (including reports queued behind a `WAITING_QUOTA` head). It adds one durable worker `status` log per report and a `report_quota_hold` projection in the sessions list. The dashboard shows an amber worker-card line and the selected worker's status detail, with the quota reason and hub hint in the tooltip.
3. One diagnostic per held report goes to the parent's own parent, resolved by ID or name within its scope. It includes the source worker, blocked parent, report reference, reason, and `hubsol` / `hubsonnet` / `hubopus` plus `model_reason` hint. It contains no report body. A separate durable notice ledger, in-flight claim, and stable `InjectedMessage.event_id` reconcile retries and crashes after acceptance. Existing turn-signal and quota-queue sweeps recover old holds, including signals still in backoff. Delivered, released and cancelled reports immediately leave the visible hold projection.
4. Original reports keep `origin="agent"` and their existing admission path. Only the platform diagnostic uses the existing platform-message origin. The quota gate and its exemptions are unchanged; tests and a quota-bypass mutation verify that the report body remains parked.
5. In `app/harness/loop.py`, MCP transport/server refusals are strings beginning `[mcp error]`; the old failure predicate omitted that prefix. Consequently they could reach `AgentSession` with `is_error=False`. The prefix now marks the event as an error.
6. In `app/session.py`, any successful tool whose name contained `send_message` used to set `_did_report=True`, irrespective of recipient. Tracking now pairs the tool call ID, turn generation, exact tool name, recipient and positive receipt. Only a successful/durably accepted send to this worker's parent suppresses the fallback signal. Failed, unknown, unrelated-recipient and stale-turn results do not. A parent ID without a parent name is also sufficient to enable reporting.
7. Auto-report exclusions now log their actual reason: manual interruption, owner-originated input, pending messages, compaction, successful empty output, explicit parent report, exact silent marker, background job wait or server-error retry. Existing suppression policies are preserved.
8. **Hub DONE duplication (seedon follow-up):** `HubBackend._run_outbox` executes through `HubBridge` and the local API without emitting the native `tool_result` that used to set `_did_report`. The outbox now invokes a session-owned callback after a positive parent receipt. The callback checks the captured turn generation and parent identity. The shared receipt predicate recognizes durable `WAITING_QUOTA` receipts despite their informational `error` field; refusals, ambiguous outcomes, progress/checklist calls and late results cannot mark the current turn reported. A test executes the real backend outbox method and then the real session `turn_end` handler, asserting exactly one parent message.

Quota-hold recovery runs in a coalesced background task. A slow upstream cannot delay durable receipt acceptance or quota release; a new hold requested during a recovery schedules a further scan. Detached upstream sessions are loaded before notification; lookup failure leaves the durable notice pending.

## The four historical misses: evidence boundary

- **Harness / DeepSeek, two turns:** a concrete runtime defect is reproduced and fixed: `[mcp error]` was emitted with success metadata, allowing `_did_report` to suppress the durable fallback. Sending to another agent also suppressed the fallback. The supplied aggregate does not include those two turns' tool calls/results, so neither defect can honestly be attributed to either specific historical turn yet.
- **edu-video, Claude Opus, 2026-10-21T14:23:21Z:** a final text alone does not explain suppression. Tests of the actual `turn_end` path demonstrate that a parented Claude worker with final text produces a durable signal. Owner-originated input, an earlier incorrectly counted send, pending input/background work, fan buffering or manual interruption require the local event/provenance rows to distinguish. No evidence that this particular report was unnecessary was supplied.
- **urok-svyaz, Luna, 2026-10-22T08:12:40Z:** a provider `stop_reason="interrupted"` with no manual interrupt produces a failed-turn report through the real turn-end handler. `AgentSession.interrupt()` explicitly sets `_manually_interrupted`; the existing manual-stop policy then suppresses reporting. The local `interrupt requested` record is needed to establish which happened in that turn. `interrupted` by itself is not proof of manual cancellation.

Required local follow-up: for each turn, inspect its incoming message provenance, send-message tool inputs/results and delivery receipts, `interrupt requested`, fan/background/pending state and adjacent errors. Do not export the DB or secrets. The new skip logs make future attribution explicit. Outcome (2) is not claimed complete for these four historical records.

## Checks

- Offline tests use the frozen dependency lock and an isolated SQLite DB. All temporary directories were inside this task directory; tests ran sequentially at nice 15 with a 2 GiB address-space limit. Import identity is checked against `app/__init__.py` in this working copy.
- `tests-final.log`: **638 passed, 2 deselected** in 39.00s. The two explicitly deselected hub prompt tests fail because this copy omits `prompts/hub/worker.md`; the unchanged `hub_preamble` falls back to `PREAMBLE_BASE`, which lacks the tested names and literal rule wording. Their failures are retained in `tests-hub.log`. No assertion or production prompt was weakened.
- The initial wider run (`tests-regression.log`) had 596 passed and 128 failed. One was a new JS test stub's interpolation bug, corrected and re-run. The other failures were 115 manager and 12 quota-admission tests requiring missing pipeline/prompts/skills or their downstream role/resume behavior. This copy omits `.orchestra/pipelines/default/pipeline.yaml` and the referenced prompt assets. No fabricated pipeline or weaker assertion was added to make them pass. Full repository acceptance must run on the orchestrator's complete checkout.
- New tests cover signal holds, acceptance-time and dispatch-time delivery holds, FIFO quota blockage, old records, malformed error metadata, parent name/ID lookup, no upstream parent, concurrent recovery, failure before notification acceptance, crash after acceptance, quota release/cancellation, a slow or detached upstream, UI text rendering, parent/sibling sends, harness refusals, provider interruptions, intentional skip reasons, and hub outbox DONE/failed/progress/late-result paths.
- **14/14 mutations killed** by behavioral assertion failures; definitions, patches and failure logs are retained beside this report (`mutations.json`). Removing the hub outbox callback produces **two** parent messages (DONE followed by `auto_report`), as requested. The sources are restored in a `finally` block after each mutation; a final clean-source smoke run is in `tests-after-mutations.log`.
- `tests-after-mutations.log`: **66 passed** in 10.67s after all source restorations. `verified-files.json` records the imported working-copy module, source hashes, Python AST checks, JavaScript syntax checks and publication-boundary filtering of task artifacts through `app.secret_mask.mask_secrets`.

Focused reproduction on a complete checkout:

```sh
uv run --offline --frozen python -m pytest tests/test_v1028_auto_report.py tests/test_v1028_report_holds.py tests/test_v1028_report_hold_frontend.py tests/test_v1028_hub_outbox_report.py -q
uv run --offline --frozen python .orchestra/tasks/V-1028/mutation_checks.py
```

## Deployment and remaining limits

Python changes require an owner-authorized service restart after acceptance. No restart was performed. No live delivery, live UI or live model calls were exercised. The exact four-turn forensic attribution and a complete-checkout regression run remain outstanding.

Mutation design note: deleting only the immediate signal-recovery wake survived because the already scheduled sweep recovery independently observed the held signal. That is valid redundancy, not a missing behavior check. The retained signal-loss mutation disables quota-signal observation itself, which must make the end-to-end visibility/notification check fail. The hub duplicate mutation removes the callback wiring; its test proceeds through `turn_end` so the failure is the second parent message, not merely a private flag assertion.
