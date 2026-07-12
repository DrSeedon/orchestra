# Retro — rag-orchestra (RAG semantic memory port)

## Metrics
- Tool calls: ~35 | Retries: 1 (dep-resolution after pillow relax) | Turns: multi (research→plan→impl)
- Files: 14 (+2321/−7) | Codex: unavailable (platform bug) → self-review substituted
- Tests: 16 rag pass / 19 skip; 2 pre-existing failures found (not mine)
- User corrections this task: 2 (mid-flight scope additions during Phase 2)

## What went wrong (signal → root cause)
- **Signal:** `uv run pytest` failed with `ModuleNotFoundError: sqlite_vec` on first test run.
  **Root cause:** I wrote `import sqlite_vec` at module top of `app/rag.py`, but it's an OPTIONAL
  dep — the module must import even when RAG deps absent. Ported kesha's top-level import verbatim
  without adapting to Orchestra's optional-dep requirement (T7 constraint I set myself in the plan).
  **Category:** correctness. Fixed by lazy import; caught by test, pre-commit. Lesson: when porting
  code into an OPTIONAL feature, audit every top-level import for the "works without deps" guarantee
  BEFORE running — don't rediscover it via ImportError.
- **Signal:** `uv sync --extra rag` → "requirements unsatisfiable" (fastembed→pillow>=12 vs base
  pillow<12). **Root cause:** didn't check the base pillow pin against fastembed's transitive
  requirement before adding the optional dep. **Category:** process. Fixed by relaxing pillow<12→<13
  (safe — pillow used only for diff_image, stable API). Lesson: adding a heavy optional dep → check
  its transitive constraints against existing pins in the SAME step, not after a failed resolve.
- **Signal:** 2 test files failed (`test_default_pipeline`, `test_routes_surface`).
  **Root cause:** NOT mine — verified pre-existing on clean HEAD via `git stash`. Characterization
  snapshots already stale vs pipeline.yaml/routes. **Category:** scope (correctly diagnosed + didn't
  "fix" the unrelated stale test — surgical). Good call to stash-verify before assuming I broke them.

## What went well (keep doing)
- **Stash-verify before blaming my change:** `git stash` → re-run → confirmed the 2 failures are
  pre-existing, not mine. Prevented a wrong "I broke tests" panic-fix on unrelated code.
- **Measured before deciding:** the whole log-segmentation (what to index) rests on real `orchestra.db`
  distribution queries, not guesses — refuted the "80% ок/го" hypothesis and found the `[from:]` gold.
- **Fail-loud verified explicitly:** ran an import test proving `RagMemory()` raises without deps
  (not silent) and `app.main` boots — the two guarantees that matter for an optional feature.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)
| Target | Change | Evidence | Status |
|---|---|---|---|
| `tests/test_default_pipeline.py` | Update hardcoded `modules == [...]` characterization to match current pipeline.yaml (5 modules, not 2) | pre-existing failure on clean HEAD, n=1 | logged, not promoted |

## Written to worker memory (Tier-1 — applied)
- When porting code into an OPTIONAL (`[extra]`) feature: audit top-level imports for the
  "imports without the extra installed" guarantee, and check the extra's transitive pins against
  existing base pins — both BEFORE the first test/sync run, not after the failure.
