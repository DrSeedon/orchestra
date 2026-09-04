<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently SQLite is a perfectly competent bouncer, except when one guest appears twice. 😏

## Summary

Reviewed the exact pinned snapshot `2268e0f...2735fcf...`; no authorization bypass or archived-project leak found. Targeted checks passed: 5 tests, `git diff --check` clean. No blocking findings.

ACK — verbatim changed line: `operatorCsrf = currentPayload.csrf_token || operatorCsrf;`

## Findings (Conventional Comments)

### [P2] bug: Deduplicate projects in the filtered join

**File:** [app/portfolio.py:310](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-projects-scope/app/portfolio.py:310) (diff lines 310–314) | **Confidence:** 0.88

The join returns one row per matching active membership, while the caller renders every returned ID. If a selected session has multiple active membership rows for one project, the board returns duplicate project cards.

```python
                    """SELECT DISTINCT p.id FROM portfolio_projects p
                       JOIN portfolio_members m ON m.project_id=p.id
```

### [P2] suggestion: Exercise the real orchestrator-switch event

**File:** [tests/test_portfolio_agent_filter_frontend_472.py:77](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-projects-scope/tests/test_portfolio_agent_filter_frontend_472.py:77) | **Confidence:** 0.94

The test changes `selectedIndex` and manually calls `PortfolioPanel.load()`, so it verifies DOM sampling but not the production switch path or stale-response invalidation. A regression where switching tabs fails to trigger the reload could pass this test.

## Verdict

**Overall Correctness:** ✅ Correct | **Confidence:** 0.91

The implementation preserves header-based authorization precedence, keeps the unfiltered operator view, excludes archived projects in the new slice, and renders empty slices correctly. The remaining findings are non-blocking robustness and coverage improvements.

The board now keeps foreign projects out; it just needs to stop photocopying the same allowed guest.
