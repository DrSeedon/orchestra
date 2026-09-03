<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The RED part is refreshingly honest; the sandbox and acceptance gates are not yet safe enough to spend a paid key on it 🧪

## Summary

All four named tests are committed byte-identically in RED commit `cbb7ccea…` and currently fail after collection on their own missing behavior. The protocol hash also matches.

The plan is not ready for implementation: isolation, paid-key handling, replay binding, and several acceptance checks can pass vacuously.

## Findings

### [blocking] Establish a real controller/tool sandbox boundary

`docs/tasks/422/plan.md:20-23`; `docs/tasks/422/protocol.json:48-57`

`AgentLoop` dispatches builtin tools in-process (`app/harness/loop.py:286-300`), while `bash` subprocesses inherit the controller’s network namespace (`app/harness/tools.py:120-135`) and OpenRouter requests run in that same process (`app/harness/llm.py:264-274`). Wrapping the whole runner in `bwrap --unshare-net` blocks OpenRouter; leaving it outside leaves tool-side network access unrestricted. The plan needs an explicit process/IPC or per-tool isolation design.

### [blocking] Make the key boundary compatible with the current Harness API

`docs/tasks/422/plan.md:20-23`

`HarnessBackend.connect()` reads `OPENROUTER_API_KEY` from `os.environ` (`app/backend_harness.py:170-187`), and the builtin shell inherits that environment. Setting the key for the existing backend exposes it to tools; clearing it makes backend connection fail. The runner must specify and test a controller-only key injection path.

### [blocking] Bind T1 to the complete catalog safety invariant

`docs/tasks/422/plan.md:60-69`; `docs/tasks/422/acceptance/test_free_lane_422.py:55-67`

T1 checks only two IDs, their cache presence, and their flags. It never rejects an enabled paid/unsuffixed Harness route or verifies text input/output, tool support, and availability for every registered route. An extra unsafe route can remain enabled while T1 passes.

### [blocking] Tie T2 to the turn created by this run

`docs/tasks/422/plan.md:74-85`; `docs/tasks/422/acceptance/test_free_lane_422.py:73-100`

The test reads the latest durable canary and latest successful `turn_usage` row but has no run nonce, receipt linkage, freshness check, or terminal-status assertion. A previous successful canary can satisfy T2 without a new real turn, and a failed new turn can be masked by old logs.

### [blocking] Validate actual N=30 selection and two-route execution

`docs/tasks/422/protocol.json:11-35`; `docs/tasks/422/acceptance/test_free_lane_422.py:110-131`

T3 checks counts and `:free` suffixes only. It does not verify eligibility, cutoff, precedence, seed, transport-canary survivors, roster hashing, route capabilities, roster membership of each run, or balanced distinct rotation. A fabricated 30-case/60-run summary—even with one route used everywhere—passes.

### [blocking] Enforce false-premise controls, not just labels

`docs/tasks/422/protocol.json:69-78`; `docs/tasks/422/acceptance/test_free_lane_422.py:114-145`

The oracle only counts two `false_premise` booleans. It does not require those cases to be in the high-risk stratum, nor require WIP/STOP outcomes with evidence. Two arbitrary labels attached to successful runs pass.

### [blocking] Make isolation and production safety evidence verifiable

`docs/tasks/422/protocol.json:48-78`; `docs/tasks/422/acceptance/test_free_lane_422.py:131-146`

T3 trusts `isolation_preflight["ok"]` and compares only session counts. It does not validate the five preflight controls, per-run databases/session stores, no remotes or alternates, solution-SHA absence, or unchanged existing logs/KV/tasks. A replay could mutate existing production rows without changing the session count and still pass.

### [blocking] Prevent a no-op replay from passing

`docs/tasks/422/protocol.json:69-78`; `docs/tasks/422/acceptance/test_free_lane_422.py:126-146`

The test accepts 60 records with allowed outcome strings and `http_attempts_total <= 900`; it does not require raw attempt receipts, nonzero inference, retry count enforcement, pilot/full-run evidence, positive-control success, or recomputation of the decision. A fabricated summary with zero HTTP attempts can pass.

### [blocking] Validate T4 content, not headings

`docs/tasks/422/plan.md:109-117`; `docs/tasks/422/acceptance/test_free_lane_422.py:150-164`

T4 checks headings and one KB marker only. Empty or incorrect fractions, failure counts, uncertainty, decision, attempt/429 accounting, manual timing, and report-to-summary evidence can all pass.

### [suggestion] Freeze the population at a timestamp and snapshot it

`docs/tasks/422/protocol.json:3-16`; `docs/tasks/422/plan.md:92-94`

`frozen_on` is only a date, while `completed_through` extends to the end of that UTC day and no corpus manifest/hash is required. The eligible population can therefore differ across runs despite the same protocol hash and seed. Record an exact cutoff and immutable corpus manifest before inference.

## Verdict

The RED oracles themselves are correctly committed and independently red, but the Phase-2 plan is **not ready**. The current acceptance layer can approve a leaked, partial, fabricated, or zero-request replay, and the stated bwrap/controller split is not represented by the existing Harness execution path.

## Round (2026-08-31T07:34:27Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The sandbox now has a respectable floor plan; the receipts are still acting as their own security auditor 🧪

## Summary

The new acceptance file matches RED commit `48096877…` byte-for-byte, the protocol hash matches, and all four tests collect before failing on their own missing artifact.

Round-1 status:

- Controller/tool boundary — **FIXED**
- Controller-only key path — **FIXED**
- T1 catalog safety coverage — **FIXED**
- T2 stale-canary protection — **STILL BROKEN**
- T3 selection/roster/rotation checks — **FIXED**, with a new strata-label gap below
- False-premise controls — **FIXED**
- Isolation and production-state proof — **STILL BROKEN**
- No-op/positive-control proof — **STILL BROKEN**
- T4 heading-only acceptance — **FIXED**, with raw-metric binding gap below
- Frozen population cutoff — **FIXED**

Revised artifact quote: “A fabricated or no-op summary cannot pass.” — `docs/tasks/422/plan.md:112`

## Findings

### blocking — STILL BROKEN: T2 is not tied to the current invocation

`docs/tasks/422/acceptance/test_free_lane_422.py:118-168`

A previously valid `canary.json` plus its matching database rows still satisfies every assertion; there is no marker supplied by the current T2 operation proving that `started_at` follows this run’s start. The attempt delta is also global: `openrouter_attempts` contains only `id`, timestamp, day, and status (`app/db.py:562-567`), so it is not bound to this canary turn. An old receipt or concurrent request can therefore satisfy the “new run, one attempt” claim.

### blocking — STILL BROKEN: isolation remains self-attested

`docs/tasks/422/acceptance/test_free_lane_422.py:272-326`; `docs/tasks/422/preflight.md:47-64`

The test trusts boolean controls and before/after production-state objects supplied by generated JSON. It does not independently establish that the actual run used bwrap, that the production database and environment were inaccessible, or that existing production rows were unchanged. The preflight evidence only demonstrates network denial for the broad `--ro-bind / /` probe, which the plan itself says must not be used by the runner.

### blocking — STILL BROKEN: controls and raw attempts can still be fabricated

`docs/tasks/422/acceptance/test_free_lane_422.py:203-212`, `:291-329`

`red_ref`, `solution_ref`, positive/negative-control results, no-op status, and raw receipt fields are accepted as self-reported values. A runner that performs no inference can create 69 JSON receipts with `http_attempts >= 1`, set the control booleans to the expected values, and satisfy the oracle without contacting OpenRouter.

### blocking — NEW BLOCKER: outcomes are not bound to raw receipts

`docs/tasks/422/acceptance/test_free_lane_422.py:291-321`, `:352-362`

`check_run()` validates route, attempt count, and isolation metadata, but never compares `run["outcome"]` or `summary["metrics"]` with an outcome recorded in the raw receipt. A real failed response can therefore be labeled `success`, and T4 only propagates that same label because it cross-checks summary against report metrics rather than recomputing from raw results.

### blocking — NEW BLOCKER: ticket strata are not cross-checked

`docs/tasks/422/acceptance/test_free_lane_422.py:214-234`, `:341-350`

The seeded IDs are selected from `population_cases`, but the test never asserts that each corpus ticket’s `stratum` equals the selected population case’s stratum. Relabeling six selected cases between strata while preserving the 6×5 counts passes and changes the weighted estimate; the false-premise location check is vulnerable to the same mismatch.

## Verdict

**Not ready for implementation.** The architectural controller/tool split and most structural checks are fixed, but stale T2 evidence, self-authored isolation/control receipts, unbound outcomes, and unchecked strata labels still permit a false or unsafe measurement. Сейчас это охранник, который принимает пропуск, потому что сам пропуск написал «я настоящий».

## Round (2026-08-31T07:44:11Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The final gate is much less decorative now; three security gaps still keep the paid-key run behind the velvet rope 🧪

## Summary

The acceptance file and protocol match RED commit `248d913d…`; all four tests collect and fail on their own seams. `_independent_bwrap_probe()` independently returned all six expected `True` controls.

Round-2 status:

- T2 stale canary — **FIXED** via externally supplied nonce and not-before timestamp.
- Isolation self-attestation — **STILL BROKEN**.
- No-op/control self-attestation — **STILL BROKEN**.
- Raw outcome/metric binding — **FIXED**.
- Corpus stratum binding — **FIXED**.

Revised artifact quote: “No criterion is relaxed after a result. A stop is reported as premise/protocol failure, not converted into a smaller or differently stratified benchmark.” — `docs/tasks/422/plan.md:142-143`

## Findings

### blocking — STILL BROKEN: the guard signature has no trusted key

`docs/tasks/422/acceptance/test_free_lane_422.py:84-92`

The verifier reads `public_key_b64` from the same `guard-receipt.json` that it verifies. Any process able to write the receipt can generate its own Ed25519 keypair and sign fabricated control, outcome, isolation, and production-state data. The supervisor’s ephemeral private key being outside model tools does not establish provenance without an out-of-band trusted public key or an independently trusted verifier.

### blocking — NEW BLOCKER: the independent probe is not the frozen bwrap policy

`docs/tasks/422/protocol.json:64-82`; `docs/tasks/422/acceptance/test_free_lane_422.py:95-120`

The protocol template includes the venv bind and no `HOME`/`PATH` `--setenv` entries, while the acceptance helper builds a different argv and never derives or hashes it from the template. A runner can therefore use a weaker policy while the independent probe still passes; the guard policy hash only compares self-authored values.

### blocking — NEW BLOCKER: the environment allowlist is not enforced

`docs/tasks/422/protocol.json:54`; `docs/tasks/422/acceptance/test_free_lane_422.py:402-412`

The protocol requires an exact environment allowlist, but raw receipts only reject `OPENROUTER_API_KEY`, `OPENROUTER_KEY`, and `INTERNAL_TOKEN`. Variables such as `HTTPS_PROXY`, `HTTP_PROXY`, or other credentials can remain tool-visible without failing acceptance. The independent probe checks only its own clean environment, not the actual replay tools.

## Verdict

**Blocked at the final round ceiling; escalate these three blockers.** The plan is otherwise structurally sound, but paid-key inference must not start until guard provenance, exact bwrap-policy binding, and the complete tool environment allowlist are independently enforced.

Пока охранник сверяет паспорт с подписью, которую паспорт сам себе поставил.
