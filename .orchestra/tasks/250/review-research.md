<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

🧪 Even frozen experiments can smuggle in one unfrozen threshold. The core result survives adversarial checking: the 28/30 totals, 1/1/4 split, `p=1.0`, criterion counts, LOC/tool/time aggregates, whale guards, expected variants, and distinguishing T03/T05 outcomes all reconcile mechanically.

## Findings (blocking/suggestion/question)

suggestion: [research.md:18](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-test-prompt-sol/docs/tasks/250/research.md:18) — “fewer than two paired task wins” was not preregistered as an H1 falsifier. [prereg.md:14](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-test-prompt-sol/docs/tasks/250/prereg.md:14) defines H1’s falsifier as no score improvement or a whale; the two-win threshold belongs to H0 at line 18. Remove it from H1 or label it secondary/post-hoc. The conclusion remains unchanged because score gain was zero.

suggestion: [research.md:129](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-test-prompt-sol/docs/tasks/250/research.md:129) — T05 does not show that the candidate’s stated compatibility answer failed to constrain its assertion. The candidate explicitly inserted an audit entry in [test_target.py:6](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-test-prompt-sol/docs/tasks/250/raw/05-t05_ledger_exactly_once-candidate/test_target.py:6), and `valid_audit_entry` stayed green; the separate, unmentioned `valid_debit_metadata` alternative failed. The supported conclusion is narrower: naming one valid extension did not prevent over-specification along another dimension.

## Verdict

**APPROVE WITH SUGGESTIONS.** No blocking findings. The load-bearing zero-gain result and operational recommendation remain supported; the two comments tighten preregistration traceability and the interpretation of T05.

The experiment holds up—the labels merely tried to grade a slightly different exam. 📋
