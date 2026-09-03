## Summary

The core negative conclusion is sound: Sol and Luna map to the same `codex` quota bucket, Luna’s savings are unmeasured, and changing an existing Codex worker’s model resets its native session.

However, the proposed Phase 2 mechanism is not ready to build as written. The document places routing before the information needed to make its trusted decision exists, overstates what four quota windows establish, and treats Spark as a small model tier even though the current router explicitly excludes it and does not observe its separate bucket.

## Findings

1. **blocking:** `docs/tasks/216/research.md:62-70,291-294` — The claimed substitution seam “immediately after `resolve_model`” cannot implement the document’s own server-owned classification. At `app/manager.py:526`, the role has not been normalized, the active pipeline and parent have not been resolved, `is_orch` is unknown, and `validate_spawn` has not run. Moreover, `RoutingInput.task_class` is merely a validated field (`app/runtime_router.py:135-159`); the reviewed files contain no production entrypoint constructing it, and `manager.py` never invokes `RuntimeRouter.admission`. The code therefore does **not** currently establish the claimed trusted task class at that seam. The viable interval is after the server has derived the class—at least after role/pipeline/parent resolution and spawn validation—but before the existing model-specific admission at `manager.py:633-636`, and still before backend/effort resolution at `:659-662`. Specify the actual derivation and integration point before Phase 2; otherwise the implementation must either guess the class or trust caller data, producing the wrong mechanism.

2. **blocking:** `docs/tasks/216/research.md:176-193,298-299,311-318` — The backtest does not support selecting `ratio ≥ 2.0`, 18 hours, and 15 pp as an operational cutoff. Of four windows, one entered observation already exhausted, one ended before warm-up, one signalled but reset at 87% rather than reaching exhaustion, and one is still in progress. Thus the claimed “2/2 идущих в стену” is not an observed 2/2 outcome. There are zero calm windows, so false-positive rate is wholly unidentified; the document is commendably explicit about that, but then promotes the same numbers into the Phase 2 policy. Treat these values as an experimental/pilot configuration with no automatic quality downgrade until prospective evidence exists, or justify them from a separately defined loss function. Parameterizing an unsupported cutoff does not validate it.

3. **blocking:** `docs/tasks/216/research.md:272-275,295-297` — Spark is not an ordinary degraded model within the existing Codex candidate. `RoutingModelsV1.validate_runtimes` explicitly rejects Spark (`app/runtime_router.py:50-56`), `_load_observation` loads only `codex`, not `codex_spark` (`:415-438`), and evaluation creates exactly one Codex candidate from that primary bucket (`:569-588`). Yet the design says Spark is the immediate degraded route before Luna is measured. Implementing only the proposed “minimal” model-tier extension would either continue judging Spark availability from the wrong `codex` pool or fail policy validation. Spark requires a separate quota candidate/observation and explicit selection semantics; the research should describe this as a separate-bucket router extension, not merely `codex.spark_eligible_classes`.

4. **suggestion:** `docs/tasks/216/research.md:291-294` — The contract between the caller’s explicit `model` argument and the router is underspecified and conflicts with current router terminology. `RoutingInput` has `manifest_model`, `current_model`, and `review_default_model`, but no requested model; in manifest-default mode, `worker_general` selects `manifest_model` (`app/runtime_router.py:627-645`). Meanwhile, `manager.py` receives an explicit resolved model. Define whether that argument becomes `manifest_model`, a new `requested_model`, or is ignored under quota mode, and ensure manifest-default preserves today’s explicit spawn behavior. Otherwise merely activating the router can change behavior even when quota routing is disabled.

5. **suggestion:** `docs/tasks/216/research.md:133-144` — “Ровно та же потеря, что при уходе на другой рантайм” is too broad. The principal claim is correct: for Sol→Luna, `resume_across_models=False` makes `native_session_reset` true and clears `session_id` (`app/session.py:2603-2633`; `app/runtime_registry.py:315-323`). But Claude↔Codex changes take dedicated history-transfer paths before that generic branch (`session.py:2591-2601`), whereas same-runtime Codex switching uses `_build_runtime_handoff`. Both reset the native ID, but their preserved history and failure modes are not necessarily identical. State the narrower proven conclusion: Sol→Luna cannot resume the native Codex session and requires a lossy handoff.

6. **suggestion:** `docs/tasks/216/research.md:255-258,300-301` — The document notices the Luna prompt contradiction but does not fully resolve ownership. `base.md` says Luna is allowed only on explicit pilot instruction, while the proposed server policy would select it without such an instruction. Updating that sentence conditionally “если автоподмена её ставит” leaves two authorities: prompt policy and server policy. Phase 2 should make the server policy authoritative and rewrite the prompt to describe that deterministic behavior, including that an orchestrator request can be downgraded. Otherwise agents will receive instructions contradicting the actual selected model.

## Verdict

**NEEDS WORK — 3 blocking findings.** The bucket and native-session conclusions survive review, but the proposed seam, threshold evidence, and Spark path would lead Phase 2 toward an incomplete or incorrect routing mechanism.

Sight-verification quote from the reviewed artifact:

> “Порог, который нельзя подвинуть без обрыва работы, будет подвинут поздно.”

- Attempt 2 started 2026-08-12: re-review after fixing all three blocking findings.

## Round (2026-08-12T06:06:07Z)

## Summary

Most corrections are sound. The threshold, Spark, requested-model, session-reset, and Luna-policy findings are fixed. One blocking contradiction remains around the supposedly trusted task class.

## Findings

1. **blocking — STILL BROKEN (prior finding 1):** The corrected F1 says no production path constructs `RoutingInput` and that trusted classification must be built in Phase 2. But the introduction still claims RuntimeRouter already contains a “доверенный серверный `task_class`”, and F8 still says:

   > “Класс задачи в T1 уже приходит из доверенного серверного entrypoint, а не из текста задания”

   The reviewed code only validates a supplied `RoutingInput.task_class`; it does not establish its provenance, and no production caller supplies it. This contradiction could send Phase 2 toward treating caller-provided classification as trusted. Rewrite the introduction and F8 to say the enum and routing behavior exist, but trusted derivation and production wiring do not.

2. **suggestion — FIXED (prior finding 2):** The threshold evidence is now accurately calibrated. The document records zero confirmed signal→wall outcomes, no calm windows, and disables automatic downgrade by default. The pilot-only conclusion follows from the evidence.

3. **suggestion — FIXED (prior finding 3):** Spark is correctly modeled as a separate candidate requiring `codex_spark` telemetry and eligibility logic, not as a model tier inside the existing primary Codex candidate.

4. **suggestion — FIXED (prior finding 4):** `requested_model` now has a deterministic contract: pass-through under `manifest_default`, server-downgradable under quota mode with an audited reason.

5. **suggestion — FIXED (prior finding 5):** The native-session statement is properly narrowed. It distinguishes same-runtime Codex lossy handoff from the dedicated Claude↔Codex history-transfer paths.

6. **suggestion — FIXED (prior finding 6):** Server policy is explicitly designated as the sole authority, with `base.md` becoming descriptive rather than an independent decision rule.

## Verdict

**NEEDS WORK — 1 blocking contradiction remains.** Remove the stale claims that trusted task-class provenance already exists; after that, the Phase 2 direction is coherent.

## Round 2 outcome and post-ceiling fix (author note)

Round 2 confirmed findings 2–6 as FIXED and left one blocking contradiction: the intro and F8
still described the T1 `task_class` as trusted server-owned provenance, while the corrected F1
said no production path builds `RoutingInput`. The reviewer is right — `runtime_router.py:137-153`
only validates the value against a closed enum.

The prose round ceiling (2) is now spent, so no third round was started. The contradiction was
fixed directly afterwards: the intro now lists what T1 does and does not contain, and F8 states
that the class vocabulary exists while trusted derivation is Phase 2 work.

Verdict of record: **NEEDS WORK** (round 2), with that single finding fixed after the ceiling.
This artifact is deliberately not relabelled APPROVED.
