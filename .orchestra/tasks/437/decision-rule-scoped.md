# #437 preregistration — superseded partial-coverage scoped decision

Status: **SUPERSEDED BEFORE ANY LIVE FABLE OBSERVATION.** The `142.225996` coefficient came from one laptop Orchestra database covering about 14% of account consumption. Full four-source coverage changed the output coefficient to `15.68`. The replacement is `decision-rule-full-coverage.md`; this file remains as the immutable record of the rejected 72,704-token design.

## Authorization and hard limits

- Authorized non-fallback Fable output target: **72,704 tokens**.
- Fable-scoped weekly hard stop: **+7 p.p. from the fresh baseline**.
- Shared Claude weekly hard stop: **15% absolute utilization**.
- Outcome: Fable-scoped weekly counter only. The shared five-hour counter is descriptive and cannot decide the hypothesis.
- No `/api/usage`; every boundary uses fresh `https://api.anthropic.com/api/oauth/usage` telemetry.

## Frozen sensitivity conversion

- Primary five-hour output coefficient: `B = 142.225996 %/MTok` from arm A in `regression-results.json`.
- Frozen 72-hour five-hour→weekly conversion: `r = 54/335 = 0.16119402985074627`.
- Fable allowance is 50% of shared weekly, so the raw-token Fable-scoped slope is
  `S = B × r / 0.5 = 45.85196288955224 scoped p.p./MTok`.
- Sensitivity output coefficients `127.990740..148.908543` imply raw scoped movement
  `2.99996..3.49025 p.p.` at the authorized target.

## Hypotheses and predictions

For actual uncontaminated Fable output `T`:

- `H_raw`: `P_raw = S × T / 1,000,000`.
- `H_price`: output is weighted by the 2× Fable/Opus API output price, so `P_price = 2 × P_raw`.

At `T=72,704`, primary predictions are `P_raw=3.33362` and `P_price=6.66724` scoped p.p.; their difference is `3.33362 p.p.`. The worst-sensitivity difference remains approximately `3.000 p.p.`.

## Call shape and stop behavior

- Three sequential Fable calls request `24,235 + 24,235 + 24,234 = 72,704` repetitions. Actual `usage.output_tokens`, not requested repetitions, determines power and prediction.
- No parallel calls. Each call records monotonic wall time and load average.
- Before each further call, project budget conservatively: `current scoped spend + maximum scoped delta of any completed Fable call`. Projected value above 7 → stop before the call.
- Observed scoped spend ≥7 after a call → stop; do not replace, retry, or top up.
- Shared weekly utilization >15 after a call → stop.
- A changed five-hour, weekly, or Fable-scoped reset timestamp, or unavailable/429 fresh telemetry → stop with no retry.

## Actual-model and safeguard rule

Every assistant message's `message.model` and every `modelUsage` entry is recorded.

A requested-Fable interval is uncontaminated only when every assistant message reports Fable 5.1 and no Opus entry has positive output. If safeguards substitute Opus:

- exclude the entire interval's scoped counter delta and all output tokens from the decision numerator/denominator;
- retain its counter delta in the budget ledger;
- list the excluded call and actual models in the report;
- never prorate its counter movement;
- do not exceed either hard stop to replace excluded output.

## Decision zones frozen before observation

Let `D` be the sum of Fable-scoped counter deltas across uncontaminated intervals and `T` their actual output. Recompute `P_raw` and `P_price` from `T`.

Conservative integer-resolution bands:

- `I_raw = [P_raw - 1, P_raw + 1]`;
- `I_price = [P_price - 1, P_price + 1]`.

Mapping:

- `RAW_TOKEN_WEIGHT`: `D` is inside `I_raw` and outside `I_price`.
- `API_PRICE_WEIGHT`: `D` is inside `I_price` and outside `I_raw`.
- `INCONCLUSIVE_OVERLAP`: `D` is inside both. The nearer prediction must not be chosen.
- `INCONCLUSIVE_NOISE`: `D` is inside neither.
- `INCONCLUSIVE_UNDERPOWERED`: `P_price - P_raw < 3`, including an early hard stop.
- `INCONCLUSIVE_FALLBACK`: excluded fallback output leaves the run below target/power.
- `INCONCLUSIVE_RESET` or `INCONCLUSIVE_TELEMETRY`: the matching quota/reset contract failed.

All applicable inconclusive labels are reported. An inconclusive result is final; no post-hoc band, coefficient, target, or tie-break change is allowed.

## Report contract

Report:

- observed `D`, actual `T`, `P_raw`, `P_price`, both intervals, and mapped zone;
- baseline/final Fable-scoped and shared weekly counters, with actual spends;
- every call's wall time, output tokens, tokens/second, and load average;
- every assistant-message model and model-usage key;
- every excluded call and reason;
- every stop condition reached.

The earlier five-hour `decision-rule.md` receives no observations and cannot be used for the verdict.
