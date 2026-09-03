## Summary
🚬 Nice, we found a real mismatch: the plan’s semantics are more advanced than today’s payload, so this is a **non-trivial rework, not a cosmetic refactor**. Right now, the backend still emits one hardcoded 3600-second assumption in key paths, so Codex-specific “approximate/unknown” behavior won’t be correct unless those core contracts change first.

## Findings (blocking/suggestion/question)

- [blocking] [app/manager.py](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/app/manager.py:1125) hardcodes `CACHE_TTL_SECONDS = 3600` and applies it in `list_sessions()` to every session row (`cache_ttl_seconds` is always set there). That directly conflicts with the plan’s goal of per-backend policy (Claude exact vs Codex approximate/unknown) and makes AC around exact/approx behavior unattainable with current behavior.
- [blocking] [app/routes/system.py](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/app/routes/system.py) `list_orchestrators()` has a fallback assignment of `cache_ttl_seconds = 3600` for orchestrator payloads unless already set. If plan only updates session serialization, orchestrator serialization still leaks 3600-second certainty and violates “Codex ChatGPT-auth has no contractual TTL”.
- [blocking] [docs/tasks/codex-cache-research/plan.md] AC implies support for active+archived serialized states, but `/api/sessions` and `app/routes/system.py` currently consume `get_all_sessions()` without exposing archived rows by default. Active/archived “serialization” is not currently observable by these consumers, so AC is not met end-to-end.
- [blocking] [app/static/js/app.js](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/app/static/js/app.js) `_cachePill` still defaults `cache_ttl_seconds` via `|| 3600` and `_renderCachePill` turns `remainingMinutes <= 0` into “cold”. This guarantees “unknown” cannot be represented once a placeholder/zero/absent TTL comes in, directly violating the requirement: after the reference window, state must be unknown, not definitively cold.
- [blocking] No explicit Codex path is currently available in payload generation for cache policy; `backend_codex.py` has persistent app-server/thread behavior but does not publish cache-contract metadata. Without adding a clear source of truth (`cache_ttl_policy`, `cache_ttl_approximate`, or similar), frontend behavior is heuristic guesswork and can be wrong under silent Codex backend changes.
- [question] [app/db.py](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/app/db.py) `get_all_sessions()`/schema already carry no explicit cache-policy column today. The plan assumes adding fields, but does not specify migration/compatibility strategy. Could this be done as a backward-compatible additive schema path with defaults, or is a migration required in this MVP sprint?
- [question] [app/mcp_stdio.py](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/app/mcp_stdio.py) The MCP side cache-badge rendering still uses a 3600 fallback and does not follow frontend semantics. If this remains, users see contradictory states in dashboard vs MCP text output.
- [suggestion] [app/routes/system.py](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/app/routes/system.py) + [app/manager.py](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/app/manager.py): model-specific policy should be centralized in one helper and called from both active-orchestrator merge and persisted-session serialization. Duplicate calculations in both paths will become a drift source (classic divergence/race between in-memory and DB snapshots).
- [suggestion] [tests/test_manager.py](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/tests/test_manager.py) / [tests/test_frontend.py](.../worktrees/mnt-data-projects-python-orchestra/research-codex-cache/tests/test_frontend.py): no current tests cover cache-pill states, unknown-after-window behavior, or archived inclusion. Plan’s AC is currently untestable unless new tests are explicitly added (good news: this is feasible, but missing from scope).
- [question] Plan should clarify “1800s is approximate/reference” in one place as explicit state machine, because current hardcoded `cold` semantics in JS would otherwise convert it into a hard contractual boundary when `<=0`.

## Verdict
**Request changes (blocking issues remain).**

Core blocker is that required runtime-aware cache semantics are not represented in the current data contracts consumed by dashboard/orchestrator endpoints, so implementation cannot satisfy AC as written without foundational serialization/schema changes first.
Think of it like labeling fuel as “empty” every time the odometer stops moving for 30 minutes: if your speedometer says all cars have 1h range, your dashboard will eventually look confident about a guess you never measured.

## Round (2026-07-18T09:20:39Z)

## Summary (Round 2)

`git diff` shows only doc-level updates in this working tree (`research.md` modified) plus untracked `plan.md`/`codex-review-plan.md`; no implementation files in `app/` or `tests/` are changed yet.
So this is a plan/doc re-review with current behavior still reflecting old semantics.

## Findings (blocking/suggestion/question)

1. [blocking] [STILL BROKEN] [app/manager.py:1125] `list_sessions()` still assigns `cache_ttl_seconds` from `CACHE_TTL_SECONDS` unconditionally, so runtime-specific TTL/approx policy is not applied yet.
2. [blocking] [STILL BROKEN] [app/routes/system.py:812] orchestrator serialization still has fallback `3600` when `cache_ttl_seconds` is missing.
3. [blocking] [FIXED] [docs/tasks/codex-cache-research/plan.md:74] archived scope issue is corrected: T1 now limits to active + non-archived sessions (explicitly removing archived serialization as out-of-scope).
4. [blocking] [STILL BROKEN] [app/static/js/app.js:1458](#L1458) and [app/static/js/app.js:1484](#L1484) still use `|| 3600` and definitive `cold` at `<=0`, so unknown-after-window cannot be represented.
5. [blocking] [STILL BROKEN] [app/manager.py:44](#L44) and [app/manager.py:1125](#L1125) plus [app/routes/system.py:812](#L812): there is still no source-of-truth runtime policy in payloads from active and DB rows, despite plan requiring backend-type-derived metadata.
6. [question] [FIXED] [docs/tasks/codex-cache-research/plan.md:12] the no-schema-change approach is now explicit (`cache_ttl_seconds` + `cache_ttl_approximate` derived from `backend_type`), resolving the migration ambiguity.
7. [blocking] [STILL BROKEN] [app/mcp_stdio.py:237](#L237) still defaults `cache_ttl_seconds` with `or 3600`, so MCP text output can still drift from plan/dashboard semantics.
8. [suggestion] [FIXED] [docs/tasks/codex-cache-research/plan.md:20](#L20) now explicitly mandates single helper in `app/models.py` and reuse in manager/orchestrator paths, eliminating the previous drift risk.
9. [suggestion] [STILL BROKEN] [tests/test_manager.py](#L1), [tests/test_frontend.py](#L1), [tests/test_mcp_stdio.py](#L1): test coverage for exact/approx/unknown state machine is still not present in current code; plan lists these as requested additions but no files changed yet.
10. [question] [FIXED] [docs/tasks/codex-cache-research/plan.md:10](#L10) and [docs/tasks/codex-cache-research/plan.md:34](#L34) now explicitly define `1800s` as approximate/reference and direct the post-window state to `unknown`, which resolves the prior ambiguity.

## Verdict

Round 2 verdict: **NOT APPROVED** for implementation status, because all prior blockers are still present in runtime code despite being documented in the updated plan.
If you want this as **APPROVED**, either commit/apply T1 code changes (manager/system/js/mcp + tests) or send that diff for review next.

## Round (2026-07-18T09:21:23Z)

## Re-review status
Round 3: Plan-only review only. I re-read `docs/tasks/codex-cache-research/plan.md` and `git diff` output.

`git status`: only `docs/tasks/codex-cache-research/research.md` is modified in tracked diff; `plan.md` and `codex-review-plan.md` are untracked and being reviewed as the proposed plan artifact.

## New findings (prior finding status → plan-level outcome)

1. FIXED.
   Finding 1 (manager hardcoded 3600) is covered by [plan.md:24](docs/tasks/codex-cache-research/plan.md:24), [plan.md:25](docs/tasks/codex-cache-research/plan.md:25): explicit replacement of `CACHE_TTL_SECONDS` with runtime helper in `app/manager.py::list_sessions`.

2. FIXED.
   Finding 2 (system fallback 3600) is covered by [plan.md:26](docs/tasks/codex-cache-research/plan.md:26): same helper applied in `app/routes/system.py::list_orchestrators`.

3. FIXED.
   Finding 3 (active+archived ambiguity) is resolved by [plan.md:74](docs/tasks/codex-cache-research/plan.md:74) and [plan.md:80-91](docs/tasks/codex-cache-research/plan.md:80): scope narrowed to active + persisted non-archived, and AC rewritten accordingly.

4. FIXED.
   Finding 4 (JS `||3600` / definite cold) is covered by [plan.md:36](docs/tasks/codex-cache-research/plan.md:36), [plan.md:34](docs/tasks/codex-cache-research/plan.md:34), [plan.md:35](docs/tasks/codex-cache-research/plan.md:35): explicit unknown-after-window behavior and no defaulting through falsy TTL.

5. FIXED.
   Finding 5 (no source of truth for runtime policy) is addressed by [plan.md:19-23](docs/tasks/codex-cache-research/plan.md:19): single helper in `app/models.py` deriving policy from existing `backend_type` (`cache_ttl_seconds`, `cache_ttl_approximate`).

6. FIXED.
   Finding 6 (schema migration ambiguity) is resolved by [plan.md:12](docs/tasks/codex-cache-research/plan.md:12): metadata derived, no DB column/migration required.

7. FIXED.
   Finding 7 (MCP fallback mismatch) is covered by [plan.md:39-41](docs/tasks/codex-cache-research/plan.md:39): `_cache_pill` updated with same runtime metadata and unknown path.

8. FIXED.
   Finding 8 (central helper duplication risk) is explicitly fixed by [plan.md:19-23](docs/tasks/codex-cache-research/plan.md:19) and reuse in manager/system paths [plan.md:24-27](docs/tasks/codex-cache-research/plan.md:24).

9. FIXED (coverage gap, not blocker).
   Finding 9 (tests missing) is addressed by [plan.md:50-62](docs/tasks/codex-cache-research/plan.md:50): explicit tests added for backend-routing, manager, API, frontend, MCP.

10. FIXED.
   Finding 10 (1800 as contract ambiguity) is explicitly normalized in [plan.md:10](docs/tasks/codex-cache-research/plan.md:10) and user-facing behavior in [plan.md:34](docs/tasks/codex-cache-research/plan.md:34).

NEW BUG.
- Untracked [docs/tasks/codex-cache-research/codex-review-plan.md](docs/tasks/codex-cache-research/codex-review-plan.md) contains Round 2 verdict text; if this file is committed as-is, it will encode stale implementation status and can confuse approval artifacts. This is non-blocking but should be cleaned or renamed before merge.

## Verdict
APPROVED FOR IMPLEMENTATION for Phase 2 plan review.
The prior blocker set is now plan-covered and coherent with current code contracts, with only the noted stale-review-artifact cleanup as a non-blocking cleanup item.
