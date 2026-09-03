<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Because apparently the gate can contradict its schema before it exists. 🙃 Review of plan #462 against frozen RED `f00ea8b5` found 7 blocking issues and 1 suggestion; no files were edited. The rollout order is otherwise correctly staged: live calls precede marker activation.

> “No line-count threshold is added. The measured threshold is **1 production path**; a one-line identity/authorization change can carry the same consequence as a large diff.”

## Findings (blocking/suggestion/question)

blocking: [P1] `.orchestra/tasks/462/plan.md:54` — The plan separates `coverage_outcome` from execution `status`, but the frozen oracle asserts `status="unavailable"` and `status="skipped"` while the existing schema permits neither. → Define the status contract and update the oracle to assert coverage outcomes separately.

blocking: [P1] `.orchestra/tasks/462/plan.md:39` — Additive columns are planned, but no `init_db` migration for existing #436 tables is specified. `CREATE TABLE IF NOT EXISTS` will not alter the live schema, so the first extended insert can fail with `no column named ...`. → Add an idempotent runtime migration and test against a pre-existing #436 schema.

blocking: [P1] `.orchestra/tasks/462/plan.md:33` — T1 only fakes job creation and inspects the reserved row; it never proves the finalizer publishes `coverage_outcome=reviewed`, that Codex receives the exact pinned diff, or that admission accepts only that receipt. An implementation can hash/enqueue the wrong review and still pass. → Add completion/finalization and exact-command/admission assertions, including stale and foreign near-misses.

blocking: [P1] `.orchestra/tasks/462/plan.md:70` — “Proof-bound orchestrator” is undefined, while `app/mcp_stdio.py:47` defaults missing `ORCHESTRA_ROLE` to `orchestrator`; the T2 fake API also ignores `target_worker`. A worker with missing role configuration could self-issue a skip. → Fail closed on missing role and resolve `target_worker` through the existing authenticated session context.

blocking: [P1] `.orchestra/tasks/462/plan.md:76` — T2 does not assert `coverage_outcome="unavailable"` or test missing-binary, failed, interrupted, or timed-out receipts. A receipt could have `status="unavailable"` but `coverage_outcome="reviewed"` and authorize a merge. → Add explicit non-qualification assertions through admission.

blocking: [P1] `.orchestra/tasks/462/plan.md:80` — T3 has no positive allow-path. An implementation that always blocks every `app/**` and `scripts/**` merge passes all frozen T3 tests, leaving production merges permanently unusable. → Add exact reviewed/skip acceptance plus stale, foreign, and mismatched snapshot cases.

blocking: [P1] `.orchestra/tasks/462/plan.md:82` — The plan checks activation at admission but does not define pending operations admitted while the marker is absent. Such an operation could execute after T4 activation using a pinned `not_active` decision, contradicting “all later production merges are enforced.” → Define and test the activation boundary: drain, reject, or revalidate pending operations.

suggestion: [P2] `.orchestra/tasks/462/plan.md:67` — The empty-`receipt_id` skip path has no idempotency key. Retrying after a transport timeout can create duplicate skip receipts because the existing idempotency mechanism keys on receipt ID. → Define deterministic deduplication for the target snapshot and test concurrent/replayed calls.

## Verdict

**Overall Correctness:** ❌ Incorrect  
**Confidence:** 0.98

The plan is not ready for Phase 2 approval until the schema/status contract, authorization, positive admission path, and rollout boundary are specified and covered. Right now it is a bouncer with a checklist that cannot decide whether “unavailable” means inside or outside.

## Round (2026-09-03T11:44:21Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Follow-up review against `b4712a67db0b`: prior findings #2, #3, #6, #7, and #8 are fixed. #1 remains broken; #4 and #5 are only partially covered by the frozen oracle. T4 rollout ordering is correct, with no prompt-before-live violation found.

> “The marker both delivers the requirement and activates enforcement; no agent is required to call unavailable code.”

## Findings (blocking/suggestion/question)

blocking: [P1] `.orchestra/tasks/462/plan.md:54-56` / `tests/test_review_coverage_gate_462.py:463` — The plan correctly requires skip receipts to use `status=completed`, but the frozen T2 test still asserts `status=="skipped"`. A conforming implementation therefore cannot pass the oracle. → Change the assertion to `status=="completed"` while retaining `coverage_outcome=="skipped"`.

blocking: [P1] `.orchestra/tasks/462/plan.md:56,81` / `tests/test_review_coverage_gate_462.py:616-630` — The plan says only a typed machine-unavailable result qualifies, but the T3 allowed fixture uses `status="failed"`, `coverage_outcome="unavailable"`, an empty `failure_code`, and `return_code=0`. The oracle therefore permits arbitrary/misclassified unavailable receipts. → Use the real quota/binary failure codes and add a wrong-code negative case.

blocking: [P1] `.orchestra/tasks/462/plan.md:73` / `tests/test_review_coverage_gate_462.py:515-524` — The authority test proves proof and replay, but never asserts that the receipt is bound to the server-resolved `target_worker`; both sessions point to the same repository and only row count/outcome are checked. An endpoint that records the caller’s session instead of the target worker would pass. → Assert `session_id`, `worker_name`, target/head, and snapshot fields from the stored receipt.

## Verdict

**Overall Correctness:** ❌ Incorrect  
**Confidence:** 0.99

Not ready for approval until the stale status assertion and the two incomplete authority/unavailability oracle checks are corrected. Сейчас шлагбаум почти собран, но один тест всё ещё требует назвать закрытую дверь `skipped`.

## Round (2026-09-03T11:47:16Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Ну конечно: раунд 2 починен, а план всё ещё спорит сам с собой. 🙃 Все три заявленных исправления в oracle `41456f2afbab` подтверждены: status contract, typed unavailable codes, and server-side target binding. Остались два блокирующих противоречия.

## Findings (blocking/suggestion/question)

blocking: [P1] `.orchestra/tasks/462/plan.md:9` — The non-negotiable trigger still names only `app/**`, while the production boundary and T3 explicitly require `app/**` **or** `scripts/**`. An implementation following the “non-negotiable” section can omit operational `scripts/**` changes and reopen the stated coverage hole. → Make the authoritative trigger wording include both roots.

blocking: [P1] `.orchestra/tasks/462/plan.md:5` — The outcome says admission requires either a completed review or an authorized skip, but T3 says typed machine-unavailable receipts also allow admission; line 11 likewise says unavailability does not block. This leaves the legal quota/binary-outage path contradictory even though the detailed status fields are now correct. → Add machine-unavailable as an explicit third qualifying outcome in the top-level contract.

## Verdict

**Overall Correctness:** ❌ Incorrect  
**Confidence:** 0.99

Round 2 fixes are accepted, but the plan is not clean until the production trigger and unavailable-admission contract have one authoritative wording.

Exact plan quote: “Thus the activation boundary is the first execution-side check that sees the marker, not merely operation creation; no pre-activation queue needs a manual drain.”

Гейт уже различает два кода отказа; теперь бы самому плану научиться различать `app` и `scripts`.
