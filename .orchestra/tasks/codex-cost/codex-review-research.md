The measurement script can crash on valid incomplete data and can misclassify completed Sol turns after model changes. Its supposedly reproducible snapshot also changes as new review jobs are recorded.

Full review comments:

- [P2] Guard the missing review median before dividing — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/measure_usage.py:543-546
  When review jobs exist but none match a Sol rollout—for example, review rollouts were cleaned, CWD correlation fails, or reviews use Spark—`category_summary(reviews)` returns `median=None`. If worker usage still matches, this guard passes and dividing `None` by the worker median raises `TypeError` instead of producing a report with no review ratio.

- [P2] Reconstruct turns without the mutable session model — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/measure_usage.py:260-264
  When a worker is switched away from Sol after a measured Sol turn, `sessions.model` contains only the new current model, so this query drops the entire session. Its Sol rollout events are then classified as unbounded worker usage and excluded from the completed-turn count and median, biasing the review-to-worker comparison; turn intervals should be loaded independently and filtered using rollout `turn_context`.

- [P2] Freeze the review sample used by the snapshot — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/measure_usage.py:151-153
  After any later `codex_review` succeeds, this unbounded query includes it and the derived min/max window silently expands, changing every total and median in the dated July 24 report. Because the documented command has no timestamp or job-ID cutoff, it cannot reproduce the committed snapshot once normal background-job activity continues.

## Round (2026-07-24T14:21:00Z)

A dated snapshot that is actually frozen—what luxury 😏

## Re-review status

- **FIXED** — missing review median is guarded before division ([measure_usage.py:553](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/measure_usage.py:553)).
- **FIXED** — worker turns load without `sessions.model`; Sol filtering uses rollout `turn_context` ([measure_usage.py:260](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/measure_usage.py:260), [measure_usage.py:353](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/measure_usage.py:353)).
- **FIXED** — paired timestamps freeze the sample, and the exact window is documented ([measure_usage.py:457](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/measure_usage.py:457), [research.md:88](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-cost/docs/tasks/codex-cost/research.md:88)).

## New findings

None. One later matching review job exists, but the frozen rerun still produced the documented 11/31 units, 264.511/2418.776 credits, and 9.86%/90.14% split. Targeted regression checks passed.

`git diff` itself was empty because `docs/tasks/codex-cost/` is entirely untracked; I reviewed that directory as the uncommitted addition.

## Verdict

✅ Correct. All prior findings are closed; no new blocker changes the report conclusion.

The snapshot is finally frozen by timestamps, not by optimism.

APPROVED
