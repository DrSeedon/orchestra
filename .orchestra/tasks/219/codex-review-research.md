## Summary

The report establishes that this particular two-worker replay had poor oracle recall, but it does not establish that four Luna researchers cannot replace one expensive researcher. The main causal ambiguity is unresolved: model capability, fan-out, slice design, and post-spawn oracle construction are confounded.

Mandatory verbatim line from the report:

> “То есть дисциплина, которую мы считаем признаком добросовестного ресёрча, соблюдена дешёвой моделью полностью — и не коррелирует с тем, найден ответ или нет.”

## Findings

[suggestion] `docs/tasks/219/research.md:158` — C1 does not survive as the precise “2 of 14” quality estimate. The oracle was frozen before outputs but after workers received their slice prompts, allowing the evaluator to decompose the reference around distinctions the prompts never requested. It also overcounts correlated reasoning stages as separate findings: A1–A5 are largely one causal analysis of `check-ignore`, while B2 and B7 partly restate the same delivery verdict. Conversely, A9 appears in `oracle-188.md:22` but silently disappears from scoring, and B3 is removed after the run. Thus “14 load-bearing findings” is not a stable, independently specified denominator. The defensible result is narrower: the two reports omitted most details selected by this retrospective oracle.

[suggestion] `docs/tasks/219/research.md:159` — C3 exposes the central confound rather than resolving it. Slice A was asked the broad question “работают ли правила” but is scored against a very particular `check-ignore` causal design, placebo dates, prompt-incidence analysis, noise estimator, and runtime comparison. Its discovery of other rules is counted as zero recall. That is indistinguishable from a parent writing an under-specified slice prompt. “Artifacts cannot detect omitted claims” survives as a general logical point; “cheap fan-out causes omission” and the resulting restriction to counting labour do not.

[suggestion] `docs/tasks/219/research.md:112` — C2’s strict 2/10 count depends on a rubric that conflates evidence-source joins with inability to parallelize research. A child can gather `WEB`, another `DB`, and a parent can join them; a `JOIN` is therefore not evidence against the proposed fan architecture unless the join itself requires iterative cross-slice discovery. The rubric asserts that distinction but does not measure it. The author’s declared skepticism and prior exposure make the non-blind classification material, not merely cosmetic.

[suggestion] `docs/tasks/219/corpus-divisibility.md:96` — A concrete misclassification is #198’s `PREMISE-REFUTED=yes`. The row explicitly says there was no corrective claim inside the research and that the refutations arrived in Phase 2, after research. Under the preregistered definition—“есть ли в прямом ответе утверждение, отменяющее вопрос”—this should be `no`. The headline count moves from 6/10 to 5/10. Strict divisibility remains 2/10, but the claim that most research tasks refute their premise no longer holds.

[suggestion] `docs/tasks/219/research.md:219` — C4’s measured core survives only locally: two adjacent turns show approximately $0.87 and 99% cache-read for this parent at this context size. The table is commendably explicit about the estimated $0.6 and extrapolated six wake-ups, but the headline overstates them. V3 was never run, its $0.88 wake-up and unchanged 2/14 quality are counterfactual, and “~85% of coordination overhead” counts only extrapolated wake-up cost. Including the report’s own $0.6 framing estimate changes the reduction from roughly 83% to roughly 74%. Historical average turns do not isolate child-triggered wake-ups.

[question] `docs/tasks/219/research.md:230` — C5 is reasoning, not measurement. The one observed interrupt concerned contamination of the experimental perimeter and preserved preregistration; it did not re-aim a child or improve research coverage. No deaf-barrier run, adaptive-re-aim run, or paired quality comparison exists. “A barrier does not itself add knowledge” is plausible; “makes divisibility worse” should remain a hypothesis.

[suggestion] `docs/tasks/219/research.md:244` — The claimed applicability boundary—only 2/10 tasks where the customer supplied slices—is not identified by the experiment. The replay tested exactly one of those supposedly favourable tasks, with two workers rather than the proposed four, and then used the same failed prompt split to declare all other tasks unsuitable. This cannot distinguish “customer must supply decomposition” from “the expensive parent must write better prompts or adapt the decomposition.”

[suggestion] `docs/tasks/219/research.md:298` — The strongest case for the owner’s proposal is underweighted: cheap independent workers buy breadth, fresh perspectives, and affordable redundancy, not merely counting labour. In this replay Luna reproduced an exact inventory at 210× lower API-equivalent cost, found two defects absent from the reference, self-reported contamination, and produced no false factual claims. At that cost, four workers could use overlapping or adversarial assignments so that the union of discoveries—or disagreement itself—reduces omission. The proposed four-worker architecture was never tested; only two single-shot, non-overlapping slices were. That is the most direct alternative explanation for the result.

## Verdict

C1: fails as a calibrated 2/14 estimate; survives only as evidence of low recall against this evaluator-built oracle.

C2: fails in its 6/10 premise-refutation headline and remains vulnerable in the strict divisibility classification.

C3: artifact checks indeed cannot detect omissions, but the report does not separate model omission from prompt-induced omission.

C4: the two $0.87/99% observations survive; the four-child table and ~85% saving are extrapolations presented too conclusively.

C5: unmeasured reasoning, not an experimental result.

Overall, the evidence supports “do not deploy the replacement yet” and “test overlapping/adversarial four-Luna designs next.” It does not support the stronger conclusion that Luna should be restricted to counting labour under an expensive researcher.

## Round (2026-08-12T08:51:07Z)

## Summary

Re-review status: the major causal claims are substantially better calibrated. I ACK both push-backs:

- P1: ACK. I withdraw the claim that the slice prompt was narrower than the reference prompt. The remaining uncertainty is only whether a stronger-than-original prompt would have helped; that is untested.
- P2: ACK. “A single-pass cheap slice does not produce the finding” is the strongest supported formulation. Model, turn budget, and tool-call budget remain confounded.

Mandatory current-file quote:

> “Оба замера дешёвые: четыре Luna по два хода ≈ $1 и ≈0.2 п.п. пула Codex.”

Note: `git diff` and `git status` show no uncommitted changes for the two reviewed files, so I reviewed their current contents rather than an available diff.

## Findings

[suggestion] [docs/tasks/219/research.md:45](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/219/research.md:45) — NEW BUG: the direct answer still says the barrier removes “~85%,” contradicting the corrected ~74% at lines 237–239. Because the direct answer is the actionable summary, the accepted C4 correction has not propagated to its most important occurrence.

[suggestion] [docs/tasks/219/research.md:69](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/219/research.md:69) — NEW BUG: the hypothesis table still says “6 из 10 с опровержением постановки,” despite the corrected `PREMISE-REFUTED 4/10`. The same stale 6/10 survives at lines 269–272. Those passages also omit the new distinction between preregistered `PREMISE-REFUTED` and post-hoc `OUT-OF-SLICE`.

[suggestion] [docs/tasks/219/research.md:12](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/219/research.md:12) — STILL BROKEN: the opening thesis still categorically says the fan should replace hands, not the researcher, and calls that conclusion “не мнение, а счёт.” Lines 51–55 and 292–301 now correctly say the proposed replacement was neither confirmed nor refuted. The first sentence should share that calibration; otherwise the report’s headline still outruns its revised verdict.

[suggestion] [docs/tasks/219/research.md:216](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-fan-research/docs/tasks/219/research.md:216) — STILL BROKEN: “Что действительно работает против `OMISSION`” remains causal overreach from one single-pass replay. The run shows that the two reproduced findings were count-like; it does not test whether expensive question ownership prevents omission, nor whether multi-pass or overlapping cheap workers do. “Что сработало в этом реплее” would match the evidence and P2 correction.

## Re-review status

- Oracle denominator unfair/unstable: FIXED. Construction and A1–A5 collapse sensitivity are now explicit.
- Prompt-induced omission: FIXED after P1. Same-width prompts are acknowledged; stronger prompting remains untested.
- Divisibility rubric conflates joins with non-parallelizability: STILL BROKEN, but the softened overall recommendation limits the damage.
- #198 misclassification: FIXED; #208 was also correctly repaired.
- Coordination table overstates measurement: FIXED except for the stale ~85% headline above.
- Barrier worsens divisibility: FIXED; correctly downgraded to a hypothesis.
- Applicability boundary asserted too strongly: STILL BROKEN at lines 263–272, especially the stale 6/10.
- Strongest case for the owner omitted: FIXED in section D.
- Turn-budget/model confound: FIXED after P2 and now prominently disclosed.

## Verdict

The revised defensible conclusion is: do not replace the expensive researcher yet; next test multi-turn, overlapping/adversarial Luna assignments. P1 and P2 are resolved in the author’s favor.

Four internal inconsistencies/overclaims remain, chiefly because earlier headline passages were not updated to match the corrected analysis. No blocking findings.

## Round 2
