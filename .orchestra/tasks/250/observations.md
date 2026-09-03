## 2026-08-23 — behavioral-test prompt research
- Observation: a single broad multi-pattern `rg` across all cited tasks produced a truncated 30K-token result; one-case/one-anchor retrieval immediately exposed the exact historical test and its corrected seam.
- Cause: the required corpus has fixed columns, while topic-wide retrieval mixes unrelated true facts and hides the join needed by the table.
- Candidate: no new skill; the existing context-economy and task-observer table methodology already prescribe targeted retrieval.
- Evidence: initial `rg` reported `Warning: truncated output`; targeted searches found `tests/test_fan_barrier_gates.py:144-173`, `tests/test_usage_history_frontend.py:244-298`, and `tests/test_hot_apply.py:70-89` without truncation.

## 2026-08-23 — checklist compliance versus oracle quality
- Observation: all 6 candidate runs answered six numbered questions before editing, yet candidate correctness tied baseline 28/30 and rejected one valid metadata extension.
- Cause: a model can state a valid future change in prose and later compare a complete record, so declared intent is not mechanical enforcement.
- Candidate: update `docs/kb/test-oracles.md`; no new skill and no production prompt change without a stronger repeated A/B.
- Evidence: `docs/tasks/250/analysis-summary.json` (`candidate_adherence_count=6/6`, `score_gain=0`) and candidate T05 `assert debits == [...]` versus `valid_debit_metadata`.

