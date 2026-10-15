# V-865 raw model answers

Workflow `V-865-6eefb1192d73`, completed 25/25. Raw answers below are copied from the returned workflow manifest in stage task order, then unblinded using the preregistered A/B order in `../manifest.md`. No wording edited.

## C01 — A

No. The −600 ms was measured after removing Tailwind, which also removed styles and made layout cheaper. The proposed static-CSS replacement was not tested, and the comparable control retains the same generated CSS and cascade position.

## C01 — B

No. The −600 ms measures removing Tailwind, which also removed styles and changed layout cost; it does not measure the proposed static-CSS replacement. The control must retain comparable generated CSS and cascade position, so the replacement’s speed is unresolved.

## C02 — A

The sequence cannot establish that a code change caused an improvement or regression: the baseline results moved without any code change, and the sample sizes differ (8, 8, and 16). The control host’s 1 MB transfer shows that the target route stalled during that observation; it does not identify the cause.

## C02 — B

The sequence establishes that the reported network baseline was unstable: results changed from 7/8 to 2/8 to 11/16 without a code change. The control host’s successful 1 MB transfer shows that some network path worked, but it does not establish that the control route was comparable to the stalled target route. This evidence cannot establish that a code change caused an outcome; that claim remains unresolved.

## C03 — A

No. The three estimators reverse the Sol/Astra ordering, so the ranking is not established. The claim that Sol costs 29% more than Astra was withdrawn.

## C03 — B

No. The Sol/Astra cost-per-run estimates use the same data, but their ordering reverses across the three estimators (0.425/0.330, 0.443/0.333, and 0.336/0.411 pp/run), so the ranking is unresolved. The exact counts—814 of 1,106 adjacent deltas were 0 and 246 were +1 pp—do not establish which model costs more.

## C04 — A

The 1.6× pool-efficiency estimate is **unresolved**: it assumed one token rate for every model, while the rate card is model-specific. Recalculation matches `cost_usd` at 94× in dollars, but this is a **model-based** result, not direct pool evidence. Direct evidence covers only 16 mixed or quantized windows. The 5 pp reserve estimates—16 Luna runs under the old formula, about 800 under the credit model, and about 9 Astra runs—are **model-based**, not established run counts.

## C04 — B

The recalculation’s match to `cost_usd` at 94× is established for the recalculated dollar values, but it does not establish pool efficiency: the original 1.6× estimate used one token rate for every model, while rates are model-specific. The reserve figures—16 Luna runs under the old formula, about 800 under the credit model, and about 9 Astra runs—are model-based estimates for a 5 pp reserve. Actual pool efficiency is unresolved: the only direct evidence is 16 mixed/quantized windows, with no comparable control or enough evidence here to quantify uncertainty.

## C05 — A

No. `weekly_scoped` is a cap within the common weekly pool, not a separate pool. The counter rose by 1 percentage point in 15 minutes, and 8 of 10 Opus turns were for another project; this observation does not attribute the quota delta to Fable.

## C05 — B

No. `weekly_scoped` is a cap within the common weekly pool, so this observation does not show Fable has separate capacity. The global counter rose 1 percentage point in 15 minutes, while 8 of the 10 Opus turns were from another project; without a comparable control, the quota delta cannot be attributed to Fable.

## C06 — A

No. The comparison changes both the method constraint and the number of turns, so it does not isolate model capability. It shows that, on this corpus and task, all five models chose AST+wc and achieved 12/12 in one turn with lower reported costs in the free-method run.

## C06 — B

No. The outcome is cost per completed task; the analysis unit is a model run. The runs used different methods and turn counts, so the prescribed-route run is not a comparable control for the free-method run. The lower costs show what happened under the free-method setup, but they do not isolate model capability.

## C07 — A

No. Opus-high passed 9/9 scenarios in the initial run, but in the second round it passed only 5/9, with the same four cancel/spawn race paths remaining. The evidence does not support that it covers all paths.

## C07 — B

No. The first Opus-high run passed 9/9 scenarios, but the second round passed only 5/9 for both Opus medium and high, with the same four cancel/spawn race paths remaining. The fixed scenario counts show Opus-high did not consistently cover all paths.

## C08 — A

Seq3 scored higher than hybrid on the four development cases: 0.902 vs. 0.879; on all seven combined cases, it scored 0.899 vs. 0.861. These results suggest seq3 may be better, but do not demonstrate that it is: repeat variation reached ±0.11 per case, and holdout coverage was incomplete (seq3 ran on only three of five cases, once each, with noise up to ±0.1). Report the observed scores and coverage, and qualify any claim of superiority as inconclusive.

## C08 — B

Seq3 scored higher than hybrid on the four development cases (0.902 vs. 0.879) and the combined seven cases (0.899 vs. 0.861), but it is not demonstrably better: per-case repeat variation reached ±0.11, and the holdout comparison is incomplete (seq3 ran on only three of five cases, with single-run noise up to ±0.1). These are observed score differences, not evidence of a reliable advantage; the holdout result is unresolved. Report the exact observed scores and coverage, and avoid a general superiority claim.

## C09 — A

No. The rollout scored 90.69% on 361 tasks, 0.50 percentage points above the 90.19% leaderboard score, but paired baseline outcomes are unavailable. The rough independent-binomial 95% interval for the difference, [−3.79, +4.79] percentage points, includes zero, so the evidence does not establish a new SOTA.

## C09 — B

No. The observed outcome was task-level accuracy: 90.69% on 361 tasks, 0.50 percentage points above the official leaderboard score. The baseline’s paired task outcomes are unavailable, so comparability and a paired analysis cannot be verified; the rough independent-binomial 95% interval (−3.79 to +4.79 pp) includes both a loss and a gain. A new SOTA is therefore unresolved, not proved.

## C10 — A

The idiom was followed in 20/20 runs; work was saved in 15/20. The 20/20 measures following the instruction idiom, not saving work. The harness erased the end-of-file marker in 8 runs in each arm.

## C10 — B

The instruction idiom was followed in 20/20 CLI runs; work was saved in 15/20. The 20/20 measures instruction following, not successful work saving. The harness erased the end-of-file marker in 8 runs in each arm.

## C11 — A

Each of the five models scored 12/12 on rows, 12/12 on longest-function names, and 12/12 on function lengths. That is 36/36 correct model×field checks per model, or **180/180 total** across five models and three fields.

## C11 — B

Each of the five models returned 12/12 rows, 12/12 longest-function names, and 12/12 function lengths. Across the three fields, that is 36/36 correct checks per model and 180/180 correct model×field checks total.

## C12 — A

On these five fixed tasks, low exceeded medium by 1 acceptance (10/10 − 9/10) and max by 2 (10/10 − 8/10). These are observed count differences only; they do not establish a population-level effort effect.

## C12 — B

On the five fixed tasks run twice each, complete acceptance was 10/10 at low, 9/10 at medium, and 8/10 at max. The observed count differences were low−medium = 1 acceptance and low−max = 2 acceptances; these counts do not establish a population-level effort effect.
