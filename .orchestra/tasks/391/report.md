# #391 — разбор сохранённых worker branches

Дата: 24.08.2026. Кодовые ветки не вливались. В main перенесены только проверенные Markdown
research/plan/review/blocker artifacts; raw evidence, intentionally RED tests and stale production
code остались на исходных refs/worktrees.

## Что перенесено

Commit 1b68b58a:

- #248: plan, known limitations, post-restart acceptance, T2/T3 Opus reviews;
- #261: research, plan and three plan/research reviews;
- #303: three implementation stop/blocker notes;
- #382: research, approved plan and research/plan reviews;
- personal memory: bench-grok, fix-secret-mask-escaped, review248-t3.

Secret-form scan clean. Changed paths are Markdown only.

Ранее в этой cleanup chain merged:

- #337 research + independent review;
- #314 independent review;
- #340 independent review.

## Code branches: decision

### Complete / archive, do not merge old branch

| Worker/task | Evidence | Action |
|---|---|---|
| feat-runtime-switch / #290 | Task done; main report records replay onto current main and 586 focused tests. Old branch has 11 historical commits and stale tree deltas. | Prove current behavioral symbols/tests, then reconcile/archive branch; no code port. |
| feat-hot-reload / #230 | Markdown is byte-identical to main; implementation is live and was exercised through multiple successful handoffs/restarts; #379 closed later exit/FD gaps. | Task marked done; archive old branch after descendant/content proof. |
| fix-spawn-delivery + impl311-t1/t2 / #311 | Task done; main contains initial_deliveries and later #381 boundary/retry fixes; task docs are already identical. | Treat child commits as stale/phantom until exact descendant proof, then archive; no merge. |
| feat-quota-front / #329 | Task done. Branch assumes quota_controller ownership that #343 later removed entirely. | Superseded: discard code branch, keep report already in main. |
| quota-config / #356 | All three commits were patch-equivalent to main by git cherry; branch reset and worker archived. | Done. |

### Superseded / discard after preserving refs

| Worker/task | Why not merge | Action |
|---|---|---|
| plan-quota-controller + impl291-* / #291 | Adaptive controller was replaced by user-approved single linear quota gate #343. Branch plan even regresses telemetry threshold 90% → 80%. T4 has dirty backtest/script. | Preserve refs/raw evidence, discard production code, archive sessions through safe gate. |
| bench-grok accumulated branch | 211-file stale aggregate across many already-merged tasks. Latest #261 research/plan is now preserved; no reviewed implementation. | Do not merge branch; reopen only chosen feature on fresh main. |
| research-gemini accumulated branch | 226-file stale aggregate. #249 research/plan already identical in main. | Do not merge; archive and respawn fresh if Gemini is approved later. |
| fix-secret-mask-escaped / #382 | Task explicitly cancelled. Branch contains research/approved plan plus intentionally RED future tests, no app implementation. Markdown now preserved. | Keep cancelled; do not merge RED tests. Archive only after explicit discard of test branch. |

### Real work worth a fresh continuation

| Priority | Task | Current blocker | Proposed next step |
|---:|---|---|---|
| 1 | #248 task lifecycle/merge finalization | Final Opus review: 3 blockers — reservation wedge on UNKNOWN, no restart trailer reconciliation, one previously green MCP test made red. Current main has since changed materially in #380/#383/#384/#386. | Fresh-main read-only reproduction of the three blockers. Port only still-live failures into a new focused ticket; do not cherry-pick old production diff. |
| 2 | #303 venv authority boundary | Provider delegation feasibility is explicitly unproven; C/D implementation is stopped. Requires real authenticated Codex/Claude/Grok/OpenCode probes and authorization. | Ask for a bounded provider-feasibility window. If any runtime cannot delegate model-selected operations, revisit architecture; no partial enablement. |
| 3 | #256 server-owned cross-runtime review gate | Branch has 24 commits, app/review_gate not in main, final independent review remained REJECT/post-ceiling mechanical. docs/tasks/256 namespace also collides with laptop knowledge research. | Do not merge. Reframe under a fresh task ID after task-identity work #388; first decide if current Opus-worker/Sol-review routing already gives enough independence. |
| 4 | #261 Grok X background retriever | Research says PROCEED narrow, but all plan reviews end NEEDS WORK. | Revise plan on fresh main before any code. Optional feature, not platform blocker. |
| 5 | #337 Agent Reach | Research + review are merged; review reports NEEDS WORK. | Address review findings only if platform-access work is prioritized; no hidden code WIP. |

### Preserve blocked

- impl-venv-boundary #303: real unmerged code and blocker notes; no merge before feasibility.
- feat-review-council #256 and children: real code, rejected review; preserve.
- research-taskmanager #248 and children: real code/probes with blockers; preserve for fresh audit.
- impl291-t4: two uncommitted evidence files; reversible stop only.
- review-337-opus: squash ancestry makes worker_wip look unmerged even though docs tree is in main;
  leave stopped until platform reconciliation, no force kill.

## Cleanup state

- 15 clean/superseded workers archived.
- Four documentation merge operations completed before this report.
- No active background jobs.
- One system worker retained: back.
- Remaining sessions are stopped/preserved because their branches contain real or dirty WIP.
- Task #356 corrected to done; task #230 corrected to done.

## Recommended user decision

Proceed with #248 fresh-main blocker audit first. It touches a live correctness seam and can be
falsified without provider calls. Keep #303 blocked until an explicitly authorized provider probe
window. Defer #256/#261/#337. Mark #291/#329/#382 branches discardable and archive them only after
the safe lifecycle gate can prove no unique required artifact remains.
