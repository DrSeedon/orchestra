## Summary

The plan is directionally coherent and references real seams: `current_quota_observation`, `_auto_switch_before_delivery`, `AgentSession.send`, `_pending_messages`, `handle_turn_end`, `change_model`, `runtime_handoff`, `codex_review`, and replayable `bg_jobs.triggering` all exist where claimed.

The delivery state machine is conservative around ambiguous submission, Claude-only routing is explicitly preserved, and operator-only mutation is correctly separated from `INTERNAL_TOKEN`. However, two crash windows can lose work or duplicate review side effects, and policy activation is not atomic with in-flight routing decisions.

## Findings

- **blocking:** Persist the continuation intent before changing runtime. The stated failover order is: “**только при idle/waiting вызывает существующий `change_model()`**” and only afterward “начинает новый continuation message”. A crash after `change_model()` clears the native session but before the linked continuation row is committed loses the continuation entirely. Define a durable failover/control state machine such as `planned -> switched -> dispatching`, with the linked continuation delivery and decision committed before `change_model()`. Recovery must resume the state machine without recreating the original prompt or repeating a switch already recorded as complete.

- **blocking:** Define the review process-to-delivery crash contract before replacing `codex_review`. The plan says the background job stores its native review session and that completion uses durable ingress, but it does not say what happens if Codex/Claude finishes—possibly after executing allowed tools—and the process crashes before the completion delivery row is created. Re-running the review can duplicate external side effects; not re-running it can lose the verdict. Persist a stable review attempt and completion `delivery_id` before launching the subprocess, capture the artifact atomically, and recover a finished artifact into that same delivery without rerunning the reviewer. Explicitly prohibit generic `bg_jobs.triggering -> active` recovery for review attempts.

- **suggestion:** Make policy PUT linearizable with admission. Reading a policy “на каждом новом decision” plus locking only the quota bucket/window allows this race: admission reads revision N, operator PUT of N+1 returns successfully, then the old decision commits and starts a backend under N. This weakens hot activation and rollback. Hold a shared policy/admission lock through decision commit or transactionally verify the policy revision immediately before committing admission; on mismatch, recompute. State whether PUT waits for admitted decisions or merely guarantees that no older revision may commit after it returns.

- **suggestion:** Specify durable review provenance independently of the requesting session’s current runtime. “provenance автора берётся из requesting session и связанного delivery/task” is ambiguous after a session has switched runtime or when the artifact was implemented across multiple deliveries. Persist `implementation_runtime` against the logical work/artifact at implementation time, define how mixed-runtime authorship is represented, and make review routing consume that immutable record. Otherwise identical artifacts may choose different reviewers depending on when `review_artifact` is called.

- **suggestion:** Explicitly retire or redefine `/api/usage/readiness`. It currently accepts an exact `model` and calls `quota_gate.get_worker_admission`, so deleting `quota_gate.py` without naming the endpoint’s replacement either breaks it or leaves a second model-specific admission owner. The plan should require removal, or redefine it as a read-only projection of `RuntimeRouter` using trusted server class/provenance and the active policy revision.

- **suggestion:** Correct the rollout dependency order. T1 says final #186 is an external prerequisite because #187 imports `weekly_runway`, yet rollout step 9 says “После merge финального #186” after the one restart in step 5. The deployable code cannot safely import a module merged only after that restart. Require #186 code to be merged and deployed before the coordinated restart; only its measured policy values may be deferred to the hot PUT.

## Verdict

Changes requested. The central routing and delivery design is viable, including Claude-only operation, but the failover and review crash windows must be closed before implementation because they can respectively lose work and duplicate external side effects. The policy/admission revision race and remaining readiness endpoint also need explicit ownership rules for deterministic hot rollout.

## Round (2026-08-11T10:53:12Z)

## Summary

Prior findings:

1. **FIXED** — continuation and failover state commit before model switch; recovery checks persisted target model.
2. **FIXED** — review attempt/completion identity precede subprocess launch; atomic artifact recovery does not rerun ambiguous attempts.
3. **FIXED** — policy PUT and admission share an ordered lock, with revision recheck before commit.
4. **FIXED** — immutable per-logical-work runtime sets handle single, mixed, and unknown provenance deterministically.
5. **FIXED** — exact-model readiness and MCP preflight are explicitly removed.
6. **FIXED** — #186 code is deployed before restart; only measured parameters activate later.

## Findings

- **blocking:** The operator window still relies on an unenforced instruction: “**между merge и restart не принимать agent turns/reconnect**”. Checking for zero running work immediately beforehand does not prevent TG ingress, dashboard sends, timers, or reconnects during the two merges. A turn accepted in that window can be interrupted by restart or encounter files from the new MCP contract while the old FastAPI process remains loaded. Add a server-enforced maintenance/admission gate activated before the quiescence check, or stop ingress/service before changing the live checkout. The gate must reject or durably queue new turns, spawns, reviews, and background wake dispatches until post-restart verification.

- **suggestion:** Make the mixed-version guard bidirectional and server-enforced. The plan explicitly covers new MCP → old server, but a client-side capability probe cannot constrain an already-running or stale MCP against the new server. Require a routing contract version on every mutating workload request, and have the server reject missing or mismatched versions before any side effect. Test both new-client/old-server and old-client/new-server directions.

## Verdict

Changes requested. The six previous correctness issues are fixed, but the rollout still has an unguarded live-ingress window that can interrupt or lose accepted work. With an enforced maintenance gate and bidirectional contract validation, the plan is ready for implementation.

## Author resolution after the round-2 ceiling

The final blocking finding is **ACKNOWLEDGED AND FIXED after review**. The plan no longer changes
the live checkout while Orchestra accepts ingress: the operator stops the service, verifies the
stopped process/port and DB state, applies the prepared #186/#187 commits while ingress is down,
then starts the service once. If a turn appeared before stop, deployment is aborted before any
checkout change.

The suggestion is also accepted: every workload HTTP mutation carries `routing-v1`; the new
server rejects absent/mismatched contracts before side effects, while the new client refuses an
old server during capability probe. Both version directions are acceptance-tested.

No third Codex round was run: `codex-debate` caps prose at two. Therefore the preserved Codex
verdict above remains **Changes requested**, not APPROVED; these final two changes are author
self-resolution at the mandatory ceiling.
