<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently the schema can already hide tasks and eat answers before implementation starts 🙃 The model is directionally aligned with #418, but Phase 1 is not safe to approve: it has six blocking gaps around source binding, delivery idempotency, authorization, and archived sessions.

Review route: Luna was unavailable in this session; no auxiliary Sol was used.

The artifact was read; for example: “При раскрытии число task cards обязано совпасть с payload count — никаких `slice(0,N)`.”

## Findings

blocking: [research.md:118-129](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:118) — Exact equality of `portfolio_projects.id` and `tm_projects.id` is not proof of linkage: portfolio IDs are freely chosen in [`app/portfolio.py:195-219`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/portfolio.py:195), while technical IDs are created independently in [`app/tm.py:220-234`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/tm.py:220). Backfilling by slug equality can expose an unrelated technical namespace; require owner-scope evidence and leave ambiguous projects unbound.

blocking: [research.md:118-126](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:118) — #418 stores `task_namespace_id` per link, and the current [`link_task()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/portfolio.py:303) permits authorized contributors to create links from their own technical scopes. A portfolio project can therefore contain links from multiple namespaces, while the proposed project-level field rejects namespace mismatches. The `orchestra` zero-link measurement does not prove other projects are homogeneous; migration must inventory and preserve mixed-link states.

blocking: [research.md:200-213](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:200) — The “same deterministic receipt can be retried” claim fails when target lifecycle changes: `target_generation` is included in the payload hash in [`app/message_deliveries.py:126-138`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/message_deliveries.py:126), and a changed hash returns `IDEMPOTENCY_CONFLICT` at lines 151–154. The plan must freeze the accepted target tuple for retries or define a safe generation-update protocol.

blocking: [research.md:196-208](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:196) — “Dashboard operator passes cookie-auth” is incompatible with the current route: [`_actor()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/routes/portfolio.py:67) requires `x-orchestra-session-id`, while the browser API helper does not send it. If the route is changed to accept cookies, the mutation also needs the existing CSRF convention; otherwise the answer endpoint is either unusable or unsafe.

blocking: [research.md:200-208](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:200) — `resolve_wait` is currently a synchronous route using synchronous `_call()` in [`app/routes/portfolio.py:87-94,219-225`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/routes/portfolio.py:87), but `accept_message_delivery()` is async and wakes an event-loop task. Phase 2 must explicitly convert the route/helper to an awaited path; otherwise the receipt flow can be dropped or run on the wrong loop.

blocking: [research.md:202-218](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:202) — The archived-target guarantee is not established for the direct service path. Normal ingress performs an archived check in [`app/routes/sessions.py:790-821`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/routes/sessions.py:790), but `accept_message_delivery()` only records supplied IDs, and cached sessions can pass [`preflight_message_delivery()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/manager.py:1157) without a DB status check. Also, the open wait FK can prevent deleting an archived opener because [`portfolio_waits.opened_by_session_id`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/db.py:558) has no delete action.

suggestion: [research.md:196-208](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:196) — Making `response` mandatory for `WaitClose` breaks the existing `project_wait(resolve|cancel)` contract: [`mcp_stdio.py:2847-2879`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/mcp_stdio.py:2847) sends `{}`, and both routes share the same request model. Use separate resolve/cancel models or preserve agent-side close without a user response.

suggestion: [research.md:120-135](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:120) — The storage model has no defined write path for `stage_label`: current `TaskLinkCreate` only accepts task identity, and `task_update()` only exposes `portfolio_project`. Define the orchestrator-only assignment/reorder/rename API, normalize case/whitespace, reject labels absent from the order, and specify whether sub-orchestrators may mutate them.

suggestion: [research.md:151-165,260-264](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:151) — Lazy queue disclosure is not compatible with the current 15-second loader: [`PortfolioPanel.load()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/static/js/app.js:3694) replaces the panel and loses expansion state on every refresh. Preserve disclosure state or pause refresh while the user inspects the 96 queued tasks.

suggestion: [research.md:246-258](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:246) — “Additive migration” needs an explicit `_migrate()` path. The live schema is created with `CREATE TABLE IF NOT EXISTS` in [`app/db.py:482-489`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/db.py:482), while existing-column changes happen in `_migrate()` at [`app/db.py:963-969`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/db.py:963). Specify defaults for existing waits and an idempotent backfill.

## Verdict

**Needs work before Phase 2.** The proposed model can satisfy the fixed decisions, but the current research does not yet prove safe namespace binding or lossless wait-answer delivery. No files were edited.

Пока это «дорога по этапам», где сам мост к техническим задачам и ответам ещё нарисован пунктиром.

## Round (2026-08-31T12:24:40Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Round 2

Apparently the obvious leaks are patched, leaving one fresh trap in the delivery contract 😏 `git diff -- docs/tasks/425/research.md` is empty because the file is untracked (`??`); I reviewed the current artifact and rechecked the named owners. Round 1 remains counted as the completed Luna review.

## Findings

Round-1 dispositions:

- **FIXED — slug-only backfill.** [`research.md:124-126`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:124) now requires both project-ID equality and exact active-owner scope equality; unmatched or ambiguous projects remain unbound.

- **FIXED — mixed namespaces.** [`research.md:129-156`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:129) preserves explicit links independently and unions them with primary-source tasks. This matches the existing per-link namespace stored in [`app/db.py:505-513`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/db.py:505).

- **FIXED — crash-window payload-hash conflict.** [`research.md:226-236`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:226) now reuses the persisted delivery tuple/generation, addressing the existing hash conflict at [`app/message_deliveries.py:126-154`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/message_deliveries.py:126).

- **FIXED — cookie/CSRF branch.** [`research.md:216-218`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:216) explicitly uses the existing [`require_operator_csrf()`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/app/auth.py:76) contract.

- **FIXED — async route boundary.** [`research.md:219-220`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:219) now requires an async resolve route and awaited `accept_message_delivery()`.

- **FIXED — initial archived-target check.** [`research.md:224-225`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:224) requires durable DB status validation before manager-cache/preflight lookup, matching the normal ingress guard in [`app/routes/sessions.py:790-821`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/routes/sessions.py:790).

blocking: [`research.md:127-130`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:127) makes future source binding owner-only but does not require the bound namespace to equal the active owner’s technical scope. Portfolio ownership alone is insufficient: current technical linking enforces caller-scope ownership through [`app/portfolio.py:285-300`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/portfolio.py:285). Without the same guard on primary-source binding, an owner can expose an unrelated namespace’s entire task set.

blocking: [`research.md:232-241`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/docs/tasks/425/research.md:232) fixes hash conflicts but leaves a stale-generation delivery unrecoverable. The existing runner rejects a changed generation at [`app/manager.py:1139-1149`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/roadmap-board/app/manager.py:1139) and records `FAILED_BEFORE_SUBMIT`; the plan has already resolved the wait after receipt acceptance. Reusing the frozen tuple repeats the failure, while changing it conflicts with the deterministic receipt. Define a retry/reopen state or keep the wait unresolved when submission fails.

## Verdict

**Needs work; not approved for Phase 2.** All six round-1 blockers are addressed in the research text, and stage limits, mixed-link visibility, agent compatibility, CSRF, async handling, and initial archive checks are now specified. The two remaining blockers are primary-source authorization and recovery after a target-generation/archive race.

Карта уже похожа на дорогу, но один шлагбаум всё ещё закрывается сразу после выезда курьера.
