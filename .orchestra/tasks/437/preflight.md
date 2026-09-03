# #437 preflight evidence — live sensitivity and timestamp filter

No Fable call had been made when these checks ran.

> **SUPERSEDED SENSITIVITY:** the local regression and live-window check cover only laptop Orchestra, about 14% of account consumption. They remain correct for that source but cannot estimate the shared-account tariff. Full four-source evidence supplied later changes output from ~142 to 15.68%/MTok and cache-write from locally unidentifiable to 1.71%/MTok. See `decision-rule-full-coverage.md`.

## Regression reproduction

Frozen harness commit: `990110f2`; result commit: `4a27deec`; raw structured result: `regression-results.json`.

| Arm | N | read %/MTok | write %/MTok | output %/MTok | intercept | control R² | extended R² | ΔR² |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A all windows/all turns | 77 | −0.163 | 4.040 | 127.765 | 24.224 | .3680 | .3836 | .0157 |
| B quota-observed turns | 77 | −0.160 | 2.577 | 140.028 | 25.463 | .3709 | .3775 | .0066 |
| C ≥1h and ≥5 quota rows | 64 | −0.165 | 1.568 | 129.574 | 34.991 | .3329 | .3357 | .0029 |
| D uncapped | 72 | −0.132 | 2.397 | 118.783 | 24.039 | .3229 | .3295 | .0066 |

The table lists extended coefficients and both model fits. The control output coefficients before adding write are 127.99–148.91%/MTok; cache-read is −0.117…−0.155%/MTok.

- Control gate passes in every arm: positive output and absolute read/output ratio <.0013.
- Cache-write coefficient is **not distinguishable from zero**: its 95% interval includes zero in every arm (`[-1.77,9.85]`, `[-3.14,8.30]`, `[-4.48,7.62]`, `[-3.33,8.13]`). Do not call the external `0.13` coefficient reproduced.
- Cache-write is not hidden by severe collinearity: VIF 3.29–6.14; standardized condition number 5.00–5.32. The local evidence supports only “no independently detectable write effect at this noise/sample,” not an exact zero.
- R² 0.323–0.384 means roughly 62–68% of window movement remains unexplained. Every coefficient is a sign/order estimate, not a precise subscription tariff.

## Why the reported 3-hour live contradiction was false

The reported snapshot was “142 Opus turns, 458,176 output tokens in the last 3 hours.” Its exact count was reproduced by this SQL shape:

```sql
WHERE ts >= datetime('now', '-3 hours')
```

`turn_usage.ts` is stored as ISO text with `T`, for example `2026-09-01T03:49:11...`. SQLite `datetime()` emits `2026-09-01 16:...` with a space. Within the same date, lexical comparison sees `T > space`, so every row on September 1 passes regardless of hour.

Observed after one additional turn:

```text
broken SQLite filter: 143 turns, 463,533 output, first=03:49:11
correct Python ISO cutoff: 85 turns, 271,347 output over the actual last 3h
```

At the earlier snapshot the broken form produced the reported 142/458,176 exactly. The “three-hour” numerator crossed multiple five-hour windows and could not be compared with the current 19% counter.

## Correct current-window positive control

Fresh upstream at `2026-09-01T19:12:16Z` reported five-hour 20%, next reset `22:50:00Z`, weekly 3%, Fable-scoped 1%.

The actual reset is visible in `turn_usage` as `86% at 17:57:09 → 1% at 18:00:34`; subtracting five hours from the provider's jittering `resets_at` would have started at 17:50 and incorrectly included pre-reset rows.

From the first post-reset turn through the live snapshot:

```text
34 Claude turns
147,164 output tokens
84,907,979 cache-read tokens
1,431,794 cache-write tokens
counter 1% → 20%, movement 19 p.p.
realized output sensitivity = 19 / 0.147164 = 129.11 p.p./MTok
```

`129.11` lies inside the frozen A–D control range `127.99–148.91`; the claimed threefold sensitivity loss is refuted.

## Consequence for live design

- If the noisy shared five-hour counter is the outcome, 23.5k Fable output separates raw/price predictions by >3 five-hour p.p., but unrelated Opus traffic contaminates it.
- If the noise-free Fable-scoped weekly counter is the outcome, the historical conversion gives raw slope `2 × (54/335) × 142.226 = 45.856 scoped p.p./MTok`; ≥3 scoped-p.p. separation requires 65.4k primary or 72.7k sensitivity-safe output.
- At 72.8k output, expected Fable-scoped movement is about 3.34 p.p. raw or 6.68 p.p. price-weighted; a 7 p.p. ceiling is required after rounding.
- Current 1 p.p. ceiling cannot deliver a noise-free scoped discriminator. No Fable call is authorized until the owner chooses the target/cap.
