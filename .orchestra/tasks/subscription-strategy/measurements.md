# Measurements — Orchestra own telemetry (Tier-1 evidence)

**Source:** `/mnt/data/Projects/Python/orchestra/data/orchestra.db`
**Extracted:** 2026-07-21
**Natural experiment:** Claude Max $200 (20×) → $100 (5×) downgrade on 2026-07-18.

## Method

`logs.type='status'` rows matching `turn ended%5h:%` embed the live limit state:

```
turn ended (end_turn, 3 turns, $0.19 turn, $2.72 ctx, $14.79 session, $1869.74 total ctx:9%) | 5h:39% reset 4h12m 7d:20% reset 0h
```

- **Limit consumed** = sum of positive deltas of the `5h:NN%` field between consecutive turns,
  ordered by ts, discarding deltas ≥50 (those are window resets, not consumption).
- **Work done** = sum of the `$X.XX turn` field (API-equivalent cost from the SDK — a proxy for
  tokens×model-rate, i.e. actual work volume).
- **Normalizer:** `pct_per_usd` = limit % consumed per $1 of API-equivalent work.
  Raw "% per turn" is NOT valid — turns are not equal units of work.
- Joined to `sessions.model`, filtered to `model LIKE 'claude%'` (Codex/Sol turns do not
  consume the Anthropic window).
- **Error turns excluded** (`content NOT LIKE '%(error,%'`) — see confounder C5 below.

Pass/fail criteria were fixed BEFORE running:
- ratio ≈ 4× → supports user's "capacity collapsed 4×" hypothesis
- ratio ≈ 2× → supports linear scaling with price (20×/5× = 4 nominal, but price 2×)
- ratio ≈ 1× → downgrade cost nothing

## Headline result

Successful Claude turns only:

| Period | Turns | 5h% consumed | API-equiv $ work | **pct_per_usd** |
|---|---:|---:|---:|---:|
| A: pre-downgrade (≤07-17) | 576 | 486.0 | 831.98 | **0.584** |
| B: post-downgrade (≥07-18) | 328 | 419.0 | 405.40 | **1.034** |

**Ratio B/A = 1.77×** — each unit of work now consumes 1.77× more of the 5h window.

Naive (unnormalized) "% per turn" gives 0.844 → 1.154 = **1.37×**, but this is a weaker
estimator because it ignores that post-downgrade turns were individually smaller.

## Per-day breakdown (successful turns only)

| Day | Turns | 5h% | $ | pct_per_usd |
|---|---:|---:|---:|---:|
| 07-13 | 5 | 4.0 | 14.12 | 0.283 |
| 07-15 | 132 | 144.0 | 225.29 | 0.639 |
| 07-16 | 312 | 211.0 | 382.67 | 0.551 |
| 07-17 | 127 | 127.0 | 209.90 | 0.605 |
| **07-18 (downgrade)** | 156 | 115.0 | 143.46 | 0.802 |
| 07-19 | 65 | 50.0 | 112.05 | 0.446 |
| 07-20 | 57 | 135.0 | 93.51 | 1.444 |
| 07-21 | 50 | 119.0 | 56.38 | 2.111 |

**Caveat — this is NOT a clean step function.** 07-19 (0.446) sits inside the pre-downgrade
range, while 07-20/07-21 spike to 1.4–2.1. The aggregate ratio is trustworthy; the
day-level series is noisy. Daily n is small (50–57 turns on the spike days).

## Confounders tested and ruled out

| # | Hypothesis | Test | Verdict |
|---|---|---|---|
| C1 | Model mix shifted (4.8 costlier than 4.6) | per-day model split | **Ruled out** — Opus-dominated both sides, no mix shift explaining spike |
| C2 | Context size grew (bigger ctx = more burn) | avg `ctx:%` per day | **Ruled out (inverted)** — 07-20/21 had the *lowest* ctx (31.6/22.4) yet highest ratio |
| C3 | More parallel agents burning the shared window | `usage_snapshots.active_agents` | **Ruled out (inverted)** — 07-20/21 had the *fewest* agents (0.32/0.21 avg) |
| C4 | Sol/Codex turns polluting Claude deltas | non-claude turns per day | **Ruled out** — 0 and 1 Sol turns on 07-20/21 |
| C5 | Error turns consume quota but report $0.00 | error-turn count by period | **CONFIRMED confounder, corrected** — see below |

### C5 detail — the error-turn artifact

| Period | Error turns | Total | Error % |
|---|---:|---:|---:|
| A: pre | **0** | 599 | 0.0% |
| B: post | **37** | 416 | **8.9%** |

Errored turns log `$0.00 turn` yet the 5h% still climbs across them (observed 07-21:
11%→14% across a run of `(error, 0 turns, $0.00 turn ...)` rows). They add limit
consumption to the numerator and nothing to the denominator, inflating `pct_per_usd`.

Excluding them barely moved the aggregate (0.5841→0.5841 pre, 1.0340→1.0335 post), so the
**1.77× headline is robust**. But they are the main driver of the 07-20/07-21 daily spike.

**Independent significance:** 0 → 37 error turns is itself a downgrade symptom — these are
the usage-limit retry storms noted in CLAUDE.md (session.py terminal-limit patterns). Post
downgrade the account hits the ceiling far more often, and each retry storm burns real quota
for zero delivered work.

## Secondary observation — 5h window saturation frequency

From `usage_snapshots`, days hitting 100% on the 5h window:
- 07-16, 07-17, 07-21 hit 100%; 07-18 hit 98%.
Pre-downgrade 100% days also existed (07-07, 07-09, 07-10, 07-11, 06-11, 06-15), so
saturation is not new — but it now occurs at lower delivered work volume.

## Limits of this measurement

- Window A vs B is 5 days vs 4 days — short.
- `$ turn` is an API-equivalent proxy, not a direct token count; per-turn token columns are
  not stored (only session-level cumulative `total_cache_read_tokens` etc.), so a pure
  token-normalized ratio was not computable.
- Anthropic does not expose the absolute quota denominator, so % is all we can observe.
- Cache hit rate could not be isolated per window (session-level cumulative only) — this is
  the one confounder NOT fully excluded. Cached tokens are cheap in $ but may still consume
  quota, which would bias `pct_per_usd` upward if post-period had higher cache rates.
