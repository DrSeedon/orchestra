<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The artifact has a strong measurement outline and the mechanical probes pass:

- `freeze_corpus_432.py`: 12 tasks, `sessions_before=467 sessions_after=467`
- `cap_probe_432.py`: `nearest-rank-p95=56129 cap_power_of_two=65536 tasks=12`

Exact sentence proving artifact read: “Treatment bundle ограничивается 65,536 UTF-8 bytes целиком в сериализованном JSON, включая path, line range и framing.”

## Findings

### blocking

- blocking: `docs/tasks/432/research.md:178-194` — the protocol requires the result commit to be absent from the experimental checkout (`git cat-file ...` must return non-zero), but later requires applying a hidden oracle “из result commit(s)” in that checkout. No separate oracle source, copy, or application mechanism is defined, so the prescribed run cannot execute as written without either exposing the result commit or inventing an unregistered data path → specify a separate privileged oracle checkout/artifact channel, with the exact copy/application order and proof that the model cannot read it.

### suggestion

- suggestion: `scripts/recon429/freeze_corpus_432.py:17-31,63-104` — corpus membership is hardcoded in `TASKS` and `EPISODES`; the script verifies those 12 rows but never recomputes the stated “all tasks satisfying rules” set or enforces most F3 criteria (terminal turn, no web/ssh, exclusion of #422, minimum repository reads) → emit and compare the complete candidate set before freezing, or state explicitly that this is a manually selected corpus.

- suggestion: `docs/tasks/432/research.md:102-108` and `scripts/recon429/cap_probe_432.py:21-37` — the cap is derived from post-task result diffs, including removed lines and diff framing, rather than from the actual pre-treatment retrieval context. This can make the bundle capacity depend on the known successful implementation and does not establish that it covers the historical search context → preregister the cap from a source-context-only measurement, or label this as a deliberately outcome-informed capacity heuristic.

- suggestion: `docs/tasks/432/research.md:203-215,234-239` — B changes more than placement: the scout receives `task brief`, uses a distinct role/tool permission set, emits JSON framing, and the main receives a bundle. The cold control does not isolate these effects, while the zero-retrieval control is a different task class → add a matched fresh-scout/handoff control with the same prompt/framing but no parent-history removal, or explicitly restrict the causal claim to the entire “scout + handoff” package.

- suggestion: `docs/tasks/432/research.md:219-227` — A is always run before B (`A1/B1/A2/B2`), so arm is confounded with within-episode time, quota state, provider availability, and machine load. A/A before treatment detects some noise but cannot identify this arm-order bias → randomize or counterbalance arm order per episode/repetition while retaining A/B alternation in the schedule.

- suggestion: `docs/tasks/432/research.md:222-230` — the A/A noise estimate is defined only for `cost_usd`, but the declared outcomes also include main-only and net `cache_read`. A cost-based p90 threshold cannot calibrate claims about cache-read savings → preregister separate A/A noise metrics and decision thresholds for each primary/secondary outcome, or declare cache-read descriptive-only.

- suggestion: `docs/tasks/432/research.md:167-170,234-241` — failure handling can still create arm-dependent exclusion: B has an extra provider session and therefore more opportunities for pre-request availability failure. “Repeat in the same slot” does not specify a bounded retry rule, whether the first attempt remains in the denominator, or how repeated failures are analyzed → define per-slot retry caps and report availability failures by arm before any paired-effect calculation.

- suggestion: `docs/tasks/432/research.md:178-182,249-252` — the hidden oracle is not preregistered at the level needed to detect oracle leakage or false reds: exact named commands/assertions are deferred to Phase 2, and a result commit is explicitly the known successful path. A model can pass the frozen assertion while producing an alternative or semantically incomplete implementation, or fail because the oracle collection itself is broken → freeze an oracle manifest with exact commands, expected failure mode on the baseline snapshot, and green evidence on each result commit before Phase 2.

## Verdict

Needs work. The core accounting contract is promising, but the oracle-access contradiction is blocking, and corpus selection, arm-order confounding, and control design currently prevent a clean causal interpretation.

## Review log

- Attempt 1 completed: verdict `Needs work`; one blocking oracle-access contradiction and seven
  suggestions.
- Attempt 2 started 2026-09-01 after changing the research artifact: controller-only post-model
  oracle channel + canary, source-context cap, package-level estimand, counterbalanced ABAB/BABA,
  separate cost/cache noise, bounded pre-provider retry, and explicit manual-corpus limitation.

## Round (2026-09-01T15:39:22Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Re-review status

`git diff` is empty because the reviewed paths are untracked (`git status --short` shows `??`); I reviewed their current contents directly.

Prior findings:

- Oracle checkout contradiction — FIXED.
- Corpus post-selection labeling — FIXED.
- Cap post-selection from result diffs — FIXED.
- Whole-package estimand — FIXED.
- Fixed arm ordering — FIXED.
- Separate cost/cache A/A noise — PARTIALLY FIXED: net `cache_read` still has no matching A/A noise estimate.
- Availability retry bias — FIXED.
- Oracle manifest gate — FIXED.

Exact sentence from the current artifact: “Разделить вклад role prompt, framing и удаления parent history этот двухплечевой замер не может; cold control проверяет зависимость эффекта от history, но не превращает package estimate в «чистую цену placement».”

## New findings

- blocking: `docs/tasks/432/research.md:238-241` — `noise_x_i = 2*abs(...)/(x_A01+x_A02)` is undefined when both A/A observations have zero `cache_read_tokens`; this can crash calibration or silently require an unstated exclusion → preregister zero-denominator handling, such as `noise=0` when both are zero and invalid when only one is zero.

- suggestion: `docs/tasks/432/research.md:182-187` — the separate cache A/A threshold calibrates baseline/main cache only, while `cache_net_B` includes scout cache and has a different distribution → either add a net-cache A/A control or make net-cache results descriptive without a threshold claim.

- suggestion: `scripts/recon429/cap_probe_432.py:46-55` — `repo_ids` can contain `None`, causing every `tool_result` with a null `tool_use_id` to count as paired; additionally, the classifier includes repository metadata commands such as `git status` and `ls-files`, whose outputs are not necessarily source context → require non-null one-to-one pairing and define/exclude non-source repository outputs.

## Verdict

Needs work. The previous blocking oracle issue is fixed, but the zero-denominator cache-noise case is a new blocking protocol defect.

## Author resolution after round ceiling

No third model round was started: the prose ceiling is two.

- ACK blocking: current `research.md` defines `0/0 → noise=0`; when exactly one observation is
  zero, the stated formula remains defined and equals 2.
- ACK net-cache suggestion: only main-cache has an inferential A/A threshold; scout+main net cache
  is explicitly descriptive.
- ACK pairing suggestion: `cap_probe_432.py` now requires non-null ids, rejects duplicate results,
  counts only exactly one paired result, reports two unpaired calls, and excludes metadata-only
  `ls/find/git status/log/ls-files`. Current result: p75 `151661`, cap `262144`, sessions `467→467`.

Reviewer verdict remains `Needs work`; this section records mechanical resolution, not a claimed
reviewer approval.
