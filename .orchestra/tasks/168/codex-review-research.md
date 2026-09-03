## Summary

Unable to perform an evidence-based review because the workspace sandbox rejects every file-read command with:

`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`

No files were edited. I won’t invent findings without reading the research and referenced code.

## Findings

**[blocking] Review infrastructure prevented access to the requested evidence**

I could not inspect `docs/tasks/168/research.md` or the explicitly allowed source files, so none of the six load-bearing claims could be verified or falsified.

## Verdict

**Blocked — no technical verdict.** Retry once workspace command execution is restored.

## Round (2026-08-08T08:01:58Z)

## Re-review status

### Round 2

- **FIXED — evidence availability:** The packet is sufficient to assess the research conclusions without filesystem access.
- **FIXED — claim 1:** `provider_readiness` demonstrably cannot implement the required gate. At Anthropic weekly utilization `97`, it returns available because it uses `>=100`; selection must use `window_minutes == 10080` and block at `>=95`.
- **STILL BROKEN — claim 2:** Placing the check after the `RUNNING` steering branch and under `_lifecycle_lock` is correct for ordinary external sends, but it does not by itself distinguish a genuinely new turn from internal continuation/retry through `self.send`.
- **FIXED — claim 3:** The proposed exemptions align with the requirement: orchestrator sessions, stop, active-turn steering/reconnect, and model changes remain allowed. A subsequent turn must be evaluated against the newly selected provider.
- **FIXED — claim 4:** Fail-open missing/stale data is a bypass. For non-orchestrator new turns, unknown weekly quota must fail closed.
- **FIXED — claim 5:** The authoritative `is_orchestrator` exemption preserves notification and error-report delivery because those paths target the orchestrator through `manager.send`.
- **FIXED — claim 6:** Spawn preflight and `codex_review` should share the decision logic, but preflight cannot be authoritative because spawning and the initial send are separate operations. The actual execution boundary must decide again.

## New findings

**[blocking] Internal continuation must not be classified solely by `status != RUNNING`**

`self.send` is used by retry/max-turn paths. If one of those calls occurs after status has transitioned out of `RUNNING`, a gate placed solely after the steering branch can interrupt an existing logical turn, contrary to the requirement. Admission needs an explicit provenance flag/token distinguishing `new_work` from continuation, with external calls defaulting to `new_work`.

**[blocking] Freshness must be enforced from source timestamps, not the current readiness envelope**

The cache can serve old data after refresh failure, while the readiness envelope labels it fresh without a timestamp. A hard gate therefore needs a verifiable observation timestamp and maximum age. Missing, malformed, or stale weekly data must deny new non-orchestrator work while leaving exemptions operational.

**[suggestion] `_flush_pending` should be checked at execution time**

It starts a distinct backend send after the previous turn ends, so it is an admission boundary for new queued work. Checking when originally queued is insufficient because quota may cross 95% before flushing. Restoring pending state on denial is appropriate; denial should not be treated as a backend failure.

**[question] Compaction is not clearly within the stated policy**

The requirement blocks “NEW WORKER turns,” while native/summary compaction is maintenance associated with an existing session. The evidence does not establish whether compaction must be denied at 95%. Treat this as a product-policy decision, not a proven research conclusion. If gated, ensure denial cannot prevent switching providers or preserving session state.

**[suggestion] A session-local callback can avoid circular imports**

Inject a narrow admission service/callback into `AgentSession`, returning a structured decision from provider, session role, operation kind, and quota snapshot. Keep provider/window interpretation outside `session.py`; do not have the callback call back into `SessionManager` while its lock is held. The same pure decision can serve send, flush, spawn preflight, and `codex_review`, while execution boundaries remain authoritative.

**[suggestion] Alternative-provider errors need gate-specific availability**

The suggested provider must have a known, fresh weekly window below 95% and correspond to the selected quota bucket—particularly distinguishing `codex` from `codex_spark`. Existing `provider_readiness` and the hardcoded Claude alternative cannot support that promise.

## Verdict

The central research conclusion is sound: the current readiness logic and #154 MCP gate cannot enforce #168, and authoritative admission belongs at each actual new-work execution boundary. Approval should be conditional on explicitly separating internal continuation from new work, defining timestamp-based fail-closed behavior, and resolving whether compaction is policy-covered.

## Round (2026-08-08T08:02:59Z)

## Re-review status

- **FIXED — internal retry/auto-continue:** Author’s rebuttal is correct. After `turn_end`, status becomes `IDLE/WAITING`; `_auto_continue` and `_retry_after_server_error` start a new provider turn. They must pass admission. No provenance exemption is warranted, and adding one would create a quota bypass.
- **STILL BROKEN — freshness:** Accepted but not yet folded into the research. The authoritative gate must require a trustworthy observation timestamp and fail closed for missing, malformed, or stale weekly data.
- **FIXED — `_flush_pending`:** It starts a new provider turn after the previous turn finishes and therefore must be admitted at execution time.
- **FIXED — compaction scope:** Claude summary and acknowledgement sends made while idle are new provider turns and should be deferred by the exhaustive gate. Native Codex compaction may conservatively share admission, but that point is not load-bearing.
- **FIXED — callback architecture:** A narrow injected admission callback/service can avoid circular imports without weakening authority.
- **FIXED — alternative-provider guidance:** Alternatives must be derived from fresh gate-specific weekly availability, including correct separation of `codex` and `codex_spark`.

## New findings

None.

## Verdict

**Research conclusions approved once timestamp-based stale/unknown fail-closed behavior is explicitly incorporated.** The lifecycle placement is correct: allow only operations belonging to the currently `RUNNING` provider turn; retries, auto-continue, pending flushes, and idle Claude compaction sends are new turns requiring admission.
