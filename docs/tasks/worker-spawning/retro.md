# Retro — worker-spawning (research + R1/R2 impl)

## Metrics
- Tool calls: ~45 | Retries: 2 (git-worktree /tmp test wrong base-branch `main`→`master`; route-test `409` unrouted-child) | Turns: many | Files: 5 (+123/−0 net)
- Codex: research-phase review returned 4 confidently-wrong findings (F3 absolute, "any worker" scope, depth=5, built-in-cheaper); impl-phase Codex skipped by orchestrator | Tests: 9 new pass; 3 pre-existing fail (unrelated, verified via git stash) | User corrections: 1 (orchestrator: "skip Codex for impl")

## What went wrong (signal → root cause)
- **Signal:** Codex overturned 4 findings I marked CONFIRMED in research.md. **Root cause:** the web-research subagent's "depth=5 / nested since v2.1.172" claim was accepted without me verifying against the installed CLI; and I conflated "worktree doesn't physically nest" (true, tested) with "no collision possible" (false — `wt_path.exists()` raises). Over-generalized from one evidence type. **Category:** correctness.
- **Signal:** route test failed `409 role 'worker' must specify child role`. **Root cause:** I wrote the test before recalling my OWN research finding F1 (worker parent + unrouted child is blocked by `validate_spawn`, `allow_unrouted_workers=False`). Didn't apply my own research to the test setup. **Category:** process.
- **Signal:** /tmp worktree experiment failed first run (`invalid reference: main`). **Root cause:** assumed default branch `main`, repo initialized `master`. Cheap 1-retry fix, minor. **Category:** process.

## What went well (keep doing)
- **Signal-confirmed:** running Codex on the research doc BEFORE impl caught 4 overstated claims — cheap, and they'd have become wrong architectural inputs. Delegating DB analysis + web-research to subagents kept my context lean enough to do careful code reads.
- **Signal-confirmed:** `git stash` to prove the 3 test failures are pre-existing (not mine) — avoided both false-blame and false-innocence.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)
| Target | Change | Evidence | Status |
|---|---|---|---|
| pipelines/.../modules/research-method.md | "External facts from a subagent's web search are UNCERTAIN until cross-checked against a primary source or local artifact (installed CLI/docs)" | n=1: depth=5 claim survived to CONFIRMED until Codex caught it | logged, not promoted |

## Written to worker memory (Tier-1 — applied)
- When writing tests that spawn child workers, set explicit `role` — worker-parent + unrouted child is blocked by `validate_spawn` (allow_unrouted_workers=False).
- Don't mark a web-research-subagent's version/number claim as CONFIRMED without a second primary source; downgrade to UNCERTAIN and flag the conflict.
