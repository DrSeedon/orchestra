## Summary

The calendar-reset claim survives the available data, but the proposed operational policy does not. The document overstates a four-week, cross-tariff backtest as a separator, and the tariff-ratio analysis describes a pair-selection method that was not actually reflected in its reported pair counts.

Sighted-review proof:

> **И главное, что портит всю красивую картину.** На тарифе Max 20 у нас **две полные недели, и обе

I ran 10 read-only SQL queries against `/home/kesha/scratch-186/snap.db`. Relevant raw output is included below.

## Findings

1. **blocking: The reported exchange-rate sample is not “both counters increasing.”** [`docs/tasks/186/research.md:156`](docs/tasks/186/research.md:156)

   The document says every pair has both counters increasing, then reports 282 Max-5 pairs and 340 post-01.08 pairs. Repeating those exact temporal/window constraints produced 282 and 341 pairs only when pairs with `Δ7d = 0` were retained. Only 58 and 94 pairs, respectively, had both counters increase.

   This is load-bearing because the reported `r` values are ratios of summed deltas including hundreds of weekly-flat pairs—not the stated sample. Conditioning on both counters increasing gives materially different values:

   ```text
   Q9 pair-selection sensitivity
   mid|282|58|224|0.274|0.063
   post01|341|94|246|0.454|0.128
   pre20|210|89|121|0.317|0.139
   ```

   Columns are `segment | five-hour-increase pairs | both-increase pairs | Δ7d=0 pairs | mean Δ7d/Δ5h among both-increase pairs | ratio of sums including flat pairs`.

   The tariff transition may still be real—the simultaneous zeroing is strong evidence—but the claimed methodology, bootstrap population, CIs, and physical interpretation of `1/r` must be recomputed and described accurately. Non-overlapping CIs from the wrong/stated-as-different sample are not valid proof.

2. **blocking: `D > 14` is not validated as a separator on the current tariff, so the “safe week” operational promise is unsupported.** [`docs/tasks/186/research.md:21`](docs/tasks/186/research.md:21), [`docs/tasks/186/research.md:32`](docs/tasks/186/research.md:32), [`docs/tasks/186/research.md:335`](docs/tasks/186/research.md:335)

   There are zero safe Max-20 weeks in the backtest. Both Max-20 observations failed; both nominal controls came from Max 5 or a tariff-transition week, where the document itself says percentages are incomparable and the 5h gate constrained demand.

   Thus these claims are not supported:

   - “Замер … даёт разделение без серой зоны.”
   - “≤13% — неделя пройдёт спокойно.”
   - “Ложных срабатываний … ноль.”

   The limitation at the end correctly acknowledges the problem, but it does not cure the operational certainty at the beginning. `D` can be presented as a runway estimate and `14` as an explicit tolerance for losing one defined “working day”; it cannot yet be presented as an empirically validated Max-20 classifier. One safe Max-20 week—or prospective validation—is required before “safe” behavior should be automated.

3. **blocking: The tariff boundaries are plausible events, but the document calls them proven tariff changes without excluding demand/telemetry confounds.** [`docs/tasks/186/research.md:138`](docs/tasks/186/research.md:138), [`docs/tasks/186/research.md:143`](docs/tasks/186/research.md:143)

   The simultaneous zeroing at both nominated boundaries is strong evidence of an account-level event. It does not identify that event as Max 20→5 or Max 5→20: the document itself records two other unexplained account-level resets and says reset alone is insufficient.

   The supposed independent confirmation, `r`, is compromised by Finding 1. The available `active_agents` history cannot exclude a concurrency confound because it is uniformly zero around both boundaries:

   ```text
   Q10 activity around boundaries compact
   pre20_24h|191|0.0|0|0.0
   post20_24h|215|0.0|0|0.0
   pre01_24h|257|0.0|0|0.0
   post01_24h|248|0.0|0|0.0
   ```

   `turn_usage` begins only on 03.08, so it cannot test model mix across either boundary. The dates can be labelled “inferred tariff boundaries, consistent with known subscription changes,” but the database alone does not establish the tariff identity.

4. **suggestion: The Tuesday 07:00 UTC anchor is supported, but “deterministic” overgeneralizes six historical windows.** [`docs/tasks/186/research.md:201`](docs/tasks/186/research.md:201), [`docs/tasks/186/research.md:220`](docs/tasks/186/research.md:220)

   I found no counterexample. All normalized targets were Tuesday at 06:59/07:00 UTC:

   ```text
   Q7 normalized weekly targets
   2026-07-07T06:59|202|2026-07-05T05:24:59.228239+00:00|2026-07-07T06:55:23.959859+00:00
   2026-07-07T07:00|214|2026-07-05T05:19:58.635440+00:00|2026-07-07T06:45:22.695713+00:00
   2026-07-14T06:59|694|2026-07-07T07:05:25.160304+00:00|2026-07-14T06:48:13.836614+00:00
   2026-07-14T07:00|715|2026-07-07T07:10:25.771422+00:00|2026-07-14T06:58:14.558161+00:00
   2026-07-21T06:59|695|2026-07-14T13:08:59.977989+00:00|2026-07-21T06:51:11.897695+00:00
   2026-07-21T07:00|716|2026-07-14T13:03:59.572692+00:00|2026-07-21T06:56:12.251319+00:00
   2026-07-28T06:59|820|2026-07-21T07:26:14.796311+00:00|2026-07-28T06:57:41.682283+00:00
   2026-07-28T07:00|835|2026-07-21T07:21:14.398451+00:00|2026-07-28T06:52:41.286691+00:00
   2026-08-04T06:59|879|2026-07-28T07:12:43.076279+00:00|2026-08-04T06:40:12.210196+00:00
   2026-08-04T07:00|887|2026-07-28T07:02:42.089937+00:00|2026-08-04T06:55:18.833504+00:00
   2026-08-11T06:59|734|2026-08-04T07:05:28.226125+00:00|2026-08-10T08:45:02.808527+00:00
   2026-08-11T07:00|925|2026-08-04T07:00:25.470231+00:00|2026-08-10T10:30:45.488589+00:00
   2026-08-18T06:59|17|2026-08-11T07:14:54.735375+00:00|2026-08-11T09:46:03.355488+00:00
   2026-08-18T07:00|15|2026-08-11T07:12:48.852510+00:00|2026-08-11T09:30:58.182858+00:00
   ```

   However, the operational mechanism should prefer fresh provider `resets_at` and use “next Tuesday 07:00 UTC” only as a clearly marked fallback. Six observations cannot prove Anthropic will never change the anchor, especially across account or plan changes.

5. **blocking: The 1.0 pp/working-hour denominator is partly circular and is presented as capacity rather than a schedule assumption.** [`docs/tasks/186/research.md:16`](docs/tasks/186/research.md:16), [`docs/tasks/186/research.md:273`](docs/tasks/186/research.md:273)

   The 98-hour denominator is obtained by selecting the 06:00–20:00 MSK band because the same consumption history places 97% of consumption there, then dividing the quota by that selected band. This guarantees a tidy “sustainable pace” for the historical activity envelope; it does not measure how many future productive hours exist or how much work one hour represents.

   It also counts 14 hours on every weekend day as “working,” while later evaluating downtime in terms of human work lost. The document acknowledges schedule drift but still uses 1.0 as a universal operational baseline. The policy needs either:

   - a schedule defined independently before examining quota consumption, or
   - a rolling empirical activity profile explicitly treated as a model input.

   Until then, `1.0 pp/hour` is an allocation assumption, not a measured sustainable throughput.

6. **blocking: The claim that all 1,653 no-reset 5h zeros are honest is not established and the class overlaps suspicious records.** [`docs/tasks/186/research.md:99`](docs/tasks/186/research.md:99)

   Only 342 rows contain direct provider evidence. The remaining 1,311 have no provider payload. Exact breakdown:

   ```text
   Q8 complete zero breakdown
   1653|1547|106|0|342|1311
   ```

   Columns are `total | seven_day_pct>0 | seven_day_pct=0 | seven_day_pct NULL | provider evidence | empty provider`.

   Of the empty-provider subset, 1,205 have positive weekly utilization and an adjacent row with the same weekly value:

   ```text
   Q3 zero classes by provider evidence
   1547|342|1205|0|1.0|100.0

   Q4 empty-provider alleged honest zeros by adjacent weekly behavior
   1205|1205
   ```

   That is useful circumstantial evidence that those 1,205 were pauses rather than total source failures, but it does not directly prove the 5h value. More importantly, 106 of the stated 1,653 also have `7d=0`; this broad class therefore includes rows requiring further subdivision, including the known empty-reset artefact pattern. The document must not generalize the 342 provider-confirmed rows to all 1,653 without a false-positive audit for the exact classifier used downstream.

7. **suggestion: Two internal numeric descriptions are plainly inconsistent.** [`docs/tasks/186/research.md:287`](docs/tasks/186/research.md:287), [`docs/tasks/186/research.md:480`](docs/tasks/186/research.md:480)

   The document twice calls 45 pp “треть недельного пула.” It is 45%, not one third. This matters because it appears in the argument that one day consumed an extreme fraction of capacity.

   Separately, “10% самых длинных ходов” is not what the shown table measures: the cutoff is by `cost_usd`, not demonstrated turn duration or tool-call count. Expensive and long may correlate, but “longest” is presented as measured without that measurement.

## Verdict

**Reject as an operational policy pending revision.**

The calendar anchor is well supported by this snapshot, and the tariff boundaries remain plausible. The central deployment conclusions—`D > 14`, “≤13% means safe,” the tariff proof via non-overlapping CIs, universal 1.0 pp/working-hour pace, and cleanliness of all 1,653 zero rows—are not established at the confidence claimed. Implementing them now could suppress or redirect the whole Claude agent team based on a cross-tariff, n=4 classifier with no safe Max-20 control.

## Round (2026-08-11T10:20:13Z)

## Re-review status

1. **FIXED** — Pair-filter description now matches the computation, and the biased `Δ7d > 0` alternative is correctly rejected.

2. **PARTIALLY FIXED** — Safe-side permission was removed, but “неделя УЖЕ решена” and H5 “CONFIRMED” still overstate a detector observed in only two Max-20 incidents.

3. **PARTIALLY FIXED** — Tariff identity is now attributed to user testimony, but line 204 still categorically says “Смена тарифа обнуляет” as though the database established the cause.

4. **FIXED** — Live `resets_at` is primary and the Tuesday anchor is explicitly a fallback.

5. **PARTIALLY FIXED** — The direct answer calls 1.0 a normative allocation, but lines 362, 365, and 587 still call it “устойчивый.”

6. **FIXED** — The 1,653-row class is correctly decomposed, and direct versus circumstantial evidence is clearly separated.

7. **PARTIALLY FIXED** — “45%” and “самых дорогих” were fixed in the main section, but line 577 still says “треть пула,” while lines 376 and 541 still infer turn length from cost.

## New findings

- **suggestion:** [`docs/tasks/186/research.md:208`](docs/tasks/186/research.md:208) — The claim that `ΣΔ5h ≥ 40` makes weekly-counter quantization error “less than 3%” uses the wrong denominator. In segment C, a 40 pp 5h increase predicts only `40 × 0.07 = 2.8 pp` weekly growth; a one-percentage-point weekly quantum is roughly 36% of that signal, not under 3%. The cutoff may still yield a useful aggregate estimator, but its stated justification and narrow CIs are invalid.

- **suggestion:** [`docs/tasks/186/research.md:210`](docs/tasks/186/research.md:210) — Bootstrapping individual 5h windows assumes independent units, but adjacent windows share one cumulative, quantized weekly counter: endpoint rounding error carries between windows, and windows within the same weekly/account episode share workload and gating conditions. Bootstrap by weekly/account episode or report the window estimates descriptively; there are too few independent weekly clusters for the current CIs to carry strong inferential weight.

## Verdict

Substantially improved, but not yet clean enough to treat its confidence intervals or categorical “week already decided” language as measured facts. The observed ordering A≈D>C looks robust; the claimed precision does not.

## Round 2

> **Оставшиеся 1 311 строк прямого доказательства не имеют** — `provider_usage` у них пуст, потому
